"""
Test Gemini Vision using device webcam.
Uses local gcloud auth (project: gebra-ai).

Usage:
    python3 test_webcam.py

Controls:
    SPACE  - Capture and analyze current frame
    A      - Toggle auto-analyze (every 3 seconds)
    Q/ESC  - Quit
"""
import asyncio
import json
import time
import os

import cv2
import numpy as np
from google import genai
from google.genai.types import GenerateContentConfig, Part

from models import CameraConfig, BoundingBox, DetectedEvent
from prompt_builder import PromptBuilder

CAMERA_CONFIG = CameraConfig(
    camera_id="webcam-test",
    org_id="test",
    site_id="test",
    name="Webcam (Local Test)",
    site_name="Home Office",
    ingest_mode="local",
    enabled_events=["person", "vehicle", "intrusion", "loitering", "fire_smoke", "object_left", "ppe_violation", "crowd_spike"],
    sensitivity="high",
    timezone="Asia/Kolkata",
)

CONFIDENCE_THRESHOLDS = {"low": 0.85, "medium": 0.70, "high": 0.50}


def draw_results(frame: np.ndarray, events: list[DetectedEvent], scene_summary: str, person_count: int) -> np.ndarray:
    """Draw bounding boxes and event info on frame."""
    display = frame.copy()

    for event in events:
        for bb in event.bounding_boxes:
            color = {
                "low": (128, 222, 74),
                "medium": (36, 191, 251),
                "high": (22, 115, 249),
                "critical": (68, 68, 239),
            }.get(event.severity, (255, 144, 30))

            cv2.rectangle(display, (bb.x1, bb.y1), (bb.x2, bb.y2), color, 2)
            label = f"{bb.label} ({event.confidence:.0%})"
            cv2.putText(display, label, (bb.x1, bb.y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    y_offset = 30
    for event in events:
        severity_color = {
            "low": (128, 222, 74),
            "medium": (36, 191, 251),
            "high": (22, 115, 249),
            "critical": (68, 68, 239),
        }.get(event.severity, (255, 255, 255))

        text = f"[{event.severity.upper()}] {event.event_type}: {event.description} ({event.confidence:.0%})"
        cv2.putText(display, text, (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.45, severity_color, 1)
        y_offset += 22

    if scene_summary:
        cv2.putText(display, f"Scene: {scene_summary}", (10, display.shape[0] - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (163, 163, 163), 1)
    cv2.putText(display, f"Persons: {person_count}", (10, display.shape[0] - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (245, 245, 245), 1)

    return display


async def analyze_frame(client, frame: np.ndarray) -> tuple[list[DetectedEvent], str, int]:
    """Send frame to Gemini and parse response."""
    _, jpeg_buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    frame_jpeg = jpeg_buf.tobytes()

    prompt_builder = PromptBuilder()
    prompt = prompt_builder.build(CAMERA_CONFIG)

    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                Part.from_text(text=prompt),
                Part.from_bytes(data=frame_jpeg, mime_type="image/jpeg"),
            ],
            config=GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        text = response.text
        data = json.loads(text)

        threshold = CONFIDENCE_THRESHOLDS.get(CAMERA_CONFIG.sensitivity, 0.70)
        events = []
        for event_data in data.get("events", []):
            event_type = event_data.get("event_type", "")
            confidence = event_data.get("confidence", 0)

            if event_type not in CAMERA_CONFIG.enabled_events:
                continue
            if confidence < threshold:
                continue

            bboxes = []
            for bb in event_data.get("bounding_boxes", []):
                bboxes.append(BoundingBox(
                    x1=bb.get("x1", 0), y1=bb.get("y1", 0),
                    x2=bb.get("x2", 0), y2=bb.get("y2", 0),
                    label=bb.get("label", ""),
                ))

            events.append(DetectedEvent(
                event_type=event_type,
                confidence=confidence,
                severity=event_data.get("severity", "low"),
                description=event_data.get("description", ""),
                bounding_boxes=bboxes,
                zone=event_data.get("zone"),
            ))

        return events, data.get("scene_summary", ""), data.get("person_count", 0)

    except json.JSONDecodeError as e:
        print(f"  [ERROR] Bad JSON from Gemini: {e}")
        return [], "", 0
    except Exception as e:
        print(f"  [ERROR] Gemini call failed: {e}")
        return [], "", 0


async def main():
    print("=" * 50)
    print("  NIGHTWATCH — Webcam AI Test")
    print("  Auth: gcloud ADC (Vertex AI)")
    print("  Project: gebra-ai (us-central1)")
    print("  Model: gemini-2.5-flash")
    print("=" * 50)
    print()
    print("  SPACE  = Capture & Analyze")
    print("  A      = Toggle auto-analyze (3s)")
    print("  Q/ESC  = Quit")
    print()

    # Uses Vertex AI with ADC (run: gcloud auth application-default login)
    client = genai.Client(vertexai=True, project="gebra-ai", location="us-central1")

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ERROR] Cannot open webcam")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    auto_mode = False
    last_auto_time = 0
    events: list[DetectedEvent] = []
    scene_summary = ""
    person_count = 0
    analyzing = False
    status_text = "Ready — press SPACE to analyze"

    print("[OK] Webcam opened. Window should appear.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[ERROR] Failed to read frame")
            break

        frame = cv2.resize(frame, (1280, 720))

        display = draw_results(frame, events, scene_summary, person_count)

        color = (30, 144, 255) if not analyzing else (36, 191, 251)
        cv2.putText(display, status_text, (10, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        if auto_mode:
            cv2.putText(display, "[AUTO]", (display.shape[1] - 70, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (74, 222, 128), 1)

        cv2.imshow("Nightwatch — Webcam Test", display)

        key = cv2.waitKey(1) & 0xFF

        should_analyze = False
        if key == ord(" "):
            should_analyze = True
        elif key == ord("a"):
            auto_mode = not auto_mode
            status_text = "Auto mode ON" if auto_mode else "Auto mode OFF"
            print(f"  Auto-analyze: {'ON' if auto_mode else 'OFF'}")
        elif key == ord("q") or key == 27:
            break

        if auto_mode and (time.time() - last_auto_time) > 3:
            should_analyze = True

        if should_analyze and not analyzing:
            analyzing = True
            status_text = "Analyzing..."
            print(f"  [{time.strftime('%H:%M:%S')}] Sending frame to Gemini...")

            events, scene_summary, person_count = await analyze_frame(client, frame)
            last_auto_time = time.time()
            analyzing = False

            if events:
                status_text = f"Detected {len(events)} event(s)"
                for e in events:
                    print(f"    → [{e.severity.upper()}] {e.event_type}: {e.description} ({e.confidence:.0%})")
            else:
                status_text = "No events detected"
                print("    → No events")

            if scene_summary:
                print(f"    Scene: {scene_summary}")
            print(f"    Persons: {person_count}")

    cap.release()
    cv2.destroyAllWindows()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
