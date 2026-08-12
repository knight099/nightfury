from pydantic import BaseModel, ConfigDict


class PipelineHealth(BaseModel):
    status: str  # "running" | "restarting" | "down"
    last_event_at: str | None = None
    gemini_call_failures_last_hour: int = 0


class HeartbeatRequest(BaseModel):
    worker_id: str | None = None
    camera_id: str | None = None
    status: str | None = None
    pipeline: PipelineHealth | None = None

    model_config = ConfigDict(extra="allow")  # preserve today's free-form **metrics passthrough
