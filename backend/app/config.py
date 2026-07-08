import os
from pydantic_settings import BaseSettings


def _default_db_url() -> str:
    from urllib.parse import urlparse, urlunparse
    pg_url = os.environ.get("POSTGRES_URL", "")
    if pg_url:
        # Strip query params (pgbouncer=true, sslmode=require, etc.)
        # asyncpg handles SSL via connect_args, not URL params
        parsed = urlparse(pg_url)
        clean = urlunparse(parsed._replace(query=""))
        clean = clean.replace("postgres://", "postgresql+asyncpg://", 1)
        clean = clean.replace("postgresql://", "postgresql+asyncpg://", 1)
        return clean
    return "postgresql+asyncpg://nightwatch:nightwatch@localhost:5432/nightwatch"


class Settings(BaseSettings):
    app_name: str = "nightwatch-api"
    debug: bool = False
    secret_key: str = "change-me"

    database_url: str = _default_db_url()
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
    relay_webrtc_url: str = "http://relay:9080"  # internal URL for backend→relay WebRTC proxy

    # Live MJPEG stream (worker-hosted). Public base URL of the worker's
    # stream server, and a shared HMAC secret used to sign short-lived
    # per-camera stream tokens (verified by the worker without a callback).
    worker_stream_url: str = "http://localhost:8090"
    stream_token_secret: str = "change-me-stream-secret"
    stream_token_ttl_seconds: int = 900

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
