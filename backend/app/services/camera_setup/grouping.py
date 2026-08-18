"""Cluster a batch of proposals into reviewable groups.

Clustering is on a closed scene_type enum, so it is exact rather than fuzzy
string matching. A camera whose config differs from its group's is split out
into its own card rather than silently averaged in — averaging would present
the operator with a config that no camera actually got proposed.
"""

import uuid
from dataclasses import dataclass, field

from app.services.camera_setup.validator import MIN_CONFIDENCE

# The fields a group must agree on to be bulk-approvable. Alert rules are
# deliberately excluded: who gets woken at 2am is confirmed per camera.
SHARED_FIELDS = ("enabled_events", "sensitivity", "suggest_pose")

NEEDS_INPUT = "needs_input"

LABELS = {
    "parking": "Parking",
    "corridor": "Corridors",
    "retail_frontage": "Retail frontage",
    "entrance": "Entrances",
    "loading_bay": "Loading bays",
    "atrium": "Atrium & open areas",
    "perimeter": "Perimeter",
    "other": "Needs your input",
    NEEDS_INPUT: "Needs your input",
}


@dataclass
class ReviewGroup:
    scene_type: str
    label: str
    bulk_approvable: bool
    shared_config: dict = field(default_factory=dict)
    proposal_ids: list[uuid.UUID] = field(default_factory=list)
    differing_proposal_ids: list[uuid.UUID] = field(default_factory=list)


def _signature(proposal: dict) -> tuple:
    events = proposal.get("enabled_events") or []
    return (
        tuple(sorted(str(e) for e in events)),
        proposal.get("sensitivity"),
        bool(proposal.get("suggest_pose")),
    )


def group_proposals(rows) -> list[ReviewGroup]:
    """Group proposals by scene type; split outliers into their own cards."""
    buckets: dict[str, list] = {}
    for row in rows:
        needs_input = (
            row.status in ("needs_input", "failed", "pending")
            or row.scene_type in (None, "other")
            or (row.confidence or 0.0) < MIN_CONFIDENCE
        )
        key = NEEDS_INPUT if needs_input else row.scene_type
        buckets.setdefault(key, []).append(row)

    groups: list[ReviewGroup] = []
    for key, members in sorted(buckets.items()):
        if key == NEEDS_INPUT:
            groups.append(
                ReviewGroup(
                    scene_type=NEEDS_INPUT,
                    label=LABELS[NEEDS_INPUT],
                    bulk_approvable=False,
                    proposal_ids=[m.id for m in members],
                )
            )
            continue

        # The majority signature defines the group; everything else is an
        # outlier the operator reviews individually.
        counts: dict[tuple, int] = {}
        for m in members:
            counts[_signature(m.proposal)] = counts.get(_signature(m.proposal), 0) + 1
        majority = max(counts, key=lambda s: (counts[s], str(s)))

        agreeing = [m for m in members if _signature(m.proposal) == majority]
        differing = [m for m in members if _signature(m.proposal) != majority]
        template = agreeing[0].proposal

        groups.append(
            ReviewGroup(
                scene_type=key,
                label=LABELS.get(key, key),
                # A group of one is not a bulk action; review it directly.
                bulk_approvable=len(agreeing) > 1,
                shared_config={f: template.get(f) for f in SHARED_FIELDS},
                proposal_ids=[m.id for m in agreeing],
                differing_proposal_ids=[m.id for m in differing],
            )
        )
    return groups
