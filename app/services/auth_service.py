from datetime import datetime, timedelta, timezone
from typing import Optional, Union, List
import hashlib
import hmac
import re
import secrets
import uuid

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User
from app.repositories.transaction_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import (
    UserCreate,
    UserLogin,
    TwoFactorSetupResponse,
)
from app.utils.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
    BusinessLogicError,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

try:
    import pyotp

    _PYOTP_AVAILABLE = True
except ImportError:
    _PYOTP_AVAILABLE = False
    import base64
    import struct
    import time


def validate_email(email: str) -> bool:
    if not email or "@" not in email or ".." in email:
        return False
    local_part = email.split("@", 1)[0]
    if local_part.startswith(".") or local_part.endswith("."):
        return False
    return (
        re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email) is not None
    )


class _FallbackTOTP:
    def __init__(self, secret: str, digits: int = 6, interval: int = 30):
        self.secret = secret
        self.digits = digits
        self.interval = interval

    @staticmethod
    def _base32_decode(secret: str) -> bytes:
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
        secret = secret.upper().rstrip("=")
        bits = ""
        for char in secret:
            if char not in alphabet:
                continue
            idx = alphabet.index(char)
            bits += format(idx, "05b")
        padding = len(bits) % 8
        if padding:
            bits = bits[:-padding]
        result = bytearray()
        for i in range(0, len(bits), 8):
            result.append(int(bits[i : i + 8], 2))
        return bytes(result)

    def _generate(self, counter: int) -> str:
        key = self._base32_decode(self.secret)
        msg = struct.pack(">Q", counter)
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        binary = (
            ((digest[offset] & 0x7F) << 24)
            | ((digest[offset + 1] & 0xFF) << 16)
            | ((digest[offset + 2] & 0xFF) << 8)
            | (digest[offset + 3] & 0xFF)
        )
        otp = binary % (10**self.digits)
        return str(otp).zfill(self.digits)

    def now(self) -> str:
        counter = int(time.time() // self.interval)
        return self._generate(counter)

    def verify(self, token: str, valid_window: int = 1) -> bool:
        token = token.strip()
        if len(token) != self.digits or not token.isdigit():
            return False
        now_counter = int(time.time() // self.interval)
        for offset in range(-valid_window, valid_window + 1):
            if hmac.compare_digest(self._generate(now_counter + offset), token):
                return True
        return False

    def provisioning_uri(self, name: str, issuer_name: Optional[str] = None) -> str:
        label = f"{issuer_name}:{name}" if issuer_name else name
        params = f"secret={self.secret}&issuer={issuer_name or ''}"
        return f"otpauth://totp/{label}?{params}"


def _get_totp(secret: str):
    if _PYOTP_AVAILABLE:
        return pyotp.TOTP(secret)
    return _FallbackTOTP(secret)


def _generate_random_base32(length: int = 32) -> str:
    if _PYOTP_AVAILABLE:
        return pyotp.random_base32(length)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _send_notification_safe(
    db: Session,
    channel: str,
    recipient: str,
    subject: str,
    message: str,
) -> None:
    try:
        from app.services.notification_service import NotificationService

        ns = NotificationService(db)
        ns.send_notification(
            channel_type=channel,
            recipient=recipient,
            subject=subject,
            message=message,
        )
    except Exception as exc:
        logger.warning(f"Notification send skipped ({channel} -> {recipient}): {exc}")


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)
        self.refresh_token_repo = RefreshTokenRepository(db)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        return pwd_context.hash(password)

    def create_access_token(self, data: dict) -> str:
        now = datetime.now(timezone.utc)
        claims = {
            **data,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        }
        return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    @staticmethod
    def _hash_refresh_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_refresh_token(self, user_id: uuid.UUID) -> str:
        token = secrets.token_urlsafe(48)
        self.refresh_token_repo.create(
            {
                "user_id": user_id,
                "token_hash": self._hash_refresh_token(token),
                "expires_at": datetime.now(timezone.utc)
                + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            }
        )
        return token

    def register_user(self, user_data: UserCreate) -> User:
        if not validate_email(user_data.email):
            raise ValidationError("Invalid email format")
        if self.user_repo.email_exists(user_data.email):
            raise ConflictError("Email already registered")
        if self.user_repo.phone_exists(user_data.phone):
            raise ConflictError("Phone number already registered")

        values = user_data.model_dump()
        values["role"] = "restaurant"
        values["password_hash"] = self.get_password_hash(values.pop("password"))
        return self.user_repo.create(values)

    def authenticate_user(self, login_data: UserLogin) -> User:
        if not validate_email(login_data.email):
            raise AuthenticationError("Invalid credentials")
        user = self.user_repo.get_by_email(login_data.email)
        if (
            not user
            or not user.is_active
            or not self.verify_password(login_data.password, user.password_hash)
        ):
            raise AuthenticationError("Invalid credentials")
        return user

    def refresh_access_token(self, refresh_token: str) -> Optional[str]:
        token_obj = self.refresh_token_repo.get_by_token_hash(
            self._hash_refresh_token(refresh_token)
        )
        if not token_obj:
            return None
        expires_at = token_obj.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return None
        user = self.user_repo.get(token_obj.user_id)
        if not user or not user.is_active:
            return None
        return self.create_access_token({"sub": str(user.id)})

    def rotate_refresh_token(self, refresh_token: str) -> Optional[tuple[str, str]]:
        token_obj = self.refresh_token_repo.get_by_token_hash(
            self._hash_refresh_token(refresh_token)
        )
        if not token_obj:
            return None
        expires_at = token_obj.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return None
        user = self.user_repo.get(token_obj.user_id)
        if not user or not user.is_active:
            return None
        new_refresh = self.create_refresh_token(user.id)
        self.refresh_token_repo.delete(token_obj.id)
        return self.create_access_token({"sub": str(user.id)}), new_refresh

    def logout_user(self, user_id: uuid.UUID) -> bool:
        self.refresh_token_repo.delete_by_user_id(user_id)
        return True

    # ========== Password Reset ==========

    def forgot_password(self, email: str) -> str:
        user = self.user_repo.get_by_email(email.strip().lower())
        if not user:
            logger.info(f"forgot_password: no user for {email}, returning dummy token")
            return secrets.token_urlsafe(48)

        raw_token = secrets.token_urlsafe(48)
        token_hash = _hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.RESET_TOKEN_EXPIRE_MINUTES
        )
        self.user_repo.save_reset_token(str(user.id), token_hash, expires_at)

        _send_notification_safe(
            self.db,
            "email",
            user.email,
            "Réinitialisation de votre mot de passe - Marinade",
            f"Bonjour {user.first_name},\n\n"
            f"Voici votre lien de réinitialisation (valide {settings.RESET_TOKEN_EXPIRE_MINUTES} min) :\n"
            f"Token : {raw_token}\n\n"
            f"Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.\n\n"
            f"L'équipe Marinade",
        )

        logger.info(f"Password reset token issued for user {user.id}")
        return raw_token

    def reset_password(self, token: str, new_password: str) -> bool:
        if not token:
            raise ValidationError("Token is required")
        token_hash = _hash_token(token)
        user = self.user_repo.get_by_reset_token_hash(token_hash)
        if not user:
            raise ValidationError("Invalid or expired reset token")

        expires_at = user.password_reset_expires_at
        if expires_at is None:
            raise ValidationError("Invalid or expired reset token")
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            self.user_repo.clear_reset_token(str(user.id))
            raise ValidationError("Reset token has expired")

        new_hash = self.get_password_hash(new_password)
        self.user_repo.update(user, {"password_hash": new_hash})
        self.user_repo.clear_reset_token(str(user.id))
        logger.info(f"Password reset successful for user {user.id}")
        return True

    # ========== Email Verification ==========

    def send_email_verification(self, user_id: uuid.UUID) -> str:
        user = self.user_repo.get(str(user_id))
        if not user:
            raise NotFoundError("User not found")
        if user.email_verified_at is not None:
            raise BusinessLogicError("Email is already verified")

        raw_token = secrets.token_urlsafe(48)
        token_hash = _hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(
            hours=settings.VERIFICATION_TOKEN_EXPIRE_HOURS
        )
        self.user_repo.save_verification_token(str(user_id), token_hash, expires_at)

        _send_notification_safe(
            self.db,
            "email",
            user.email,
            "Vérification de votre email - Marinade",
            f"Bonjour {user.first_name},\n\n"
            f"Merci de vérifier votre email en utilisant ce token :\n"
            f"Token : {raw_token}\n\n"
            f"Valide pendant {settings.VERIFICATION_TOKEN_EXPIRE_HOURS}h.\n\n"
            f"L'équipe Marinade",
        )

        logger.info(f"Email verification token issued for user {user.id}")
        return raw_token

    def verify_email(self, token: str) -> User:
        if not token:
            raise ValidationError("Token is required")
        token_hash = _hash_token(token)
        user = self.user_repo.get_by_email_verification_token_hash(token_hash)
        if not user:
            raise ValidationError("Invalid or expired verification token")

        expires_at = user.verification_token_expires_at
        if expires_at is None:
            raise ValidationError("Invalid or expired verification token")
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            self.user_repo.clear_email_verification_token(str(user.id))
            raise ValidationError("Verification token has expired")

        self.user_repo.set_email_verified(str(user.id), datetime.now(timezone.utc))
        self.user_repo.clear_email_verification_token(str(user.id))
        logger.info(f"Email verified for user {user.id}")
        self.db.refresh(user)
        return user

    # ========== Phone Verification ==========

    def send_phone_verification(self, user_id: uuid.UUID) -> str:
        user = self.user_repo.get(str(user_id))
        if not user:
            raise NotFoundError("User not found")
        if user.phone_verified_at is not None:
            raise BusinessLogicError("Phone is already verified")

        code = "".join(secrets.choice("0123456789") for _ in range(6))
        code_hash = _hash_token(code)
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.RESET_TOKEN_EXPIRE_MINUTES
        )
        self.user_repo.save_phone_verification_code(str(user_id), code_hash, expires_at)

        _send_notification_safe(
            self.db,
            "sms",
            user.phone,
            "",
            f"Marinade: votre code de vérification est {code}. Valide {settings.RESET_TOKEN_EXPIRE_MINUTES} min.",
        )

        logger.info(f"Phone verification code issued for user {user.id}")
        return code

    def verify_phone(self, user_id: uuid.UUID, code: str) -> bool:
        user = self.user_repo.get(str(user_id))
        if not user:
            raise NotFoundError("User not found")
        if user.phone_verified_at is not None:
            return True

        stored_hash = user.phone_verification_code_hash
        if not stored_hash:
            raise ValidationError("No pending phone verification")
        expires_at = user.verification_token_expires_at
        if expires_at is None:
            raise ValidationError("Invalid or expired phone verification code")
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            self.user_repo.clear_phone_verification_code(str(user_id))
            raise ValidationError("Phone verification code has expired")

        given_hash = _hash_token(code.strip())
        if not hmac.compare_digest(stored_hash, given_hash):
            raise ValidationError("Invalid phone verification code")

        self.user_repo.set_phone_verified(str(user_id), datetime.now(timezone.utc))
        self.user_repo.clear_phone_verification_code(str(user_id))
        logger.info(f"Phone verified for user {user.id}")
        return True

    # ========== Two-Factor Authentication ==========

    def setup_two_factor(self, user_id: uuid.UUID) -> TwoFactorSetupResponse:
        user = self.user_repo.get(str(user_id))
        if not user:
            raise NotFoundError("User not found")
        if user.two_factor_confirmed_at is not None:
            raise BusinessLogicError(
                "2FA is already enabled; disable it first to reconfigure"
            )

        secret = _generate_random_base32(32)
        self.user_repo.save_2fa_secret(str(user_id), secret)

        raw_codes: List[str] = []
        hashed_codes: List[str] = []
        for _ in range(8):
            rc = secrets.token_hex(8)
            raw_codes.append(rc)
            hashed_codes.append(_hash_token(rc))
        self.user_repo.save_2fa_recovery_codes(str(user_id), hashed_codes)

        totp = _get_totp(secret)
        qr_code_url = totp.provisioning_uri(
            name=user.email,
            issuer_name=settings.TWO_FACTOR_ISSUER,
        )

        logger.info(f"2FA setup initiated for user {user.id}")
        return TwoFactorSetupResponse(
            secret=secret,
            qr_code_url=qr_code_url,
            recovery_codes=raw_codes,
        )

    def confirm_two_factor(self, user_id: uuid.UUID, token: str) -> bool:
        user = self.user_repo.get(str(user_id))
        if not user:
            raise NotFoundError("User not found")
        secret = self.user_repo.get_2fa_secret(str(user_id))
        if not secret:
            raise BusinessLogicError("2FA setup has not been initiated")
        if user.two_factor_confirmed_at is not None:
            raise BusinessLogicError("2FA is already confirmed")

        totp = _get_totp(secret)
        if not totp.verify(token.strip(), valid_window=1):
            raise ValidationError("Invalid 2FA token")

        self.user_repo.confirm_2fa_enabled(str(user_id), datetime.now(timezone.utc))
        logger.info(f"2FA confirmed for user {user.id}")
        return True

    def verify_two_factor_login(
        self, email_or_user: Union[str, User], token: str
    ) -> bool:
        if isinstance(email_or_user, User):
            user = email_or_user
        else:
            normalized = str(email_or_user).strip().lower()
            user = self.user_repo.get_by_email(normalized)
            if not user:
                user = self.user_repo.get_by_phone(normalized)
            if not user:
                raise AuthenticationError("Invalid credentials")

        if not user.two_factor_confirmed_at:
            return True

        token = token.strip()
        secret = self.user_repo.get_2fa_secret(str(user.id))
        if secret:
            totp = _get_totp(secret)
            if totp.verify(token, valid_window=1):
                return True

        hashed_codes = self.user_repo.get_2fa_recovery_codes(str(user.id)) or []
        given_hash = _hash_token(token)
        for idx, stored in enumerate(hashed_codes):
            if isinstance(stored, str) and hmac.compare_digest(stored, given_hash):
                remaining = [c for i, c in enumerate(hashed_codes) if i != idx]
                self.user_repo.save_2fa_recovery_codes(str(user.id), remaining)
                logger.info(
                    f"Recovery code used for user {user.id}, {len(remaining)} remain"
                )
                return True

        raise AuthenticationError("Invalid 2FA token or recovery code")

    def disable_two_factor(self, user_id: uuid.UUID) -> bool:
        user = self.user_repo.get(str(user_id))
        if not user:
            raise NotFoundError("User not found")
        if not user.two_factor_confirmed_at:
            return True
        self.user_repo.disable_2fa(str(user_id))
        logger.info(f"2FA disabled for user {user_id}")
        return True
