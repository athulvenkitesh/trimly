import os
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def sqlalchemy_url(value: str) -> str:
    """Point a plain Postgres URL at the installed psycopg 3 driver.

    Managed hosts (Render, Heroku, Fly) hand out ``postgresql://`` or
    ``postgres://``; SQLAlchemy would then try psycopg2, which is not installed.
    """
    for scheme in ("postgres://", "postgresql://"):
        if value.startswith(scheme):
            return "postgresql+psycopg://" + value[len(scheme):]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "Booking API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://booking:booking@localhost:5432/booking"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret_key: str = "development-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 14
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    payment_provider: str = ""
    payment_api_key: str = ""
    payment_webhook_secret: str = ""
    # Direct UPI-intent payments (no gateway fees): your merchant VPA, e.g. shop@upi.
    upi_vpa: str = ""
    upi_payee_name: str = "Trimly"
    # Convenience fee added to every WhatsApp payment; owners may override per shop.
    default_convenience_fee_paise: int = 2000
    # Absolute URLs the app hands out (payment callbacks, WhatsApp links).
    # Left empty, it falls back to the host's own URL — see below.
    public_base_url: str = ""
    # Shop logos: "local" writes to ./uploads, "s3" uploads to an S3-compatible
    # bucket (Cloudflare R2). A container host must use "s3" — its disk is
    # replaced on every deploy.
    storage_backend: str = "local"
    s3_endpoint_url: str = ""
    s3_region: str = "auto"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    # Public URL the bucket is served from, e.g. https://cdn.example.com
    s3_public_base_url: str = ""

    @field_validator("database_url")
    @classmethod
    def normalise_database_url(cls, value: str) -> str:
        return sqlalchemy_url(value)

    @model_validator(mode="after")
    def resolve_public_base_url(self):
        """Work out this deployment's own URL instead of asking the operator to.

        Render injects RENDER_EXTERNAL_URL (https://trimly-xxxx.onrender.com) for
        every web service, so a first deploy works with no public URL set. A
        custom domain still needs PUBLIC_BASE_URL set explicitly.
        """
        if not self.public_base_url:
            self.public_base_url = os.environ.get("RENDER_EXTERNAL_URL") or "http://localhost:8000"
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
