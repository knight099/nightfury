import asyncio
import json
import logging
import os

from config import config
from models import CameraConfig
from camera_worker import CameraWorker
from capacity import CapacityTracker
from gemini_client import GeminiClient
from api_client import ApiClient
from mjpeg_server import MJPEGServer

logger = logging.getLogger(__name__)

# Sampling multiplier applied to every camera when the box is running above
# its capacity. Uniform degradation across all cameras is almost always better
# than perfect analysis on some and none on others — but it must be visible,
# which is why it is reported as `load_state: degraded` with a reason rather
# than applied silently.
DEGRADED_LOAD_FACTOR = 0.5

# Setup analysis is not urgent; detection is. Bounding concurrency keeps an
# onboarding run from competing with the pipeline this box exists to run.
MAX_CONCURRENT_SETUP_JOBS = 2
SETUP_POLL_INTERVAL = 30


def _stream_signature(c: CameraConfig) -> tuple:
    return (c.ingest_mode, c.rtsp_url, c.stream_key, c.idle_fps, c.active_fps)


def compute_diff(
    current_signatures: dict[str, tuple],
    desired: dict[str, CameraConfig],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Pure helper: compute reconcile diff.

    Args:
        current_signatures: camera_id -> stream signature tuple of running workers
        desired: camera_id -> desired CameraConfig

    Returns:
        (to_start, to_stop, to_restart, to_update) lists of camera_ids.
    """
    current_ids = set(current_signatures.keys())
    desired_ids = set(desired.keys())

    to_start = sorted(desired_ids - current_ids)
    to_stop = sorted(current_ids - desired_ids)

    to_restart: list[str] = []
    to_update: list[str] = []
    for cid in sorted(current_ids & desired_ids):
        if current_signatures[cid] != _stream_signature(desired[cid]):
            to_restart.append(cid)
        else:
            to_update.append(cid)
    return to_start, to_stop, to_restart, to_update


class WorkerSupervisor:
    """
    Manages multiple CameraWorker instances on a single machine.
    Polls the backend for camera assignments and reconciles running workers.
    Falls back to cameras.json on cold start if the backend is unreachable.
    """

    def __init__(self):
        self.workers: dict[str, CameraWorker] = {}  # camera_id → worker
        self.api_client = ApiClient()  # used by supervisor for assignments; also brokers Gemini tokens
        self.gemini = GeminiClient(self.api_client)  # shared across all workers
        self.mjpeg_server = MJPEGServer(lambda cid: self.workers.get(cid))
        # config.max_cameras is now a ceiling an operator can set, not the
        # capacity itself — the box measures what it can actually run.
        self.capacity = CapacityTracker(config.max_cameras)
        # Cameras the backend assigned that this box could not start. Reported
        # every heartbeat so the backend can mark them unassigned and place
        # them elsewhere. Never silently dropped.
        self.rejected: set[str] = set()

    async def run(self):
        """Main supervisor loop."""
        logger.info(
            f"Supervisor starting (worker_id={config.worker_id}, "
            f"capacity={self.capacity.capacity}, ceiling={config.max_cameras})"
        )

        # Cold start: try backend assignments, fall back to cameras.json
        cameras = await self._cold_start_configs()
        if not cameras:
            logger.warning("No cameras configured at cold start. Will retry via reconcile loop.")

        for cam_config in cameras:
            await self._start_worker(cam_config)

        await self.mjpeg_server.start()

        reconcile_task = asyncio.create_task(self._reconcile_loop())
        setup_task = asyncio.create_task(self._setup_loop())
        try:
            while True:
                await asyncio.sleep(config.health_report_interval)
                await self._health_check()
        except asyncio.CancelledError:
            logger.info("Supervisor shutting down...")
            reconcile_task.cancel()
            try:
                await reconcile_task
            except (asyncio.CancelledError, Exception):
                pass
            setup_task.cancel()
            try:
                await setup_task
            except (asyncio.CancelledError, Exception):
                pass
            await self.mjpeg_server.stop()
            await self._stop_all()
            try:
                await self.api_client.close()
            except Exception as e:
                logger.debug(f"api_client close error: {e}")

    async def _cold_start_configs(self) -> list[CameraConfig]:
        """Try backend first, fall back to cameras.json on failure."""
        assignments = await self.api_client.get_assignments()
        if assignments is None:
            logger.info("Backend unreachable at cold start; falling back to cameras.json")
            return self._load_camera_configs()
        if not assignments:
            logger.info("Backend returned no assignments at cold start")
            return []
        return [CameraConfig.from_assignment(a) for a in assignments]

    async def _reconcile_loop(self):
        """Periodically poll assignments and reconcile workers."""
        while True:
            try:
                await asyncio.sleep(config.assignment_poll_interval)
                await self._reconcile_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Reconcile loop error: {e}")

    async def _reconcile_once(self):
        assignments = await self.api_client.get_assignments()
        if assignments is None:
            logger.debug("Reconcile: skipped (backend unreachable)")
            return

        desired: dict[str, CameraConfig] = {}
        for a in assignments:
            try:
                cfg = CameraConfig.from_assignment(a)
            except Exception as e:
                logger.warning(f"Reconcile: malformed assignment skipped: {e}")
                continue
            desired[cfg.camera_id] = cfg

        current_signatures = {
            cid: w.stream_config_signature() for cid, w in self.workers.items()
        }
        to_start, to_stop, to_restart, to_update = compute_diff(current_signatures, desired)

        if not (to_start or to_stop or to_restart or to_update):
            return

        for cid in to_stop:
            await self._stop_worker(cid)

        for cid in to_restart:
            await self._stop_worker(cid)

        for cid in to_update:
            try:
                self.workers[cid].update_config(desired[cid])
            except Exception as e:
                logger.error(f"Reconcile: update_config failed for {cid}: {e}")

        # A camera that reappears in the desired set gets a fresh chance to
        # start — its earlier rejection may have been a capacity condition
        # that has since cleared.
        self.rejected &= set(desired)

        for cid in to_start + to_restart:
            await self._start_worker(desired[cid])

        if to_start or to_stop or to_restart or to_update:
            logger.info(
                f"Reconcile: started={len(to_start)} stopped={len(to_stop)} "
                f"restarted={len(to_restart)} updated={len(to_update)} "
                f"(active={len(self.workers)})"
            )

    async def _setup_loop(self):
        """Poll for camera-setup jobs and answer them."""
        while True:
            try:
                await asyncio.sleep(SETUP_POLL_INTERVAL)
                # The backend pops these jobs off Redis destructively, so a job
                # is consumed the instant it is fetched here — not once it is
                # answered. A job lost to cancellation or a crash mid-analysis
                # is NOT redelivered; its camera_setup_proposals row just stays
                # "pending" until an operator retries the setup run. Do not add
                # retry/re-enqueue logic here that assumes redelivery — it does
                # not exist.
                jobs = await self.api_client.get_setup_jobs()
                if not jobs:
                    continue
                semaphore = asyncio.Semaphore(MAX_CONCURRENT_SETUP_JOBS)

                async def run(job):
                    async with semaphore:
                        await self._run_setup_job(job)

                await asyncio.gather(*(run(j) for j in jobs), return_exceptions=True)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"setup loop error: {e}")

    async def _run_setup_job(self, job: dict):
        """Observe one camera and post a proposal (or the reason there isn't one)."""
        import cv2
        from scene_analyzer import SceneAnalysisError, analyze_scene

        camera_id = job.get("camera_id")
        name = job.get("camera_name", camera_id)
        frame_count = int(job.get("frame_count", 10))
        observe_seconds = int(job.get("observe_seconds", 180))

        worker = self.workers.get(camera_id)
        if worker is None:
            await self.api_client.post_setup_result(
                camera_id, {"error": "this camera is not running on this appliance"}
            )
            return

        interval = max(1.0, observe_seconds / max(1, frame_count))
        frames: list[bytes] = []
        height, width = 720, 1280
        for _ in range(frame_count):
            frame = worker.last_frame
            if frame is not None:
                height, width = frame.shape[0], frame.shape[1]
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    frames.append(buf.tobytes())
            await asyncio.sleep(interval)

        try:
            proposal = await analyze_scene(self.gemini, frames, name, width, height)
        except SceneAnalysisError as exc:
            await self.api_client.post_setup_result(camera_id, {"error": str(exc)})
            return

        await self.api_client.post_setup_result(
            camera_id,
            {"proposal": proposal, "frame_width": width, "frame_height": height},
        )
        logger.info(f"[{name}] setup proposal submitted")

    async def _start_worker(self, cam_config: CameraConfig):
        """Start a camera worker, subject to admission control.

        The backend's placement reconciler already bounds assignments by this
        box's reported capacity, so hitting the limit here means the two views
        have diverged (capacity was just revised downward, or an assignment
        raced a revision). That is a safety valve, not the normal path — and
        unlike the old ``cameras[:max_cameras]`` slice it is *reported*, so a
        camera nobody is analysing shows up in the fleet view instead of
        looking identical to a camera nobody configured.
        """
        if cam_config.camera_id in self.workers:
            logger.warning(f"Worker already running for {cam_config.camera_id}")
            return

        hard_ceiling = max(self.capacity.capacity, config.max_cameras)
        if len(self.workers) >= hard_ceiling:
            self.rejected.add(cam_config.camera_id)
            logger.warning(
                f"Rejecting {cam_config.name} ({cam_config.camera_id}): "
                f"{len(self.workers)} running, ceiling {hard_ceiling}. "
                "Reported to backend for re-placement."
            )
            return

        worker = CameraWorker(cam_config, self.gemini)
        try:
            await worker.start()
            self.workers[cam_config.camera_id] = worker
            self.rejected.discard(cam_config.camera_id)
        except Exception as e:
            logger.error(f"Failed to start worker for {cam_config.name}: {e}")

    def _apply_load_factor(self) -> None:
        """Degrade sampling uniformly when running above capacity.

        Rung 2 of the ladder: rather than dropping a camera outright (rung 3),
        every camera on the box samples less often. Applied to the sampler's
        multiplier, not to idle_fps/active_fps, so the stream signature is
        unchanged and nothing restarts.
        """
        over = len(self.workers) > self.capacity.capacity
        factor = DEGRADED_LOAD_FACTOR if over else 1.0
        for worker in self.workers.values():
            worker.frame_sampler.load_factor = factor

    async def _stop_worker(self, camera_id: str):
        """Stop a specific camera worker."""
        worker = self.workers.pop(camera_id, None)
        if worker:
            await worker.stop()

    async def _stop_all(self):
        """Stop all workers."""
        for camera_id in list(self.workers.keys()):
            await self._stop_worker(camera_id)

    async def _health_check(self):
        """Check worker health, revise capacity, and send ONE batched heartbeat."""
        dead_workers = []
        camera_payloads = []
        utilisations = []

        for camera_id, worker in self.workers.items():
            # Read utilisation for every worker, alive or not — it resets the
            # measurement window, and skipping dead ones would let a stale
            # window inflate the next reading.
            utilisations.append(worker.consume_utilisation())
            if not worker.is_alive:
                dead_workers.append(camera_id)
                logger.warning(f"Worker dead: {camera_id}")
            else:
                camera_payloads.append(worker.heartbeat_payload())

        mean_utilisation = sum(utilisations) / len(utilisations) if utilisations else 0.0
        self.capacity.observe(len(camera_payloads), mean_utilisation)
        self._apply_load_factor()

        # Rejected cameras are reported as their own entries so the backend can
        # mark them unassigned — the fleet view's whole purpose is that these
        # are visible rather than merely absent.
        for camera_id in sorted(self.rejected):
            camera_payloads.append({"camera_id": camera_id, "status": "unassigned"})

        load_state, load_reason = self.capacity.load_state(
            len(self.workers), len(self.rejected)
        )
        await self.api_client.send_agent_heartbeat(
            cameras=camera_payloads,
            capacity_cameras=self.capacity.capacity,
            capacity_source=self.capacity.source,
            load_state=load_state,
            load_reason=load_reason,
            rejected_cameras=sorted(self.rejected),
        )

        # Restart dead workers
        for camera_id in dead_workers:
            worker = self.workers.pop(camera_id)
            cam_config = worker.camera_config
            logger.info(f"Restarting worker for {cam_config.name}")
            await self._start_worker(cam_config)

        active = sum(1 for w in self.workers.values() if w.is_alive)
        logger.info(
            f"Health: {active}/{len(self.workers)} cameras active | "
            f"capacity={self.capacity.capacity} ({self.capacity.source}) "
            f"util={mean_utilisation:.2f} state={load_state} "
            f"rejected={len(self.rejected)} | Gemini stats: {self.gemini.stats}"
        )

    def _load_camera_configs(self) -> list[CameraConfig]:
        """Load camera configs from cameras.json file (cold-start fallback)."""
        config_path = os.environ.get("CAMERAS_CONFIG", "cameras.json")

        if not os.path.exists(config_path):
            logger.warning(f"Camera config not found: {config_path}")
            return []

        with open(config_path) as f:
            data = json.load(f)

        cameras = []
        for cam in data.get("cameras", []):
            cameras.append(CameraConfig(
                camera_id=cam["camera_id"],
                org_id=cam["org_id"],
                site_id=cam.get("site_id", ""),
                name=cam["name"],
                site_name=cam.get("site_name", ""),
                ingest_mode=cam["ingest_mode"],
                rtsp_url=cam.get("rtsp_url"),
                stream_key=cam.get("stream_key"),
                enabled_events=cam.get("enabled_events", ["person", "vehicle", "intrusion"]),
                detection_zones=cam.get("detection_zones", []),
                sensitivity=cam.get("sensitivity", "medium"),
                timezone=cam.get("timezone", "Asia/Kolkata"),
                idle_fps=cam.get("idle_fps", config.idle_fps),
                active_fps=cam.get("active_fps", config.active_fps),
            ))

        logger.info(f"Loaded {len(cameras)} camera configs from {config_path}")
        return cameras
