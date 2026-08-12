"""
nightwatch_locate.py
====================
Grounding/detection layer for NIGHTWATCH's snapshot pipeline.

Slots into the existing frame grabber: the grabber writes snap_<ts>.jpg every
N seconds; this module runs each snapshot through a text-prompted detector,
filters the returned boxes against per-event rules (zone + min size), de-dupes
against recent alerts (loop suppression), and fires an alert callback.

The detector is a *pluggable backend* so you can evaluate on the research-only
LocateAnything-3B now and swap in a commercially-licensed open-detection model
(Grounding DINO, OWLv2) for the shipped product with one line — see
DetectorBackend subclasses at the bottom.

LICENSE NOTE
------------
LocateAnythingBackend uses nvidia/LocateAnything-3B, which is NVIDIA
non-commercial / research-only (Qwen2.5-3B backbone under the Qwen Research
License). Fine for prototyping and benchmarking; do NOT ship it in the paid
product. Use OWLv2Backend (Apache-2.0) for release.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from PIL import Image


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Box:
    """Pixel-coordinate bounding box."""
    x1: float
    y1: float
    x2: float
    y2: float
    label: str = ""
    score: float = 1.0  # confidence; backends that expose it populate this

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    def iou(self, other: "Box") -> float:
        ix1, iy1 = max(self.x1, other.x1), max(self.y1, other.y1)
        ix2, iy2 = min(self.x2, other.x2), min(self.y2, other.y2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0


@dataclass
class EventRule:
    """One thing NIGHTWATCH watches for in a frame.

    prompt        : free-form description handed to the detector
                    (e.g. "a person", "a delivery package", "a vehicle").
    min_area_frac : ignore boxes smaller than this fraction of the frame
                    (filters out distant noise / false positives).
    zone          : optional (x1,y1,x2,y2) in *fractions* of the frame [0..1];
                    a detection only counts if its center falls inside.
                    e.g. front-door region = (0.3, 0.2, 0.7, 0.9).
    cooldown_s    : suppress repeat alerts for this event for N seconds
                    (loop / static-object suppression).
    dedup_iou     : if a new box overlaps a still-cooling box by more than this,
                    treat it as the same object and stay silent.
    min_score     : minimum confidence score (0–1); ignored by LocateAnything
                    which has no per-box score, respected by OWLv2/DINO.
    """
    name: str
    prompt: str
    min_area_frac: float = 0.01
    zone: Optional[tuple[float, float, float, float]] = None
    cooldown_s: float = 30.0
    dedup_iou: float = 0.5
    min_score: float = 0.2


@dataclass
class Alert:
    event: str
    timestamp: float
    boxes: list[Box]
    crop: Optional[Image.Image] = None
    snapshot_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class DetectorBackend(ABC):
    """Anything that turns (image, text prompt) -> list[Box] in pixel coords."""

    @abstractmethod
    def locate(self, image: Image.Image, prompt: str) -> list[Box]:
        ...


# ---------------------------------------------------------------------------
# Backend A — LocateAnything-3B (research/eval only)
# ---------------------------------------------------------------------------

class LocateAnythingBackend(DetectorBackend):
    """Loads nvidia/LocateAnything-3B once and serves grounding queries.

    Wraps the official LocateAnythingWorker from the model card. Requires a
    CUDA GPU (Ampere/Hopper/Lovelace/Blackwell); the 3B model is ~6–7 GB in
    bf16 so it fits a single 4090/L40. Model output coordinates are normalized
    to [0, 1000] and parsed back to pixels here.

    IMPORTANT: verify _parse_boxes against real output before trusting results.
    The model card shows two conflicting formats; the regex below matches the
    worker parser but run locate() on one real frame and print the raw answer
    string to confirm.
    """

    def __init__(self, model_path: str = "nvidia/LocateAnything-3B",
                 device: str = "cuda", generation_mode: str = "hybrid",
                 max_new_tokens: int = 2048):
        import torch
        from transformers import AutoModel, AutoTokenizer, AutoProcessor

        self._torch = torch
        self.device = device
        self.dtype = torch.bfloat16
        self.generation_mode = generation_mode
        self.max_new_tokens = max_new_tokens

        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        self.processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
        self.model = (
            AutoModel.from_pretrained(model_path, torch_dtype=self.dtype,
                                      trust_remote_code=True)
            .to(device).eval()
        )

    def _generate(self, image: Image.Image, question: str) -> str:
        torch = self._torch
        messages = [{"role": "user", "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": question},
        ]}]
        text = self.processor.py_apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        images, videos = self.processor.process_vision_info(messages)
        inputs = self.processor(text=[text], images=images, videos=videos,
                                return_tensors="pt").to(self.device)

        with torch.no_grad():
            response = self.model.generate(
                pixel_values=inputs["pixel_values"].to(self.dtype),
                input_ids=inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
                image_grid_hws=inputs.get("image_grid_hws", None),
                tokenizer=self.tokenizer,
                max_new_tokens=self.max_new_tokens,
                use_cache=True,
                generation_mode=self.generation_mode,
                do_sample=False,
                verbose=False,
            )
        return response[0] if isinstance(response, tuple) else response

    @staticmethod
    def _parse_boxes(answer: str, w: int, h: int, label: str) -> list[Box]:
        # NOTE: confirm this pattern against your installed model version's
        # actual output — the card shows both `<box><n><n><n><n></box>` and a
        # `<box> x1, y1, x2, y2 </box>` form. This matches the worker's parser.
        boxes: list[Box] = []
        for m in re.finditer(r"<box><(\d+)><(\d+)><(\d+)><(\d+)></box>", answer):
            x1, y1, x2, y2 = (int(g) for g in m.groups())
            boxes.append(Box(
                x1=x1 / 1000 * w, y1=y1 / 1000 * h,
                x2=x2 / 1000 * w, y2=y2 / 1000 * h,
                label=label,
                score=1.0,  # LocateAnything exposes no per-box confidence
            ))
        return boxes

    def locate(self, image: Image.Image, prompt: str) -> list[Box]:
        q = f"Locate all the instances that match the following description: {prompt}."
        answer = self._generate(image, q)
        w, h = image.size
        return self._parse_boxes(answer, w, h, label=prompt)


# ---------------------------------------------------------------------------
# Backend B — OWLv2 (Apache-2.0 — production backend)
# ---------------------------------------------------------------------------

class OWLv2Backend(DetectorBackend):
    """Open-vocabulary detector using google/owlv2-base-patch16-ensemble.

    Apache-2.0 licensed — safe to ship in the paid product.

    Each call to locate() passes one text prompt at a time so the interface
    stays identical to LocateAnythingBackend; batching multiple prompts in a
    single forward pass is a perf optimisation you can add later.

    score_thresh: confidence gate applied before returning boxes.  Start at
    0.10–0.15 for broad prompts ("a person") and raise to 0.25+ for specific
    ones ("a delivery package") to cut false positives.  EventRule.min_score
    provides a per-rule override that NightwatchDetector applies on top.
    """

    def __init__(
        self,
        model_id: str = "google/owlv2-base-patch16-ensemble",
        device: str = "cuda",
        score_thresh: float = 0.10,
    ):
        import torch
        from transformers import Owlv2ForObjectDetection, Owlv2Processor

        self._torch = torch
        self.device = device
        self.score_thresh = score_thresh

        self.processor = Owlv2Processor.from_pretrained(model_id)
        self.model = (
            Owlv2ForObjectDetection.from_pretrained(model_id)
            .to(device).eval()
        )

    def locate(self, image: Image.Image, prompt: str) -> list[Box]:
        torch = self._torch
        w, h = image.size
        target_sizes = torch.tensor([[h, w]], device=self.device)

        # OWLv2 expects a list-of-lists for text queries (batch × n_queries).
        inputs = self.processor(
            text=[[prompt]],
            images=image,
            return_tensors="pt",
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model(**inputs)

        results = self.processor.post_process_object_detection(
            outputs,
            threshold=self.score_thresh,
            target_sizes=target_sizes,
        )[0]

        boxes: list[Box] = []
        for box, score in zip(results["boxes"], results["scores"]):
            x1, y1, x2, y2 = box.tolist()
            boxes.append(Box(x1=x1, y1=y1, x2=x2, y2=y2,
                             label=prompt, score=float(score)))
        return boxes


# ---------------------------------------------------------------------------
# The NIGHTWATCH detector — rules, filtering, loop suppression
# ---------------------------------------------------------------------------

class NightwatchDetector:
    def __init__(self, backend: DetectorBackend, rules: Sequence[EventRule],
                 on_alert: Callable[[Alert], None]):
        self.backend = backend
        self.rules = list(rules)
        self.on_alert = on_alert
        # per-event: (last_alert_ts, [boxes still within cooldown])
        self._recent: dict[str, tuple[float, list[Box]]] = {}

    def _passes_filters(self, box: Box, rule: EventRule, w: int, h: int) -> bool:
        if box.area < rule.min_area_frac * (w * h):
            return False
        if box.score < rule.min_score:
            return False
        if rule.zone:
            zx1, zy1, zx2, zy2 = rule.zone
            cx, cy = box.center
            if not (zx1 * w <= cx <= zx2 * w and zy1 * h <= cy <= zy2 * h):
                return False
        return True

    def _is_duplicate(self, box: Box, rule: EventRule, now: float) -> bool:
        last = self._recent.get(rule.name)
        if not last:
            return False
        last_ts, last_boxes = last
        if now - last_ts >= rule.cooldown_s:
            return False  # cooldown expired -> allow new alert
        return any(box.iou(b) >= rule.dedup_iou for b in last_boxes)

    def process(self, image: Image.Image,
                snapshot_path: Optional[str] = None,
                timestamp: Optional[float] = None) -> list[Alert]:
        now = timestamp if timestamp is not None else time.time()
        w, h = image.size
        alerts: list[Alert] = []

        for rule in self.rules:
            boxes = self.backend.locate(image, rule.prompt)
            kept = [b for b in boxes if self._passes_filters(b, rule, w, h)]
            fresh = [b for b in kept if not self._is_duplicate(b, rule, now)]
            if not fresh:
                if kept:
                    # object persists within cooldown — refresh box positions
                    self._recent[rule.name] = (
                        self._recent.get(rule.name, (now, []))[0], kept)
                continue

            crop = None
            b0 = fresh[0]
            crop = image.crop((int(b0.x1), int(b0.y1), int(b0.x2), int(b0.y2)))

            alert = Alert(event=rule.name, timestamp=now, boxes=fresh,
                          crop=crop, snapshot_path=snapshot_path)
            self._recent[rule.name] = (now, kept)
            self.on_alert(alert)
            alerts.append(alert)

        return alerts


# ---------------------------------------------------------------------------
# Test runner — python nightwatch_locate.py [options] snap_*.jpg
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import glob
    import os

    parser = argparse.ArgumentParser(
        description="Run NightwatchDetector against a folder of snapshots.")
    parser.add_argument(
        "--backend", choices=["locate", "owlv2"], default="owlv2",
        help="Detection backend.  'locate' = nvidia/LocateAnything-3B "
             "(research only, needs CUDA + ~7 GB VRAM). "
             "'owlv2' = google/owlv2-base-patch16-ensemble (Apache-2.0, default).")
    parser.add_argument(
        "--locate-model", default="nvidia/LocateAnything-3B",
        metavar="HF_ID",
        help="HuggingFace model ID for the LocateAnything backend.")
    parser.add_argument(
        "--owlv2-model", default="google/owlv2-base-patch16-ensemble",
        metavar="HF_ID",
        help="HuggingFace model ID for the OWLv2 backend.")
    parser.add_argument(
        "--score-thresh", type=float, default=0.10,
        help="Global confidence threshold for OWLv2 (per-rule min_score "
             "can raise it further).  Ignored by LocateAnything.")
    parser.add_argument(
        "--device", default="cuda",
        help="Torch device string, e.g. 'cuda', 'cuda:1', 'cpu'.")
    parser.add_argument(
        "--dump-raw", action="store_true",
        help="(LocateAnything only) Print the raw model answer string before "
             "parsing — use this to verify the box regex on your first run.")
    parser.add_argument(
        "--save-crops", action="store_true",
        help="Save alert crop images as alert_<event>_<ts>.jpg alongside the input.")
    parser.add_argument(
        "snapshots", nargs="*", default=[],
        help="Snapshot file(s) to process.  If omitted, processes snap_*.jpg "
             "in the current directory in timestamp order.")
    args = parser.parse_args()

    # ── Build backend ────────────────────────────────────────────────────────
    if args.backend == "locate":
        print(f"[loader] LocateAnything-3B from {args.locate_model!r} "
              f"on {args.device}  (RESEARCH ONLY — do not ship)")
        backend: DetectorBackend = LocateAnythingBackend(
            model_path=args.locate_model, device=args.device)

        # Monkey-patch _generate to dump raw output when --dump-raw is set.
        if args.dump_raw:
            _orig_generate = backend._generate

            def _patched_generate(image: Image.Image, question: str) -> str:
                answer = _orig_generate(image, question)
                print(f"[raw answer] {answer!r}")
                return answer

            backend._generate = _patched_generate  # type: ignore[method-assign]

    else:
        print(f"[loader] OWLv2 from {args.owlv2_model!r} "
              f"on {args.device}  score_thresh={args.score_thresh}")
        backend = OWLv2Backend(
            model_id=args.owlv2_model,
            device=args.device,
            score_thresh=args.score_thresh,
        )

    # ── Alert handler ────────────────────────────────────────────────────────
    def handle_alert(alert: Alert) -> None:
        scores = ", ".join(f"{b.score:.2f}" for b in alert.boxes)
        print(f"[ALERT] {alert.event}  ts={alert.timestamp:.0f}  "
              f"boxes={len(alert.boxes)}  scores=[{scores}]  "
              f"file={alert.snapshot_path}")
        if args.save_crops and alert.crop is not None:
            out = f"alert_{alert.event}_{int(alert.timestamp)}.jpg"
            alert.crop.save(out)
            print(f"        crop saved → {out}")

    # ── Rules (tune zones/thresholds against real footage) ───────────────────
    rules = [
        EventRule(name="person_at_door", prompt="a person",
                  zone=(0.3, 0.2, 0.7, 0.95), min_area_frac=0.02,
                  cooldown_s=30, min_score=0.15),
        EventRule(name="vehicle_in_driveway", prompt="a car or vehicle",
                  min_area_frac=0.05, cooldown_s=60, min_score=0.20),
        EventRule(name="package", prompt="a delivery package or box on the ground",
                  zone=(0.2, 0.5, 0.8, 1.0), min_area_frac=0.005,
                  cooldown_s=300, min_score=0.10),
    ]

    detector = NightwatchDetector(backend, rules, on_alert=handle_alert)

    # ── Snapshot loop ─────────────────────────────────────────────────────────
    paths = args.snapshots or sorted(glob.glob("snap_*.jpg"))
    if not paths:
        parser.error("No snapshots found.  Pass file paths or cd to the snap folder.")

    for path in paths:
        # Derive timestamp from filename (snap_<ts>.jpg) or fall back to mtime.
        stem = os.path.splitext(os.path.basename(path))[0]
        parts = stem.split("_")
        try:
            ts = float(parts[-1])
        except ValueError:
            ts = os.path.getmtime(path)

        img = Image.open(path).convert("RGB")
        alerts = detector.process(img, snapshot_path=path, timestamp=ts)
        if not alerts:
            print(f"[  ok  ] {path}  — no alerts")
