from typing import List, Optional
from urllib.parse import quote_plus

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    RESET_TOKEN_EXPIRE_MINUTES: int = 15
    VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24

    EMAIL_FROM: str = "noreply@marinade.local"
    TWO_FACTOR_ISSUER: str = "Marinade"

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

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in {"production", "prod", "staging"}

    @property
    def DATABASE_URL(self) -> str:
        user = quote_plus(self.DB_USER)
        password = quote_plus(self.DB_PASSWORD)
        return f"postgresql://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?sslmode={quote_plus(self.DB_SSLMODE)}"

    @model_validator(mode="after")
    def validate_security_configuration(self):
        if self.is_production:
            if (
                self.SECRET_KEY == "your-secret-key-here-change-this-in-production"
                or len(self.SECRET_KEY) < 32
            ):
                raise ValueError(
                    "SECRET_KEY must be a private random value of at least 32 characters in production"
                )
            if self.DEBUG:
                raise ValueError("DEBUG must be false in production")
            if self.ALLOW_ORIGINS.strip() == "*" or not self.ALLOW_ORIGINS.strip():
                raise ValueError(
                    "ALLOW_ORIGINS must be an explicit allow-list in production"
                )
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
