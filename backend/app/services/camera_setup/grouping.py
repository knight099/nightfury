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
    needs_input_rows: list = []

    for row in rows:
        # Eligible for normal grouping: proposed + valid scene_type + good confidence
        is_eligible = (
            row.status == "proposed"
            and row.scene_type not in (None, "other")
            and (row.confidence or 0.0) >= MIN_CONFIDENCE
        )
        # Terminal states always go in their scene-type group for visibility
        is_terminal = row.status in ("approved", "rejected")

        if is_eligible or is_terminal:
            buckets.setdefault(row.scene_type, []).append(row)
        else:
            needs_input_rows.append(row)

    groups: list[ReviewGroup] = []

    # Add needs_input group if there are any rows
    if needs_input_rows:
        groups.append(
            ReviewGroup(
                scene_type=NEEDS_INPUT,
                label=LABELS[NEEDS_INPUT],
                bulk_approvable=False,
                proposal_ids=[m.id for m in needs_input_rows],
            )
        )

    # Process scene-type buckets
    for key, members in sorted(buckets.items()):
        # Compute majority from proposed rows only
        proposed_members = [m for m in members if m.status == "proposed"]
        terminal_members = [m for m in members if m.status in ("approved", "rejected")]

        if not proposed_members:
            # Only terminal rows, no proposed - show them but not bulk-approvable
            groups.append(
                ReviewGroup(
                    scene_type=key,
                    label=LABELS.get(key, key),
                    bulk_approvable=False,
                    shared_config={},
                    proposal_ids=[m.id for m in terminal_members],
                    differing_proposal_ids=[],
                )
            )
            continue

        # The majority signature defines the group; everything else is an
        # outlier the operator reviews individually.
        counts: dict[tuple, int] = {}
        for m in proposed_members:
            counts[_signature(m.proposal)] = counts.get(_signature(m.proposal), 0) + 1
        majority = max(counts, key=lambda s: (counts[s], str(s)))

        proposed_agreeing = [m for m in proposed_members if _signature(m.proposal) == majority]
        proposed_differing = [m for m in proposed_members if _signature(m.proposal) != majority]
        template = proposed_agreeing[0].proposal

        groups.append(
            ReviewGroup(
                scene_type=key,
                label=LABELS.get(key, key),
                # A group of one is not a bulk action; review it directly.
                bulk_approvable=len(proposed_agreeing) > 1,
                shared_config={f: template.get(f) for f in SHARED_FIELDS},
                proposal_ids=[m.id for m in (proposed_agreeing + terminal_members)],
                differing_proposal_ids=[m.id for m in proposed_differing],
            )
        )
    return groups
