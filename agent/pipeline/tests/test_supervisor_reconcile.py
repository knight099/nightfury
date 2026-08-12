import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import CameraConfig
from supervisor import compute_diff, WorkerSupervisor


def _run(coro):
    return asyncio.run(coro)


def _cfg(camera_id: str, **overrides) -> CameraConfig:
    base = dict(
        camera_id=camera_id,
        org_id="org-1",
        name=f"cam-{camera_id}",
        ingest_mode="rtsp_pull",
        rtsp_url=f"rtsp://example/{camera_id}",
        stream_key=None,
        sensitivity="medium",
        idle_fps=1.0,
        active_fps=5.0,
    )
    base.update(overrides)
    return CameraConfig(**base)


def _sig(c: CameraConfig) -> tuple:
    return (c.ingest_mode, c.rtsp_url, c.stream_key, c.idle_fps, c.active_fps)


# ---------------------- pure helper tests ----------------------

def test_compute_diff_new_camera_added():
    current = {}
    desired = {"a": _cfg("a")}
    to_start, to_stop, to_restart, to_update = compute_diff(current, desired)
    assert to_start == ["a"]
    assert to_stop == []
    assert to_restart == []
    assert to_update == []


def test_compute_diff_camera_removed():
    desired = {}
    a = _cfg("a")
    current = {"a": _sig(a)}
    to_start, to_stop, to_restart, to_update = compute_diff(current, desired)
    assert to_start == []
    assert to_stop == ["a"]
    assert to_restart == []
    assert to_update == []


def test_compute_diff_sensitivity_change_only_is_update():
    a = _cfg("a", sensitivity="low")
    a2 = _cfg("a", sensitivity="high")
    current = {"a": _sig(a)}
    desired = {"a": a2}
    to_start, to_stop, to_restart, to_update = compute_diff(current, desired)
    assert to_update == ["a"]
    assert to_restart == []
    assert to_start == []
    assert to_stop == []


def test_compute_diff_rtsp_change_is_restart():
    a = _cfg("a", rtsp_url="rtsp://old")
    a2 = _cfg("a", rtsp_url="rtsp://new")
    current = {"a": _sig(a)}
    desired = {"a": a2}
    to_start, to_stop, to_restart, to_update = compute_diff(current, desired)
    assert to_restart == ["a"]
    assert to_update == []


def test_compute_diff_fps_change_is_restart():
    a = _cfg("a", idle_fps=1.0)
    a2 = _cfg("a", idle_fps=2.0)
    current = {"a": _sig(a)}
    desired = {"a": a2}
    _, _, to_restart, to_update = compute_diff(current, desired)
    assert to_restart == ["a"]
    assert to_update == []


def test_compute_diff_mixed():
    a = _cfg("a")
    b = _cfg("b", rtsp_url="rtsp://old-b")
    c = _cfg("c")
    current = {"a": _sig(a), "b": _sig(b), "c": _sig(c)}
    desired = {
        "a": _cfg("a", sensitivity="high"),       # update
        "b": _cfg("b", rtsp_url="rtsp://new-b"),  # restart
        "d": _cfg("d"),                            # start
        # "c" removed -> stop
    }
    to_start, to_stop, to_restart, to_update = compute_diff(current, desired)
    assert to_start == ["d"]
    assert to_stop == ["c"]
    assert to_restart == ["b"]
    assert to_update == ["a"]


# ---------------------- supervisor reconcile (with fakes) ----------------------

class FakeApiClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.closed = False

    async def get_assignments(self):
        if not self.responses:
            return None
        return self.responses.pop(0)

    async def close(self):
        self.closed = True


class FakeWorker:
    def __init__(self, cfg):
        self.camera_config = cfg
        self.started = False
        self.stopped = False
        self.update_calls = []

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def stream_config_signature(self):
        return _sig(self.camera_config)

    def update_config(self, new_cfg):
        self.update_calls.append(new_cfg)
        self.camera_config = new_cfg

    @property
    def is_alive(self):
        return self.started and not self.stopped


