from typing import Any, Dict

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.transaction import TokenResponse
from app.schemas.user import (
    UserCreate,
    UserLogin,
    UserResponse,
    PasswordConfirmRequest,
    PasswordResetRequest,
    PasswordResetConfirm,
    EmailVerifyRequest,
    PhoneVerifyRequest,
    TwoFactorSetupResponse,
    TwoFactorVerifyRequest,
    TwoFactorRecoveryCodesResponse,
)
from app.services.auth_service import AuthService
from app.utils.exceptions import AuthenticationError, ValidationError

router = APIRouter(prefix="/auth", tags=["authentication"])


def _dev_only(**secrets_by_name: str) -> Dict[str, Any]:
    """Expose verification secrets in the response ONLY when explicitly enabled.

    Without an email/SMS provider a developer has no other way to complete these
    flows locally. The flag defaults to false and the configuration validator
    refuses to boot in production with it on, so a real deployment can never
    return a token that proves nothing about who receives it.
    """
    return dict(secrets_by_name) if settings.DEV_EXPOSE_AUTH_TOKENS else {}


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["authentication"],
)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    return AuthService(db).register_user(user_data)


@router.post(
    "/login",
    response_model=TokenResponse,
    tags=["authentication"],
    description=(
        "Si la 2FA est activée sur le compte, `two_factor_code` (code TOTP à 6 "
        "chiffres ou code de secours) est obligatoire ; sinon la réponse est 401 "
        "avec `details.two_factor_required = true`."
    ),
)
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
    # Même réponse que le compte existe ou non, pour ne pas révéler les comptes.
    token = AuthService(db).forgot_password(data.email)
    return {"message": "Reset email sent", **_dev_only(reset_token=token)}


@router.post("/reset-password", tags=["authentication"])
def reset_password(data: PasswordResetConfirm, db: Session = Depends(get_db)):
    AuthService(db).reset_password(data.token, data.new_password)
    return {"success": True}


@router.post("/send-verification-email", tags=["authentication"])
def send_verification_email(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    token = AuthService(db).send_email_verification(current_user.id)
    return {"message": "Verification email sent", **_dev_only(verification_token=token)}


@router.post("/verify-email", tags=["authentication"])
def verify_email(data: EmailVerifyRequest, db: Session = Depends(get_db)):
    AuthService(db).verify_email(data.token)
    return {"success": True}


@router.post("/send-verification-phone", tags=["authentication"])
def send_verification_phone(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    code = AuthService(db).send_phone_verification(current_user.id)
    return {"message": "Verification code sent", **_dev_only(verification_code=code)}


@router.post("/verify-phone", tags=["authentication"])
def verify_phone(
    data: PhoneVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    AuthService(db).verify_phone(current_user.id, data.code)
    return {"success": True}


def _require_password(service: AuthService, user: User, password: str) -> None:
    if not service.verify_password(password, user.password_hash):
        raise ValidationError("Invalid password")


@router.post(
    "/2fa/setup", response_model=TwoFactorSetupResponse, tags=["authentication"]
)
def setup_two_factor(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return AuthService(db).setup_two_factor(current_user.id)


@router.post("/2fa/confirm", tags=["authentication"])
def confirm_two_factor(
    data: TwoFactorVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    AuthService(db).confirm_two_factor(current_user.id, data.token)
    return {"success": True}


@router.post("/2fa/disable", tags=["authentication"])
def disable_two_factor(
    data: PasswordConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = AuthService(db)
    if current_user.two_factor_confirmed_at is None:
        raise ValidationError("2FA is not enabled")
    _require_password(service, current_user, data.password)
    service.disable_two_factor(current_user.id)
    return {"success": True}


@router.post(
    "/2fa/recovery-codes",
    response_model=TwoFactorRecoveryCodesResponse,
    tags=["authentication"],
    description=(
        "Génère un nouveau jeu de codes de secours et invalide les précédents. "
        "Exige le mot de passe."
    ),
)
def regenerate_recovery_codes(
    data: PasswordConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = AuthService(db)
    _require_password(service, current_user, data.password)
    return TwoFactorRecoveryCodesResponse(
        recovery_codes=service.regenerate_recovery_codes(current_user.id)
    )
