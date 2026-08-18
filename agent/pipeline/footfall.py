"""Footfall counting by line crossing.

An operator draws a line across a doorway or corridor on the camera image.
People detected walking across it are counted, with direction — "in" one way,
"out" the other.

WHAT THIS CAN AND CANNOT CLAIM
------------------------------
This is a **traffic estimate, not a turnstile**. It is built on the same
single-camera IoU tracker the rest of the pipeline uses, which has no
re-identification (see ``person_tracker.py``). That produces specific,
predictable error:

* **Occlusion re-counts.** Someone briefly hidden behind a pillar or another
  person loses their track and gets a fresh one. If they cross the line after
  that, they are counted again.
* **Crowds under-count.** Overlapping detections merge or drop under a dense
  group, so busy periods read low — exactly when accuracy matters most to a
  tenant.
* **Sampling gaps.** Detection runs at the sampler's rate, not every frame. A
  fast crossing between two sampled frames is missed entirely, and the
  degradation ladder lowers that rate further under load.

None of this is fixable with a better line algorithm; it is a property of
tracking without re-identification. So the numbers are honest as *relative
trend* ("Level 2 is twice as busy after 6pm", "Tuesday is our quietest day")
and dishonest as *absolute counts* ("4,812 visitors yesterday"). Anything
built on top of this — dashboards, tenant reports — must present it that way,
and the API surfaces it as an estimate for that reason.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# A track must be seen this many times before its crossings count. Filters
# one-frame detection flickers, which would otherwise register as crossings.
MIN_TRACK_HITS = 2

# How long an unseen track is kept before being dropped. Deliberately short:
# holding a stale track risks matching it to a different person who happens to
# walk through the same area, which invents a crossing rather than missing one.
TRACK_TTL_SECONDS = 2.0

# Minimum IoU to consider two boxes the same person between frames.
MATCH_IOU = 0.2

# Fallback association when IoU is zero.
#
# IoU matching silently fails whenever a person moves further than their own
# width between two ANALYSED frames — which is common here, because detection
# runs at the sampler's rate (1fps idle) rather than every frame, and the
# degradation ladder lowers it further under load. A walking person at 1fps
# easily clears their own box width, so the track breaks, a new one starts,
# and the crossing is never counted because the new track has no previous
# side to compare against.
#
# Falling back to centroid proximity — bounded to a multiple of the box width
# so it cannot associate two different people across a room — recovers those
# crossings. It is still not re-identification: it only bridges consecutive
# frames, never an occlusion gap.
MATCH_DISTANCE_WIDTHS = 2.0


@dataclass
class CountingLine:
    """A directed line segment across the frame, in pixel coordinates.

    Direction is defined by the line's own orientation: a crossing from the
    left side of the vector a→b to the right counts as "in", the reverse as
    "out". Which physical direction that means is the operator's business —
    they name it when they draw it.
    """

    name: str
    x1: int
    y1: int
    x2: int
    y2: int

    def side(self, px: float, py: float) -> int:
        """Which side of the line a point is on: +1, -1, or 0 exactly on it."""
        cross = (self.x2 - self.x1) * (py - self.y1) - (self.y2 - self.y1) * (px - self.x1)
        if cross > 0:
            return 1
        if cross < 0:
            return -1
        return 0

    def within_segment(self, px: float, py: float) -> bool:
        """Whether the point's projection falls within the segment's extent.

        Without this, someone walking far past the end of a drawn line still
        counts, because an infinite line divides the whole frame. That is the
        single most common false count in a naive implementation.
        """
        dx, dy = self.x2 - self.x1, self.y2 - self.y1
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return False
        t = ((px - self.x1) * dx + (py - self.y1) * dy) / length_sq
        return 0.0 <= t <= 1.0


@dataclass
class _Track:
    track_id: int
    cx: float
    cy: float
    last_seen: float
    hits: int = 1
    # Last known side per line, so a crossing is a change of sign.
    sides: dict = field(default_factory=dict)


def _iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _proximity(a, b) -> float:
    """1.0 when two boxes are co-located, falling to 0 at the distance limit.

    Compares bottom-centre points (the same reference the crossing test uses)
    and bounds the search by the boxes' own width, so this can never associate
    two people standing apart.
    """
    ax, ay = (a[0] + a[2]) / 2.0, a[3]
    bx, by = (b[0] + b[2]) / 2.0, b[3]
    width = max(1.0, (a[2] - a[0] + b[2] - b[0]) / 2.0)
    limit = width * MATCH_DISTANCE_WIDTHS
    dist = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
    if dist >= limit:
        return 0.0
    return 1.0 - (dist / limit)


class FootfallCounter:
    """Counts directional line crossings for one camera.

    Stateful across frames. Call ``update`` with the person bounding boxes for
    each analysed frame; read and reset totals with ``drain``.
    """

    def __init__(self, lines: list[CountingLine]):
        self.lines = lines
        self._tracks: dict[int, _Track] = {}
        self._boxes: dict[int, tuple] = {}
        self._next_id = 1
        # {line_name: {"in": n, "out": n}}
        self._counts: dict[str, dict[str, int]] = {
            line.name: {"in": 0, "out": 0} for line in lines
        }

    def update(self, person_boxes: list, now: float) -> None:
        """Advance tracking by one frame and record any crossings.

        ``person_boxes`` are objects with x1/y1/x2/y2 attributes.
        """
        if not self.lines:
            return

        # Age out stale tracks before matching, so a long-gone person cannot
        # be revived by an unrelated detection in the same area.
        for tid in [t for t, tr in self._tracks.items() if now - tr.last_seen > TRACK_TTL_SECONDS]:
            self._tracks.pop(tid, None)
            self._boxes.pop(tid, None)

        boxes = [(b.x1, b.y1, b.x2, b.y2) for b in person_boxes]
        unmatched = set(range(len(boxes)))

        # Greedy match against existing tracks, best pair first. IoU is
        # preferred; centroid proximity is the fallback for fast movement
        # between sampled frames (see MATCH_DISTANCE_WIDTHS).
        pairs = []
        for tid, prev in self._boxes.items():
            for i in unmatched:
                score = _iou(prev, boxes[i])
                if score >= MATCH_IOU:
                    pairs.append((score, tid, i))
                    continue
                proximity = _proximity(prev, boxes[i])
                if proximity > 0:
                    # Scaled below any real IoU match so genuine overlaps
                    # always win the greedy assignment.
                    pairs.append((proximity * MATCH_IOU * 0.99, tid, i))
        pairs.sort(key=lambda p: (p[0], -p[1]), reverse=True)

        used_tracks: set[int] = set()
        for _, tid, i in pairs:
            if tid in used_tracks or i not in unmatched:
                continue
            used_tracks.add(tid)
            unmatched.discard(i)
            self._advance(tid, boxes[i], now)

        for i in unmatched:
            self._create(boxes[i], now)

    def _centroid(self, box) -> tuple[float, float]:
        # Bottom-centre, not box centre: it approximates where the person's
        # feet meet the floor, which is what actually crosses a line drawn on
        # the ground. Using the box centre makes tall people cross early.
        return ((box[0] + box[2]) / 2.0, float(box[3]))

    def _create(self, box, now: float) -> None:
        tid = self._next_id
        self._next_id += 1
        cx, cy = self._centroid(box)
        track = _Track(track_id=tid, cx=cx, cy=cy, last_seen=now)
        for line in self.lines:
            track.sides[line.name] = line.side(cx, cy)
        self._tracks[tid] = track
        self._boxes[tid] = box

    def _advance(self, tid: int, box, now: float) -> None:
        track = self._tracks[tid]
        cx, cy = self._centroid(box)
        track.hits += 1
        track.last_seen = now
        self._boxes[tid] = box

        for line in self.lines:
            previous = track.sides.get(line.name, 0)
            current = line.side(cx, cy)
            track.sides[line.name] = current

            if current == 0 or previous == 0 or current == previous:
                continue
            if track.hits < MIN_TRACK_HITS:
                continue
            # Only count if the crossing happened along the drawn segment,
            # not out past its ends where the infinite line still divides the
            # frame.
            if not (line.within_segment(cx, cy) or line.within_segment(track.cx, track.cy)):
                continue

            direction = "in" if previous < 0 and current > 0 else "out"
            self._counts[line.name][direction] += 1

        track.cx, track.cy = cx, cy

    def drain(self) -> dict[str, dict[str, int]]:
        """Return counts since the last drain and reset them."""
        out = {name: dict(v) for name, v in self._counts.items()}
        self._counts = {line.name: {"in": 0, "out": 0} for line in self.lines}
        return out

    @property
    def active_tracks(self) -> int:
        return len(self._tracks)


def lines_from_config(raw: list) -> list[CountingLine]:
    """Build counting lines from a camera's config, skipping malformed ones.

    A bad line is dropped with a warning rather than crashing the worker: one
    mis-drawn line must not stop a camera being analysed at all.
    """
    lines: list[CountingLine] = []
    for item in raw or []:
        try:
            lines.append(
                CountingLine(
                    name=str(item["name"]),
                    x1=int(item["x1"]),
                    y1=int(item["y1"]),
                    x2=int(item["x2"]),
                    y2=int(item["y2"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("skipping malformed counting line %r: %s", item, exc)
    return lines
