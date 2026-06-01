from typing import Mapping


def render_whatsapp_message(payload: Mapping, dashboard_url: str) -> str:
    headline = payload.get("headline", "Nightwatch digest")
    period = payload.get("period", "")
    narrative = payload.get("narrative", "")
    highlights = list(payload.get("highlights", []))[:3]
    degraded = bool(payload.get("degraded", False))

    lines = [f"📋 *{headline}*"]
    if period:
        lines.append(f"_{period}_")
    lines.append("")
    if degraded:
        lines.append("(Limited summary — full AI recap unavailable.)")
    if narrative:
        lines.append(narrative)
    if highlights:
        lines.append("")
        for h in highlights:
            cam = h.get("camera_name", "camera")
            why = h.get("why_notable", "")
            t = (h.get("time") or "").split("T")[-1][:5]  # HH:MM
            lines.append(f"• {t} {cam} — {why}")
    lines.append("")
    lines.append(f"View full digest: {dashboard_url}")
    return "\n".join(lines)


def build_quiet_payload(period_label: str) -> dict:
    return {
        "headline": "All quiet",
        "period": period_label,
        "total_events": 0,
        "by_severity": {},
        "narrative": "It was quiet — nothing of note was detected during this window.",
        "highlights": [],
        "quiet_periods": [],
        "degraded": False,
    }


def build_degraded_payload(events_summary: list[dict], period_label: str) -> dict:
    by_severity: dict[str, int] = {}
    for e in events_summary:
        sev = e.get("severity", "low")
        by_severity[sev] = by_severity.get(sev, 0) + 1
    return {
        "headline": f"{len(events_summary)} events recorded",
        "period": period_label,
        "total_events": len(events_summary),
        "by_severity": by_severity,
        "narrative": (
            "AI summary was unavailable. The list of detected events is preserved "
            "in the dashboard for your review."
        ),
        "highlights": [],
        "quiet_periods": [],
        "degraded": True,
    }
