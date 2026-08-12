from models import CameraConfig
from prompt_builder import PromptBuilder


def test_basic_prompt_build():
    builder = PromptBuilder()
    cam = CameraConfig(
        camera_id="test-123",
        org_id="org-456",
        site_id="site-789",
        name="Front Door Cam",
        site_name="Office Mumbai",
        ingest_mode="rtsp_pull",
        enabled_events=["person", "vehicle", "intrusion"],
        sensitivity="medium",
    )

    prompt = builder.build(cam)

    assert "Front Door Cam" in prompt
    assert "Office Mumbai" in prompt
    assert "person, vehicle, intrusion" in prompt
    assert "medium" in prompt
    assert "JSON" in prompt


def test_prompt_with_zones():
    builder = PromptBuilder()
    cam = CameraConfig(
        camera_id="test-123",
        org_id="org-456",
        site_id="site-789",
        name="Parking Cam",
        site_name="Mall",
        ingest_mode="rtsp_pull",
        enabled_events=["person"],
        detection_zones=[{"name": "Entry Gate", "points": [[0, 0], [100, 0], [100, 100]]}],
        sensitivity="high",
    )

    prompt = builder.build(cam)

    assert "Entry Gate" in prompt
    assert "Detection zones:" in prompt
    assert "high" in prompt
