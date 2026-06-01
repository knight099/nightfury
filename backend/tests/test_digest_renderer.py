from app.services.digest.renderer import render_whatsapp_message, build_quiet_payload


PAYLOAD = {
    "headline": "Quiet night, one delivery seen",
    "period": "Last night (22:00 – 06:59)",
    "total_events": 3,
    "by_severity": {"low": 2, "medium": 1},
    "narrative": "Activity was minimal. A delivery was spotted at 02:14 on the front camera.",
    "highlights": [
        {"time": "2026-05-28T02:14:00+05:30", "camera_name": "Front", "why_notable": "Person at gate"},
        {"time": "2026-05-28T03:40:00+05:30", "camera_name": "Garage", "why_notable": "Cat triggered motion"},
    ],
    "quiet_periods": ["00:00 – 02:00", "04:00 – 06:00"],
    "degraded": False,
}


def test_render_whatsapp_includes_headline_and_link():
    text = render_whatsapp_message(PAYLOAD, dashboard_url="https://app/digests/abc")
    assert "Quiet night, one delivery seen" in text
    assert "https://app/digests/abc" in text
    assert text.count("• ") <= 3


def test_quiet_payload_when_no_events():
    payload = build_quiet_payload(period_label="Last night (22:00 – 06:59)")
    assert payload["total_events"] == 0
    assert payload["headline"]
    assert "quiet" in payload["narrative"].lower()
    assert payload["highlights"] == []


def test_render_whatsapp_marks_degraded_payload():
    p = {**PAYLOAD, "degraded": True}
    text = render_whatsapp_message(p, dashboard_url="https://app/x")
    assert "(summary unavailable" in text.lower() or "limited summary" in text.lower()