def _make_supervisor(api_responses):
    sup = WorkerSupervisor.__new__(WorkerSupervisor)
    sup.workers = {}
    sup.gemini = None
    sup.api_client = FakeApiClient(api_responses)

    async def fake_start_worker(cam_config):
        if cam_config.camera_id in sup.workers:
            return
        w = FakeWorker(cam_config)
        await w.start()
        sup.workers[cam_config.camera_id] = w

    async def fake_stop_worker(camera_id):
        w = sup.workers.pop(camera_id, None)
        if w:
            await w.stop()

    sup._start_worker = fake_start_worker
    sup._stop_worker = fake_stop_worker
    return sup


def test_reconcile_adds_new_camera():
    sup = _make_supervisor([
        [{"camera_id": "a", "org_id": "o", "name": "A", "ingest_mode": "rtsp_pull",
          "rtsp_url": "rtsp://a"}],
    ])

    async def scenario():
        await sup._reconcile_once()
        assert "a" in sup.workers
        assert sup.workers["a"].started

    _run(scenario())


def test_reconcile_removes_missing_camera():
    sup = _make_supervisor([[]])
    sup.workers["a"] = FakeWorker(_cfg("a"))
    sup.workers["a"].started = True

    async def scenario():
        await sup._reconcile_once()
        assert "a" not in sup.workers

    _run(scenario())


def test_reconcile_sensitivity_change_calls_update_only():
    existing = FakeWorker(_cfg("a", sensitivity="low"))
    existing.started = True
    sup = _make_supervisor([
        [{"camera_id": "a", "org_id": "o", "name": "A", "ingest_mode": "rtsp_pull",
          "rtsp_url": "rtsp://example/a", "sensitivity": "high"}],
    ])
    sup.workers["a"] = existing

    async def scenario():
        await sup._reconcile_once()
        assert sup.workers["a"] is existing
        assert not existing.stopped
        assert len(existing.update_calls) == 1
        assert existing.update_calls[0].sensitivity == "high"

    _run(scenario())


def test_reconcile_rtsp_change_restarts_worker():
    existing = FakeWorker(_cfg("a", rtsp_url="rtsp://old"))
    existing.started = True
    sup = _make_supervisor([
        [{"camera_id": "a", "org_id": "o", "name": "A", "ingest_mode": "rtsp_pull",
          "rtsp_url": "rtsp://new"}],
    ])
    sup.workers["a"] = existing

    async def scenario():
        await sup._reconcile_once()
        assert existing.stopped
        assert "a" in sup.workers
        assert sup.workers["a"] is not existing
        assert sup.workers["a"].camera_config.rtsp_url == "rtsp://new"

    _run(scenario())


def test_reconcile_none_response_keeps_workers():
    existing = FakeWorker(_cfg("a"))
    existing.started = True
    sup = _make_supervisor([None])
    sup.workers["a"] = existing

    async def scenario():
        await sup._reconcile_once()
        assert "a" in sup.workers
        assert not existing.stopped
        assert sup.workers["a"] is existing

    _run(scenario())


def test_reconcile_empty_list_stops_all():
    a = FakeWorker(_cfg("a"))
    a.started = True
    b = FakeWorker(_cfg("b"))
    b.started = True
    sup = _make_supervisor([[]])
    sup.workers["a"] = a
    sup.workers["b"] = b

    async def scenario():
        await sup._reconcile_once()
        assert sup.workers == {}
        assert a.stopped and b.stopped

    _run(scenario())


def test_from_assignment_defaults_optional_fields():
    cfg = CameraConfig.from_assignment({
        "camera_id": "cam-1",
        "org_id": "org-1",
        "name": "Front",
        "ingest_mode": "rtsp_pull",
        "rtsp_url": "rtsp://x",
    })
    assert cfg.site_id == ""
    assert cfg.site_name == ""
    assert cfg.sensitivity == "medium"
    assert cfg.enabled_events == ["person", "vehicle", "intrusion"]
