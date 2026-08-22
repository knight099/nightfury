"""Footfall counting by line crossing.

An operator draws a line across a doorway or corridor on the camera image.
People detected walking across it are counted, with direction — "in" one way,
"out" the other.

WHAT THIS CAN AND CANNOT CLAIM
------------------------------
This is a **traffic estimate, not a turnstile**. It is built on ByteTrack
(vendored from roboflow/supervision, see sv_vendor/), which has no
re-identification. That produces specific, predictable error:

* **Occlusion re-counts.** Someone briefly hidden behind a pillar or another
  person loses their track and gets a fresh one once ByteTrack's own
  lost-track buffer expires. If they cross the line after that, they are
  counted again.
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
from dataclasses import dataclass

import numpy as np
from sv_vendor import ByteTrack, Detections, LineZone, Point, Position
from sv_vendor.smoother import DetectionsSmoother

logger = logging.getLogger(__name__)


@dataclass
class CountingLine:
    """A directed line segment across the frame, in pixel coordinates."""

    name: str
    x1: int
    y1: int
    x2: int
    y2: int


class FootfallCounter:
    """Counts directional line crossings for one camera, backed by
    ByteTrack (tracking) + LineZone (crossing detection) instead of this
    module's previous hand-rolled IoU+proximity tracker and manual
    side-of-line math.

    Still not re-identification — see the module docstring's estimate
    caveats, which remain true: ByteTrack also has no cross-occlusion
    identity recovery beyond its own lost-track buffer.
    """

    def __init__(self, lines: list[CountingLine]):
        self.lines = lines
        self._bytetrack = ByteTrack()
        self._smoother = DetectionsSmoother(length=3)
        self._zones = {
            line.name: LineZone(
                start=Point(line.x1, line.y1),
                end=Point(line.x2, line.y2),
                # Bottom-center, matching this module's old convention (a
                # person's feet cross the line, not their head) — the
                # LineZone default is all four box corners.
                triggering_anchors=(Position.BOTTOM_CENTER,),
                minimum_crossing_threshold=1,
            )
            for line in lines
        }
        # LineZone.in_count/out_count are running totals (a Counter that's
        # never reset) — drain() needs a delta, so snapshot the last-read
        # totals per line and subtract on each drain.
        self._last_totals = {name: {"in": 0, "out": 0} for name in self._zones}

    def update(self, person_boxes: list, now: float) -> None:
        """Advance tracking by one frame and record any crossings.

        ``person_boxes`` are objects with x1/y1/x2/y2 attributes.
        """
        if not self.lines:
            return
        if not person_boxes:
            self._bytetrack.update_with_detections(Detections.empty())
            return

        xyxy = np.array([[b.x1, b.y1, b.x2, b.y2] for b in person_boxes], dtype=np.float32)
        confidence = np.array([1.0] * len(person_boxes), dtype=np.float32)
        detections = Detections(xyxy=xyxy, confidence=confidence, class_id=np.zeros(len(person_boxes), dtype=int))
        tracked = self._bytetrack.update_with_detections(detections)
        tracked = self._smoother.update_with_detections(tracked)

        for zone in self._zones.values():
            zone.trigger(tracked)

    def drain(self) -> dict[str, dict[str, int]]:
        """Return counts since the last drain and reset them."""
        out = {}
        for name, zone in self._zones.items():
            current = {"in": int(zone.in_count), "out": int(zone.out_count)}
            previous = self._last_totals[name]
            out[name] = {
                "in": current["in"] - previous["in"],
                "out": current["out"] - previous["out"],
            }
            self._last_totals[name] = current
        return out

    @property
    def active_tracks(self) -> int:
        return len(self._bytetrack.tracked_tracks)


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
