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

    # Must point at a dedicated, disposable database — never the same as
    # database_url. The test suite runs create_all/drop_all around every
    # test; pointed at the real database this destroys production/dev data.
    test_database_url: str = ""

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

    dashboard_base_url: str = "https://nightfury-beta.vercel.app"

    # Public URL of the customer-facing frontend, used to build the QR
    # claim_url returned to a device during provisioning
    # (https://app.../connect?claim=<opaque>). Defaults to the local dev
    # frontend port.
    app_public_url: str = "http://localhost:3000"

    # Public GitHub Release (or CDN) prefix containing the cross-compiled
    # agent files. Account-bound installer scripts fetch the platform binary
    # from here and never contain a permanent device credential.
    agent_release_base_url: str = (
        "https://github.com/knight099/nightfury/releases/latest/download"
    )

    relay_public_url: str = "grpcs://relay.nightwatch.local:443"
    relay_webrtc_url: str = "http://relay:9080"  # internal URL for backend→relay WebRTC proxy

    # Live MJPEG stream (worker-hosted). Public base URL of the worker's
    # stream server, and a shared HMAC secret used to sign short-lived
    # per-camera stream tokens (verified by the worker without a callback).
    worker_stream_url: str = "http://localhost:8090"
    stream_token_secret: str = "change-me-stream-secret"
    stream_token_ttl_seconds: int = 900

    # TURN fallback relay (coturn) for WebRTC live view when a direct P2P
    # connection fails. turn_shared_secret must match coturn's
    # static-auth-secret (see deploy/coturn/turnserver.conf). Empty
    # turn_url disables minting — browsers fall back to STUN-only.
    turn_url: str = ""
    turn_shared_secret: str = ""
    turn_credential_ttl_seconds: int = 600

    super_admin_username: str = "super_nightvision"
    # The super admin belongs to a real organisation of its own, so that
    # "my org" surfaces (settings, sites, cameras, digests) work for them and
    # they have somewhere to put their own test hardware. Cross-org visibility
    # is unaffected: every bypass keys off role == "super_admin", never off
    # org_id being null.
    super_admin_org_name: str = "Nightwatch HQ"
    super_admin_password: str = ""

    access_token_expire_minutes: int = 1440  # 24 hours
    refresh_token_expire_days: int = 7

    # Digest subsystem
    gemini_api_key: str = ""
    # Vertex AI project/location used by the edge-box token broker
    # (/api/edge/gemini-token) — mirrors worker/config.py's fields of the
    # same name so edge boxes target the same Vertex AI project as the
    # cloud worker.
    gemini_vertex_project: str = "gebra-ai"
    gemini_vertex_location: str = "us-central1"
    ollama_api_key: str = ""
    ollama_base_url: str = "https://ollama.com"
    # qwen3.5 is vision-capable but requires a paid Ollama Cloud plan; gemma4
    # is tagged vision-capable but 500s on every image request as of this
    # writing (verified against the real API, not a local bug). minimax-m3
    # is the confirmed-working, account-accessible vision model.
    ollama_test_camera_model: str = "minimax-m3"
    digest_daily_spend_cap_usd: float = 1.0
    # Per-site daily AI spend cap. 0 disables it (org cap only), which is the
    # single-site default. On an estate this is what stops one busy floor
    # exhausting the whole org's budget and degrading every other floor.
    digest_site_daily_spend_cap_usd: float = 0.0
    digest_on_demand_per_user_hourly_limit: int = 10
    digest_max_events_per_window: int = 200
    digest_max_range_days: int = 7

    # Rate limiting
    rate_limit_enabled: bool = True

    # Local ONNX detection for the Test AI page — runs before deciding
    # whether to escalate to Gemini. Same models/approach as worker/, kept
    # as a separate copy since backend and worker are separate deployable
    # services with no shared package today.
    local_detection_enabled: bool = True
    yolo_model_path: str = "models/yolov8n.onnx"
    pose_model_path: str = "models/yolov8n-pose.onnx"
    yolo_input_size: int = 640
    pose_input_size: int = 640
    pose_keypoint_confidence: float = 0.3
    local_detection_fastpath_confidence: float = 0.80

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
