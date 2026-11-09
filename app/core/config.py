from typing import List, Optional
from urllib.parse import quote_plus

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_ALLOWED_JWT_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})
_DEFAULT_SECRETS = frozenset(
    {"your-secret-key-here-change-this-in-production", "changeme", "secret"}
)
_DEFAULT_DB_PASSWORDS = frozenset({"postgres", "password", "changeme", "admin", "root", ""})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "marinade"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_SSLMODE: str = "prefer"
    DB_CONNECT_TIMEOUT_SECONDS: int = 5

    SECRET_KEY: str = "your-secret-key-here-change-this-in-production"
    ALGORITHM: str = "HS256"
    # Jetons d'accès courts : une session révoquée l'est au plus tard à leur expiration
    # (en pratique immédiatement : chaque requête vérifie la session, voir dependencies).
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    # Durée d'inactivité d'une session : chaque jeton de rafraîchissement vit ce temps.
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Durée de vie absolue d'une session, rotations comprises (ASVS 7.3.2).
    SESSION_ABSOLUTE_LIFETIME_DAYS: int = 30
    JWT_ISSUER: str = "marinade-api"
    JWT_AUDIENCE: str = "marinade-clients"
    RESET_TOKEN_EXPIRE_MINUTES: int = 15
    VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24

    # --- Activation du compte par code à usage unique (envoyé par email à l'inscription) ---
    ACTIVATION_CODE_LENGTH: int = 6
    ACTIVATION_CODE_EXPIRE_MINUTES: int = 15
    # Essais incorrects tolérés avant d'invalider le code (il faut alors en demander un nouveau).
    ACTIVATION_CODE_MAX_ATTEMPTS: int = 5
    # Délai minimal entre deux envois pour un même compte.
    ACTIVATION_CODE_RESEND_SECONDS: int = 60

    # --- Emails (voir app/services/email_service.py) ---
    # auto | smtp | console | memory | disabled. « auto » : SMTP dès que les identifiants
    # sont renseignés, sinon simple journalisation (aucun email ne part).
    EMAIL_BACKEND: str = "auto"
    # Avec Gmail, l'expéditeur DOIT être l'adresse du compte SMTP (sinon réécrit par Google).
    EMAIL_FROM: str = "noreply@marinade.local"
    EMAIL_FROM_NAME: str = "Marinade"
    EMAIL_REPLY_TO: Optional[str] = None
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    # Mot de passe d'application (jamais le mot de passe du compte) ; les espaces sont ignorés.
    SMTP_PASSWORD: Optional[SecretStr] = None
    # starttls (587) | ssl (465) | none
    SMTP_SECURITY: str = "starttls"
    SMTP_TIMEOUT_SECONDS: float = 15.0
    SMTP_MAX_ATTEMPTS: int = 3
    # Adresse publique de l'interface web, pour les liens des emails.
    FRONTEND_URL: str = "http://localhost:5173"
    TWO_FACTOR_ISSUER: str = "Marinade"
    # Clé dédiée au chiffrement des secrets TOTP au repos. À défaut, SECRET_KEY
    # est utilisée : la faire tourner invalide alors les secrets 2FA existants.
    TWO_FACTOR_ENCRYPTION_KEY: Optional[str] = None

    # Développement uniquement : renvoie les jetons de vérification / réinitialisation
    # dans la réponse HTTP, faute de fournisseur email/SMS réel. Interdit en production.
    DEV_EXPOSE_AUTH_TOKENS: bool = False

    # Rôle propriétaire du schéma, utilisé par Alembic uniquement. L'application
    # doit se connecter avec un rôle non propriétaire, non superutilisateur et
    # sans BYPASSRLS, sinon les politiques RLS ne protègent rien.
    MIGRATION_DATABASE_URL: Optional[str] = None

    APP_NAME: str = "Marinade API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"
    SKIP_DB_INIT: bool = True
    ALLOW_LEGACY_PAYMENT_SIMULATION: bool = False

    ALLOW_ORIGINS: str = "http://localhost:3000"
    ALLOW_CREDENTIALS: bool = True
    ALLOW_METHODS: str = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    ALLOW_HEADERS: str = (
        "Authorization,Content-Type,X-Request-ID,X-Tenant-ID,X-Signature"
    )

    EASYTRANSACT_API_BASE_URL: Optional[str] = None
    EASYTRANSACT_API_TOKEN: Optional[str] = None
    EASYTRANSACT_WEBHOOK_SECRET: Optional[str] = None
    EASYTRANSACT_WEBHOOK_SIGNATURE_HEADER: str = "X-Signature"
    EASYTRANSACT_HTTP_TIMEOUT_SECONDS: float = 10.0
    EASYTRANSACT_WEBHOOK_MAX_BODY_BYTES: int = 1_048_576
    EASYTRANSACT_WEBHOOK_SIGNATURE_ALGORITHM: str = "hmac-sha256"
    EASYTRANSACT_STATUS_REFERENCE_PARAM: str = "vendor_reference"
    EASYTRANSACT_INITIATE_CONTENT_TYPE: str = "json"

    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # Écrans cuisine/bar : un ticket plus ancien que cette fenêtre n'est plus affiché
    # et est annulé à la clôture de sa session.
    KDS_TICKET_WINDOW_HOURS: int = 12

    # --- Sécurité HTTP (ASVS V3/V4/V13) ---
    # Documentation interactive (/docs, /redoc, /openapi.json). Vide = active hors production.
    DOCS_ENABLED: Optional[bool] = None
    # Strict-Transport-Security. Vide = active en production (TLS terminé par le proxy).
    HSTS_ENABLED: Optional[bool] = None
    HSTS_MAX_AGE_SECONDS: int = 31_536_000
    # Taille maximale d'un corps de requête JSON/formulaire hors import de fichier.
    MAX_REQUEST_BODY_BYTES: int = 6 * 1024 * 1024

    # --- Limitation de débit et verrouillage (ASVS V6.3.1 / V2.4.1) ---
    # Compteurs stockés en base (table auth_throttle) : partagés entre workers.
    RATE_LIMIT_ENABLED: bool = True
    # Échecs de connexion tolérés par identifiant avant verrouillage, puis durée du
    # premier verrouillage (doublée à chaque nouvel échec, plafonnée).
    LOCKOUT_THRESHOLD: int = 5
    LOCKOUT_BASE_SECONDS: int = 60
    LOCKOUT_MAX_SECONDS: int = 3600
    # Vérification facultative contre HaveIBeenPwned (k-anonymat, 5 premiers caractères
    # du SHA-1 seulement). La liste locale des 10 000 mots de passe courants s'applique toujours.
    PASSWORD_HIBP_CHECK: bool = False

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in {"production", "prod", "staging"}

    @property
    def docs_enabled(self) -> bool:
        return (not self.is_production) if self.DOCS_ENABLED is None else self.DOCS_ENABLED

    @property
    def hsts_enabled(self) -> bool:
        return self.is_production if self.HSTS_ENABLED is None else self.HSTS_ENABLED

    @property
    def cors_allow_credentials(self) -> bool:
        """Jamais de credentials avec l'origine « * » (Starlette refléterait toute origine)."""
        return self.ALLOW_CREDENTIALS and "*" not in self.cors_origins

    @property
    def DATABASE_URL(self) -> str:
        user = quote_plus(self.DB_USER)
        password = quote_plus(self.DB_PASSWORD)
        return f"postgresql://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?sslmode={quote_plus(self.DB_SSLMODE)}"

    @model_validator(mode="after")
    def validate_security_configuration(self):
        if self.ALGORITHM not in _ALLOWED_JWT_ALGORITHMS:
            raise ValueError(
                f"ALGORITHM must be one of {sorted(_ALLOWED_JWT_ALGORITHMS)} (HMAC, fixed server side)"
            )
        if self.SMTP_SECURITY.lower() not in {"starttls", "ssl", "none"}:
            raise ValueError("SMTP_SECURITY must be starttls, ssl or none")
        if self.EMAIL_BACKEND.lower() not in {"auto", "smtp", "console", "memory", "disabled"}:
            raise ValueError("EMAIL_BACKEND must be auto, smtp, console, memory or disabled")
        if self.is_production:
            if self.SMTP_SECURITY.lower() == "none" and self.EMAIL_BACKEND.lower() in {"auto", "smtp"}:
                raise ValueError("SMTP_SECURITY=none is forbidden in production (credentials in clear)")
            if (
                self.SECRET_KEY in _DEFAULT_SECRETS
                or len(self.SECRET_KEY) < 32
            ):
                raise ValueError(
                    "SECRET_KEY must be a private random value of at least 32 characters in production"
                )
            if self.DB_PASSWORD in _DEFAULT_DB_PASSWORDS or len(self.DB_PASSWORD) < 12:
                raise ValueError(
                    "DB_PASSWORD must not be a default value and needs at least 12 characters in production"
                )
            if self.DB_HOST not in {"localhost", "127.0.0.1", "::1"} and self.DB_SSLMODE not in {
                "require", "verify-ca", "verify-full"
            }:
                raise ValueError(
                    "DB_SSLMODE must be require, verify-ca or verify-full for a remote database in production"
                )
            if self.TWO_FACTOR_ENCRYPTION_KEY is not None and len(self.TWO_FACTOR_ENCRYPTION_KEY) < 32:
                raise ValueError("TWO_FACTOR_ENCRYPTION_KEY needs at least 32 characters")
            if self.DEBUG:
                raise ValueError("DEBUG must be false in production")
            if not self.RATE_LIMIT_ENABLED:
                raise ValueError("RATE_LIMIT_ENABLED must be true in production")
            if self.ACCESS_TOKEN_EXPIRE_MINUTES > 30:
                raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must not exceed 30 in production")
            if "*" in self.cors_origins or not self.cors_origins:
                raise ValueError(
                    "ALLOW_ORIGINS must be an explicit allow-list in production"
                )
            if any(not o.startswith("https://") for o in self.cors_origins):
                raise ValueError("ALLOW_ORIGINS must only list https:// origins in production")
            if self.ALLOW_CREDENTIALS and (
                self.ALLOW_HEADERS.strip() == "*"
            ):
                raise ValueError("Wildcard headers cannot be used with credentialed CORS")
            if not self.SKIP_DB_INIT:
                raise ValueError(
                    "SKIP_DB_INIT must remain true in production; use Alembic"
                )
            if self.ALLOW_CREDENTIALS and self.ALLOW_METHODS.strip() == "*":
                raise ValueError(
                    "Wildcard methods cannot be used with credentialed CORS"
                )
            if self.ALLOW_LEGACY_PAYMENT_SIMULATION:
                raise ValueError("Legacy payment simulation is forbidden in production")
            if self.DEV_EXPOSE_AUTH_TOKENS:
                raise ValueError(
                    "DEV_EXPOSE_AUTH_TOKENS must be false in production: "
                    "verification and reset tokens must never appear in HTTP responses"
                )
            if not self.EASYTRANSACT_API_BASE_URL or not self.EASYTRANSACT_API_TOKEN:
                raise ValueError("Easy Transact credentials are required in production")
            if not self.EASYTRANSACT_WEBHOOK_SECRET:
                raise ValueError(
                    "Easy Transact webhook secret is required in production"
                )
        return self

    @property
    def cors_origins(self) -> List[str]:
        return [
            origin.strip() for origin in self.ALLOW_ORIGINS.split(",") if origin.strip()
        ]

    @property
    def cors_methods(self) -> List[str]:
        return [
            method.strip().upper()
            for method in self.ALLOW_METHODS.split(",")
            if method.strip()
        ]

    @property
    def cors_headers(self) -> List[str]:
        return [
            header.strip() for header in self.ALLOW_HEADERS.split(",") if header.strip()
        ]


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


settings = get_settings()
