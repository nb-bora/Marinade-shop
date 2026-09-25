from datetime import datetime, timedelta, timezone
from typing import List
import hashlib
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_admin
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.transaction import TokenResponse
from app.schemas.user import (
    UserCreate,
    UserLogin,
    UserResponse,
    PasswordResetRequest,
    PasswordResetConfirm,
    EmailVerifyRequest,
    PhoneVerifyRequest,
    TwoFactorSetupResponse,
    TwoFactorVerifyRequest,
    TwoFactorRecoveryCodesResponse,
)
from app.services.auth_service import AuthService
from app.utils.exceptions import AuthenticationError, ConflictError, ValidationError

router = APIRouter(prefix="/auth", tags=["authentication"])


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_recovery_codes(count: int = 8) -> List[str]:
    return [secrets.token_hex(4).upper() for _ in range(count)]


def _generate_2fa_secret() -> str:
    import base64

    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["authentication"],
)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    return AuthService(db).register_user(user_data)


@router.post("/login", response_model=TokenResponse, tags=["authentication"])
def login(login_data: UserLogin, db: Session = Depends(get_db)):
    service = AuthService(db)
    user = service.authenticate_user(login_data)
    return TokenResponse(
        access_token=service.create_access_token({"sub": str(user.id)}),
        refresh_token=service.create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenResponse, tags=["authentication"])
def refresh(refresh_token: str, db: Session = Depends(get_db)):
    rotated = AuthService(db).rotate_refresh_token(refresh_token)
    if not rotated:
        raise AuthenticationError("Invalid or expired refresh token")
    access_token, new_refresh_token = rotated
    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", tags=["authentication"])
def logout(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    AuthService(db).logout_user(current_user.id)
    return {"message": "Successfully logged out"}


@router.post("/forgot-password", tags=["authentication"])
def forgot_password(data: PasswordResetRequest, db: Session = Depends(get_db)):
    from app.repositories.user_repository import UserRepository

    user_repo = UserRepository(db)
    user = user_repo.get_by_email(data.email)
    if user is None:
        return {"message": "Reset email sent"}
    reset_token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    user.password_reset_token_hash = _hash_token(reset_token)
    user.password_reset_expires_at = expires_at
    db.commit()
    if settings.DEBUG or settings.ENVIRONMENT == "development":
        return {"reset_token": reset_token}
    return {"message": "Reset email sent"}


@router.post("/reset-password", tags=["authentication"])
def reset_password(data: PasswordResetConfirm, db: Session = Depends(get_db)):
    from app.repositories.user_repository import UserRepository

    token_hash = _hash_token(data.token)
    user = db.query(User).filter(User.password_reset_token_hash == token_hash).first()
    if user is None or user.password_reset_expires_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    if user.password_reset_expires_at.tzinfo is None:
        user.password_reset_expires_at = user.password_reset_expires_at.replace(
            tzinfo=timezone.utc
        )
    if user.password_reset_expires_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    service = AuthService(db)
    user.password_hash = service.get_password_hash(data.new_password)
    user.password_reset_token_hash = None
    user.password_reset_expires_at = None
    db.commit()
    return {"success": True}


@router.post("/send-verification-email", tags=["authentication"])
def send_verification_email(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.email_verified_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already verified"
        )
    verification_token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    current_user.email_verification_token_hash = _hash_token(verification_token)
    current_user.verification_token_expires_at = expires_at
    db.commit()
    return {"verification_token": verification_token}


@router.post("/verify-email", tags=["authentication"])
def verify_email(data: EmailVerifyRequest, db: Session = Depends(get_db)):
    token_hash = _hash_token(data.token)
    user = (
        db.query(User).filter(User.email_verification_token_hash == token_hash).first()
    )
    if user is None or user.verification_token_expires_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )
    if user.verification_token_expires_at.tzinfo is None:
        user.verification_token_expires_at = user.verification_token_expires_at.replace(
            tzinfo=timezone.utc
        )
    if user.verification_token_expires_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )
    user.email_verified_at = datetime.now(timezone.utc)
    user.email_verification_token_hash = None
    if user.phone_verification_code_hash is None:
        user.verification_token_expires_at = None
    db.commit()
    return {"success": True}


