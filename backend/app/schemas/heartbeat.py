from pydantic import BaseModel, ConfigDict


class PipelineHealth(BaseModel):
    """Detection-pipeline health reported alongside a camera heartbeat.

    KNOWN GAP — this field currently has NO producer.

    Heartbeats are posted by the Python pipeline
    (``agent/pipeline/api_client.py``), but the process-restart state this
    schema describes lives in the Go supervisor
    (``agent/internal/pipeline/supervisor.go``, ``Supervisor.Health()``).
    They are separate OS processes with no channel between them, so the
    Python side cannot see the Go side's restart count/status and nothing
    ever populates this field. The backend accepts and logs it if sent.

    Closing the gap needs one of:
      (a) the Go supervisor posting its own supplementary heartbeat to
          ``/internal/heartbeat`` using the device token it already holds, or
      (b) a local IPC channel — e.g. the supervisor writing its Health as
          JSON to a file under the state dir, which the Python pipeline reads
          and includes in its own heartbeat post.

    Deliberately not implemented in this fix wave; documented so a follow-up
    task has a clear starting point rather than a silently-unfulfilled
    contract.
    """

    status: str  # "running" | "restarting" | "down"
    last_event_at: str | None = None
    gemini_call_failures_last_hour: int = 0


class HeartbeatRequest(BaseModel):
    worker_id: str | None = None
    camera_id: str | None = None
    status: str | None = None
    pipeline: PipelineHealth | None = None

    model_config = ConfigDict(extra="allow")  # preserve today's free-form **metrics passthrough
