from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Backend API
    backend_url: str = "https://nightfury-backend.vercel.app"
    worker_api_key: str = "change-me-worker-secret"
    device_token: str = Field(default="", validation_alias="NIGHTWATCH_DEVICE_TOKEN")

    # GCS
    gcs_bucket: str = "nightwatch-events"
    gcs_project: str = "nightwatch-dev"

    # Gemini
    gemini_model: str = "gemini-2.5-flash"
    gemini_max_concurrent: int = 5
    gemini_timeout_seconds: int = 10
    gemini_vertex_project: str = "gebra-ai"
    gemini_vertex_location: str = "us-central1"
    gemini_api_key: str = ""

    # Stream
    ffmpeg_path: str = "ffmpeg"
    frame_width: int = 1280
    frame_height: int = 720
    max_decode_fps: int = 10
    ring_buffer_seconds: int = 30

    # Motion detection
    motion_threshold: float = 0.01
    motion_pixel_threshold: int = 25

    # Sampling
    idle_fps: float = 1.0
    active_fps: float = 5.0
    no_motion_timeout: float = 10.0

    # YOLO local detection (gates + short-circuits Gemini calls)
    yolo_enabled: bool = True
    yolo_model_path: str = "models/yolov8n.onnx"
    yolo_input_size: int = 640
    yolo_fastpath_confidence: float = 0.75
    yolo_escalate_floor: float = 0.35

    # Pose detection + step-sequence tracking
    pose_enabled: bool = True
    pose_model_path: str = "models/yolov8n-pose.onnx"
    pose_input_size: int = 640
    pose_keypoint_confidence: float = 0.3
    track_iou_threshold: float = 0.3
    track_ttl_seconds: float = 5.0

    # Worker
    worker_id: str = "worker-local"
    max_cameras: int = 12
    health_report_interval: int = 30
    assignment_poll_interval: int = 10

    # Latest-frame uploader (for live-ish snapshot polling from frontend)
    latest_frame_interval_seconds: float = 2.0
    latest_frame_quality: int = 70

    # Live MJPEG stream server (multipart/x-mixed-replace)
    mjpeg_server_enabled: bool = True
    mjpeg_server_host: str = "0.0.0.0"
    mjpeg_server_port: int = 8090
    mjpeg_fps: float = 10.0
    mjpeg_quality: int = 80

    # Shared HMAC secret used to verify stream tokens issued by the backend's
    # /api/cameras/{id}/stream-url endpoint. Must match backend's
    # STREAM_TOKEN_SECRET. Empty string disables auth (local dev only).
    stream_token_secret: str = ""

    # Offline queue (events buffered when backend unreachable)
    offline_queue_path: str = "/tmp/nightwatch_worker_queue.sqlite3"
    offline_queue_max_rows: int = 10000



config = Config()
