"""Validation of an agent-returned setup proposal.

A proposal that fails validation is marked `needs_input` with the reasons
attached. It is NEVER silently corrected: a corrected proposal is no longer
the thing the model justified in its rationale, so approving it would mean a
human accepting something nobody explained.
"""

SCENE_TYPES = {
    "parking",
    "corridor",
    "retail_frontage",
    "entrance",
    "loading_bay",
    "atrium",
    "perimeter",
    "other",
}

VALID_SENSITIVITIES = {"low", "medium", "high"}

# Below this, the proposal goes to the "Needs your input" group and can never
# be bulk-approved.
MIN_CONFIDENCE = 0.6

# Matches the camera model's existing vocabulary.
KNOWN_EVENT_TYPES = {
    "person",
    "vehicle",
    "animal",
    "intrusion",
    "loitering",
    "crowd_spike",
}


def validate_proposal(proposal: dict, frame_width: int, frame_height: int) -> list[str]:
    """Return a list of failure reasons. Empty list means the proposal is usable."""
    reasons: list[str] = []

    scene_type = proposal.get("scene_type")
    if scene_type not in SCENE_TYPES:
        reasons.append(f"unknown scene_type {scene_type!r}")

    confidence = proposal.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        reasons.append("confidence missing or out of range")

    events = proposal.get("enabled_events")
    if not isinstance(events, list) or not events:
        reasons.append("enabled_events is empty")
    else:
        unknown = [e for e in events if e not in KNOWN_EVENT_TYPES]
        if unknown:
            reasons.append(f"unknown event types: {', '.join(map(str, unknown))}")

    if proposal.get("sensitivity") not in VALID_SENSITIVITIES:
        reasons.append("sensitivity must be low, medium or high")

    for zone in proposal.get("zones") or []:
        name = zone.get("name")
        polygon = zone.get("polygon")
        if not name:
            reasons.append("a zone has no name")
        if not isinstance(polygon, list) or len(polygon) < 3:
            reasons.append(f"zone {name!r} needs at least 3 points")
            continue
        for point in polygon:
            if (
                not isinstance(point, (list, tuple))
                or len(point) != 2
                or not (0 <= point[0] <= frame_width)
                or not (0 <= point[1] <= frame_height)
            ):
                reasons.append(f"zone {name!r} has a point outside the frame")
                break

    for line in proposal.get("counting_lines") or []:
        name = line.get("name")
        if not name:
            reasons.append("a counting line has no name")
        try:
            x1, y1, x2, y2 = int(line["x1"]), int(line["y1"]), int(line["x2"]), int(line["y2"])
        except (KeyError, TypeError, ValueError):
            reasons.append(f"counting line {name!r} is missing coordinates")
            continue
        if (x1, y1) == (x2, y2):
            reasons.append(f"counting line {name!r} has zero length")
        for x, y in ((x1, y1), (x2, y2)):
            if not (0 <= x <= frame_width and 0 <= y <= frame_height):
                reasons.append(f"counting line {name!r} extends outside the frame")
                break

    if not proposal.get("rationale"):
        # The rationale is what an operator reads before approving twelve
        # cameras at once. A proposal without one cannot be reviewed.
        reasons.append("no rationale given")

    return reasons
