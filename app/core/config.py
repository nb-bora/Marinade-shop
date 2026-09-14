from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    # Database
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "marinade"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"

    @property
    def DATABASE_URL(self) -> str:
        """Build database URL from individual components"""
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    # Security
    SECRET_KEY: str = "your-secret-key-here-change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Application
    APP_NAME: str = "Marinade API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"

    # Database Initialization
    SKIP_DB_INIT: bool = False

    # CORS
    ALLOW_ORIGINS: str = "*"
    ALLOW_CREDENTIALS: bool = True
    ALLOW_METHODS: str = "*"
    ALLOW_HEADERS: str = "*"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    @property
    def cors_origins(self) -> List[str]:
        """Parse CORS origins from string"""
        if self.ALLOW_ORIGINS == "*":
            return ["*"]
        try:
            return [origin.strip() for origin in self.ALLOW_ORIGINS.split(",")]
        except Exception:
            return ["*"]

    @property
    def cors_methods(self) -> List[str]:
        """Parse CORS methods from string"""
        if self.ALLOW_METHODS == "*":
            return ["*"]
        try:
            return [method.strip() for method in self.ALLOW_METHODS.split(",")]
        except Exception:
            return ["*"]

    @property
    def cors_headers(self) -> List[str]:
        """Parse CORS headers from string"""
        if self.ALLOW_HEADERS == "*":
            return ["*"]
        try:
            return [header.strip() for header in self.ALLOW_HEADERS.split(",")]
        except Exception:
            return ["*"]


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get settings instance (singleton pattern)"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# For backward compatibility
settings = get_settings()
