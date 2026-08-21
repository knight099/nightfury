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


class CameraHeartbeat(BaseModel):
    """Per-camera health inside a batched agent heartbeat."""

    camera_id: str
    status: str = "online"
    # Line-crossing counts accumulated since the previous heartbeat:
    # {line_name: {"in": n, "out": n}}. Drained agent-side, so each bucket is
    # reported exactly once — a dropped heartbeat loses that interval rather
    # than double-counting the next.
    footfall: dict[str, dict[str, int]] | None = None
    # Cumulative frames decoded for this camera since the pipeline started.
    # Onboarding's "stream verified" step needs to know a frame was actually
    # decoded, not just that a stream object exists — see
    # agent/pipeline/camera_worker.py::heartbeat_payload.
    frames_processed: int = 0

    model_config = ConfigDict(extra="allow")  # free-form per-camera metrics


class HeartbeatRequest(BaseModel):
    """One heartbeat post.

    Two shapes are accepted on the same endpoint:

    * **Batched (current)** — one post per agent carrying every camera in
      ``cameras``, plus the agent's self-reported capacity and load state.
    * **Single-camera (legacy)** — ``camera_id``/``status`` at the top level.

    The legacy shape is still accepted because agents update independently of
    the backend: a box running the old pipeline must keep reporting health
    across a backend deploy rather than going dark until someone updates it.

    The batched shape exists because the per-camera shape does not scale. The
    old pipeline posted one HTTP request and one row update per camera every
    ``health_report_interval``; at 400 cameras that is ~13 requests/sec and
    ~13 writes/sec, permanently, purely for health reporting.
    """

    worker_id: str | None = None

    # Batched shape
    cameras: list[CameraHeartbeat] | None = None
    # Agent's own view of how many cameras it can run, and where it stands
    # against that. See agent/pipeline/capacity.py.
    capacity_cameras: int | None = None
    capacity_source: str | None = None  # "declared" | "measured"
    load_state: str | None = None  # "ok" | "degraded" | "over_capacity"
    load_reason: str | None = None
    # Cameras the agent was assigned but could not start. These become
    # `unassigned` so the fleet view can surface them and the reconciler can
    # place them elsewhere — never silently dropped.
    rejected_cameras: list[str] | None = None

    # Legacy single-camera shape
    camera_id: str | None = None
    status: str | None = None

    pipeline: PipelineHealth | None = None

    model_config = ConfigDict(extra="allow")  # preserve today's free-form **metrics passthrough
