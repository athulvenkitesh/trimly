from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    public_base_url: str = "http://localhost:8000"

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
