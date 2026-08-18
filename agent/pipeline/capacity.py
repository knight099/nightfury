"""How many cameras this box can actually run.

``max_cameras`` used to be a hardcoded 12 applied as ``cameras[:12]``. That is
a guess baked into a constant, and it was applied by silently dropping the
excess — the worst possible failure mode, because a dropped camera looks
exactly like a camera nobody configured.

Capacity really depends on stream resolution, frame rates, how many cameras
have a ``step_sequence`` (pose detection is far more expensive than the YOLO
gate), and what hardware the box happens to be. So it is measured, not
declared once:

* **Declared** — a starting estimate from CPU cores and available RAM,
  reported at startup so the backend can place cameras before any measurement
  exists.
* **Measured** — revised from observed per-camera analysis cost, with damping
  and hysteresis so a busy afternoon does not cause placement thrash.

``config.max_cameras`` remains as an operator-settable *ceiling*, never the
primary number.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Rough cost model for the declared estimate. A camera's pipeline is mostly
# FFmpeg decode plus periodic ONNX inference; both are CPU-bound, and in
# practice a core sustains a few cameras at the default 1fps idle sampling.
CAMERAS_PER_CORE = 3
# Decode buffers plus the ring buffer dominate per-camera memory.
MB_PER_CAMERA = 350
# Leave room for the OS and the Go supervisor alongside us.
RESERVED_MB = 1024

# Never report less than this, even on a very small box — one camera is the
# minimum useful deployment, and reporting 0 would make the box unusable
# rather than merely slow.
MIN_CAPACITY = 1

# Measured capacity only moves after this many consecutive observations agree,
# so one slow minute cannot shed cameras.
HYSTERESIS_SAMPLES = 5
# Fraction of a camera's sampling interval that analysis may consume before
# the box is considered saturated. Above this, work is queueing.
SATURATION_RATIO = 0.75


def _cpu_count() -> int:
    # sched_getaffinity respects cgroup/container CPU limits, which os.cpu_count
    # does not — important because the agent normally ships as a container.
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError:
        return max(1, os.cpu_count() or 1)


def _available_mb() -> int | None:
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def declared_capacity(ceiling: int) -> int:
    """Starting estimate from hardware, capped by the operator's ceiling."""
    by_cpu = _cpu_count() * CAMERAS_PER_CORE

    available_mb = _available_mb()
    if available_mb is None:
        # Unknown memory (non-Linux dev box) — trust CPU alone rather than
        # inventing a number.
        by_mem = by_cpu
    else:
        by_mem = max(MIN_CAPACITY, (available_mb - RESERVED_MB) // MB_PER_CAMERA)

    capacity = max(MIN_CAPACITY, min(by_cpu, by_mem, ceiling))
    logger.info(
        "declared capacity=%d (cpu=%d cores -> %d, mem=%s MB -> %d, ceiling=%d)",
        capacity,
        _cpu_count(),
        by_cpu,
        available_mb,
        by_mem,
        ceiling,
    )
    return capacity


class CapacityTracker:
    """Tracks observed load and revises capacity with hysteresis."""

    def __init__(self, ceiling: int):
        self.ceiling = ceiling
        self.capacity = declared_capacity(ceiling)
        self.source = "declared"
        self._over_streak = 0
        self._under_streak = 0

    def observe(self, active_cameras: int, mean_utilisation: float) -> None:
        """Record one health-check round.

        ``mean_utilisation`` is the mean fraction of each camera's sampling
        interval spent actually analysing frames — 1.0 means analysis is taking
        as long as the interval between frames, i.e. the box is exactly
        saturated and any more load queues up.
        """
        if active_cameras <= 0:
            return

        if mean_utilisation > SATURATION_RATIO:
            self._over_streak += 1
            self._under_streak = 0
        elif mean_utilisation < SATURATION_RATIO / 2 and active_cameras >= self.capacity:
            # Only grow when actually running at capacity — plenty of headroom
            # while running 2 of 12 cameras says nothing about whether 20 fit.
            self._under_streak += 1
            self._over_streak = 0
        else:
            self._over_streak = 0
            self._under_streak = 0

        if self._over_streak >= HYSTERESIS_SAMPLES:
            # Shed toward what is actually sustainable at the observed cost.
            new_capacity = max(MIN_CAPACITY, int(active_cameras * SATURATION_RATIO / max(mean_utilisation, 0.01)))
            new_capacity = min(new_capacity, self.capacity - 1, self.ceiling)
            self._set(max(MIN_CAPACITY, new_capacity))
            self._over_streak = 0
        elif self._under_streak >= HYSTERESIS_SAMPLES:
            self._set(min(self.ceiling, self.capacity + 1))
            self._under_streak = 0

    def _set(self, capacity: int) -> None:
        if capacity == self.capacity:
            return
        logger.info("capacity revised %d -> %d (measured)", self.capacity, capacity)
        self.capacity = capacity
        self.source = "measured"

    def load_state(self, active_cameras: int, rejected: int) -> tuple[str, str | None]:
        """Classify current load for the heartbeat.

        Returns ``(state, reason)``. The reason is shown verbatim in the fleet
        view, so it is written for an operator, not a log reader.
        """
        if rejected:
            return (
                "over_capacity",
                f"{rejected} camera(s) could not be started — capacity is {self.capacity}",
            )
        if active_cameras > self.capacity:
            return (
                "degraded",
                f"running {active_cameras} cameras above capacity {self.capacity}; "
                "sampling rates reduced across all cameras",
            )
        return "ok", None
