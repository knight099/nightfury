from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "nightwatch-api"
    debug: bool = False
    secret_key: str = "change-me"

    database_url: str = "postgresql+asyncpg://nightwatch:nightwatch@localhost:5432/nightwatch"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    redis_url: str = "redis://localhost:6379/0"

    gcs_bucket: str = "nightwatch-events"
    gcs_project: str = "nightwatch-dev"
    gcs_signed_url_expiry: int = 3600

    firebase_project_id: str = ""

    gupshup_api_key: str = ""
    gupshup_app_name: str = ""
    whatsapp_business_number: str = ""
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "alerts@nightwatch.ai"

    worker_api_key: str = "change-me-worker-secret"

    relay_public_url: str = "grpcs://relay.nightwatch.local:443"

    super_admin_username: str = "super_nightvision"
    super_admin_password: str = ""

    access_token_expire_minutes: int = 1440  # 24 hours
    refresh_token_expire_days: int = 7

    # Digest subsystem
    gemini_api_key: str = ""
    digest_daily_spend_cap_usd: float = 1.0
    digest_on_demand_per_user_hourly_limit: int = 10
    digest_max_events_per_window: int = 200
    digest_max_range_days: int = 7

    # Rate limiting
    rate_limit_enabled: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
