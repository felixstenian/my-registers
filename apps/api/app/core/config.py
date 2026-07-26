from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "production", "test"] = "development"
    app_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"

    database_url: str = Field(
        default="postgresql+asyncpg://registers_app:dev_password@postgres:5432/registers"
    )

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_fallback_model: str = "claude-haiku-4-5-20251001"
    anthropic_max_tokens: int = 1024
    anthropic_temperature: float = 0.1

    jwt_secret: str = "dev-only-secret-do-not-use-in-prod"
    jwt_access_ttl_seconds: int = 900
    refresh_ttl_seconds: int = 1_209_600
    cookie_domain: str = "localhost"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    default_admin_email: str = "admin@example.com"
    default_admin_password: str = ""

    s3_endpoint: str = "http://minio:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "registers-media"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_force_path_style: bool = True
    s3_public_base_url: str = ""

    tz: str = "America/Sao_Paulo"
    allowed_origins: str = "http://localhost:3000"
    rate_limit_login_per_min: int = 5

    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