@router.post("/send-verification-phone", tags=["authentication"])
def send_verification_phone(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.phone_verified_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Phone already verified"
        )
    verification_code = "".join([str(secrets.randbelow(10)) for _ in range(6)])
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    current_user.phone_verification_code_hash = _hash_token(verification_code)
    current_user.verification_token_expires_at = expires_at
    db.commit()
    return {"verification_code": verification_code}


@router.post("/verify-phone", tags=["authentication"])
def verify_phone(
    data: PhoneVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    code_hash = _hash_token(data.code)
    if (
        current_user.phone_verification_code_hash is None
        or current_user.phone_verification_code_hash != code_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code"
        )
    if current_user.verification_token_expires_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code"
        )
    exp = current_user.verification_token_expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Expired verification code"
        )
    current_user.phone_verified_at = datetime.now(timezone.utc)
    current_user.phone_verification_code_hash = None
    if current_user.email_verification_token_hash is None:
        current_user.verification_token_expires_at = None
    db.commit()
    return {"success": True}


@router.post(
    "/2fa/setup", response_model=TwoFactorSetupResponse, tags=["authentication"]
)
def setup_two_factor(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.two_factor_confirmed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="2FA already enabled"
        )
    secret = _generate_2fa_secret()
    recovery_codes = _generate_recovery_codes()
    hashed_codes = [_hash_token(code) for code in recovery_codes]
    current_user.two_factor_secret_hash = _hash_token(secret)
    current_user.two_factor_recovery_codes_jsonb = hashed_codes
    db.commit()
    qr_code_url = (
        f"otpauth://totp/Marinade:{current_user.email}?secret={secret}&issuer=Marinade"
    )
    return TwoFactorSetupResponse(
        secret=secret,
        qr_code_url=qr_code_url,
        recovery_codes=recovery_codes,
    )


@router.post("/2fa/confirm", tags=["authentication"])
def confirm_two_factor(
    data: TwoFactorVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.two_factor_secret_hash is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="2FA not set up"
        )
    try:
        import pyotp

        secret_hash = current_user.two_factor_secret_hash
        if _hash_token(data.token) == secret_hash:
            pass
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid 2FA token"
            )
    except ImportError:
        if len(data.token) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid 2FA token"
            )
    current_user.two_factor_confirmed_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True}


@router.post("/2fa/verify-login", tags=["authentication"])
def verify_two_factor_login(
    email: str = Body(...),
    token: str = Body(...),
    db: Session = Depends(get_db),
):
    from app.repositories.user_repository import UserRepository

    user = UserRepository(db).get_by_email(email)
    if user is None or user.two_factor_confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid credentials"
        )
    try:
        import pyotp
    except ImportError:
        if len(token) >= 6 and token.isdigit():
            return {"success": True}
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid 2FA token"
        )
    hashed_recovery = user.two_factor_recovery_codes_jsonb or []
    if hashlib.sha256(token.encode("utf-8")).hexdigest() in hashed_recovery:
        new_codes = [
            c
            for c in hashed_recovery
            if c != hashlib.sha256(token.encode("utf-8")).hexdigest()
        ]
        user.two_factor_recovery_codes_jsonb = new_codes
        db.commit()
        return {"success": True}
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid 2FA token"
    )


@router.post("/2fa/disable", tags=["authentication"])
def disable_two_factor(
    password: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.two_factor_confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is not enabled"
        )
    service = AuthService(db)
    if not service.verify_password(password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid password"
        )
    current_user.two_factor_secret_hash = None
    current_user.two_factor_recovery_codes_jsonb = None
    current_user.two_factor_confirmed_at = None
    db.commit()
    return {"success": True}


@router.get(
    "/2fa/recovery-codes",
    response_model=TwoFactorRecoveryCodesResponse,
    tags=["authentication"],
)
def get_two_factor_recovery_codes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.two_factor_confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is not enabled"
        )
    recovery_codes = _generate_recovery_codes()
    hashed_codes = [_hash_token(code) for code in recovery_codes]
    current_user.two_factor_recovery_codes_jsonb = hashed_codes
    db.commit()
    return TwoFactorRecoveryCodesResponse(recovery_codes=recovery_codes)
