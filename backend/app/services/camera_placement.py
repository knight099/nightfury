"""Camera → agent placement.

The backend is the assignment authority: it decides which cameras run on which
edge box, and agents execute what they are told. Keeping placement in one place
makes it auditable, overridable by a human, and reasonable to test.

Two layers, deliberately separated:

* ``plan_placement`` — a pure function over plain dataclasses. No DB, no I/O.
  All the placement policy lives here.
* ``reconcile_site`` — the thin caller that loads state, applies the plan, and
  bumps the affected agents' ``assignment_version``.

Policy, in priority order:

1. **Site affinity is absolute.** An agent is physically on one LAN, so it can
   only serve cameras at its own site. This is a hard constraint, never a
   preference — placing a camera on an agent that cannot reach it produces a
   silently dead camera.
2. **Pins win.** An operator who pinned a camera to a box knows something about
   the building that the packer does not. Pinned cameras are placed first and
   are never moved, even if that leaves the packing lopsided.
3. **Stickiness.** A camera already on a healthy agent with capacity stays
   there. Moving a camera restarts its stream, so movement must be justified by
   necessity, never by a marginally better packing.
4. **Least-loaded first** for genuinely new placements, which spreads load
   rather than filling one box before touching the next.
5. **Overflow is explicit.** Cameras that fit nowhere are returned as
   ``unassigned`` rather than silently dropped. That state is what the fleet
   view surfaces and what tells the customer to add an appliance.

The function is deterministic and idempotent: same inputs produce the same
output, and applying a plan then re-planning yields no further moves. That is
what makes it safe to run on every lifecycle event without causing churn.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.camera import Camera

logger = logging.getLogger(__name__)

# Capacity assumed for an agent that has not yet reported one. Conservative on
# purpose: under-filling a box leaves cameras visibly unassigned (recoverable,
# and the fleet view says so), while over-filling it causes the agent to reject
# cameras and forces a second placement round.
DEFAULT_CAPACITY = 4

# Camera statuses that mean "not placed anywhere". Kept here so the API layer
# and the reconciler agree on the vocabulary.
STATUS_UNASSIGNED = "unassigned"


@dataclass(frozen=True)
class CameraSlot:
    """A camera that needs a home."""

    camera_id: uuid.UUID
    site_id: uuid.UUID
    current_agent_id: uuid.UUID | None = None
    pinned_agent_id: uuid.UUID | None = None


@dataclass(frozen=True)
class AgentSlot:
    """An agent that can host cameras."""

    agent_id: uuid.UUID
    site_id: uuid.UUID | None
    capacity: int
    healthy: bool = True


@dataclass
class PlacementPlan:
    """Result of planning. ``assignments`` covers every input camera."""

    assignments: dict[uuid.UUID, uuid.UUID | None] = field(default_factory=dict)
    moved: list[uuid.UUID] = field(default_factory=list)
    unassigned: list[uuid.UUID] = field(default_factory=list)
    per_agent_count: dict[uuid.UUID, int] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.moved)


def plan_placement(cameras: list[CameraSlot], agents: list[AgentSlot]) -> PlacementPlan:
    """Assign cameras to agents. Pure — no I/O, no DB, no clock.

    Cameras and agents may span multiple sites; site affinity is enforced
    per-camera, so callers can pass a whole org or a single site.
    """
    # Deterministic iteration regardless of DB row order.
    cameras = sorted(cameras, key=lambda c: str(c.camera_id))
    usable = {
        a.agent_id: a
        for a in sorted(agents, key=lambda a: str(a.agent_id))
        if a.healthy and a.site_id is not None and a.capacity > 0
    }

    load: dict[uuid.UUID, int] = {aid: 0 for aid in usable}
    plan = PlacementPlan()

    def can_host(agent_id: uuid.UUID | None, cam: CameraSlot) -> bool:
        """Capacity and site affinity, the two hard constraints."""
        if agent_id is None:
            return False
        agent = usable.get(agent_id)
        if agent is None:
            return False
        if agent.site_id != cam.site_id:
            return False
        return load[agent_id] < agent.capacity

    def place(cam: CameraSlot, agent_id: uuid.UUID) -> None:
        load[agent_id] += 1
        plan.assignments[cam.camera_id] = agent_id
        if cam.current_agent_id != agent_id:
            plan.moved.append(cam.camera_id)

    def drop(cam: CameraSlot) -> None:
        plan.assignments[cam.camera_id] = None
        plan.unassigned.append(cam.camera_id)
        if cam.current_agent_id is not None:
            plan.moved.append(cam.camera_id)

    # Pass 1 — pinned cameras. They consume capacity before anything else, so
    # an unpinned camera can never squeeze a pinned one out of its box.
    remaining: list[CameraSlot] = []
    for cam in cameras:
        if cam.pinned_agent_id is None:
            remaining.append(cam)
            continue
        if can_host(cam.pinned_agent_id, cam):
            place(cam, cam.pinned_agent_id)
        else:
            # A pin we cannot honour is an operator-visible problem, not
            # something to quietly re-pack elsewhere — the pin expressed an
            # intent that no longer holds.
            logger.warning(
                "camera %s pinned to agent %s which cannot host it "
                "(capacity, health, or site mismatch)",
                cam.camera_id,
                cam.pinned_agent_id,
            )
            drop(cam)

    # Pass 2 — stickiness. Anything already running somewhere valid stays put.
    still_homeless: list[CameraSlot] = []
    for cam in remaining:
        if can_host(cam.current_agent_id, cam):
            place(cam, cam.current_agent_id)  # type: ignore[arg-type]
        else:
            still_homeless.append(cam)

    # Pass 3 — new placements onto the least-loaded eligible agent.
    for cam in still_homeless:
        candidates = [
            a
            for a in usable.values()
            if a.site_id == cam.site_id and load[a.agent_id] < a.capacity
        ]
        if not candidates:
            drop(cam)
            continue
        # Tie-break on agent_id so the result is stable, not dict-order.
        best = min(candidates, key=lambda a: (load[a.agent_id], str(a.agent_id)))
        place(cam, best.agent_id)

    plan.per_agent_count = dict(load)
    return plan


async def reconcile_site(
    db: AsyncSession,
    org_id: uuid.UUID,
    site_id: uuid.UUID | None = None,
) -> PlacementPlan:
    """Load state for an org (or one site), plan, and apply.

    Applies only what changed, and bumps ``assignment_version`` on every agent
    whose camera set was touched — that version is the ETag that lets agents
    skip re-fetching unchanged config.
    """
    cam_stmt = select(Camera).where(
        Camera.org_id == org_id, Camera.deleted_at.is_(None)
    )
    agent_stmt = select(Agent).where(Agent.org_id == org_id)
    if site_id is not None:
        cam_stmt = cam_stmt.where(Camera.site_id == site_id)
        agent_stmt = agent_stmt.where(Agent.site_id == site_id)

    cameras = list((await db.execute(cam_stmt)).scalars().all())
    agents = list((await db.execute(agent_stmt)).scalars().all())
    agents_by_id = {a.id: a for a in agents}

    plan = plan_placement(
        cameras=[
            CameraSlot(
                camera_id=c.id,
                site_id=c.site_id,
                current_agent_id=c.agent_id,
                pinned_agent_id=c.pinned_agent_id,
            )
            for c in cameras
        ],
        agents=[
            AgentSlot(
                agent_id=a.id,
                site_id=a.site_id,
                capacity=a.capacity_cameras if a.capacity_cameras is not None else DEFAULT_CAPACITY,
                # Both pairing paths set "online"; anything else (a future
                # revoked/suspended state, or a row that never completed
                # pairing) must not be handed cameras.
                healthy=a.status == "online",
            )
            for a in agents
        ],
    )

    if not plan.changed:
        return plan

    touched: set[uuid.UUID] = set()
    moved = set(plan.moved)
    for camera in cameras:
        if camera.id not in moved:
            continue
        new_agent_id = plan.assignments.get(camera.id)
        if camera.agent_id is not None:
            touched.add(camera.agent_id)
        if new_agent_id is not None:
            touched.add(new_agent_id)

        camera.agent_id = new_agent_id
        if new_agent_id is None:
            # Distinct from "offline": the camera may be perfectly healthy —
            # nobody is watching it. The UI must not conflate the two.
            camera.status = STATUS_UNASSIGNED
        elif camera.status == STATUS_UNASSIGNED:
            # Placed again; let the next heartbeat report the real status.
            camera.status = "offline"

    for agent_id, count in plan.per_agent_count.items():
        agent = agents_by_id.get(agent_id)
        if agent is not None:
            agent.assigned_count = count
    for agent_id in touched:
        agent = agents_by_id.get(agent_id)
        if agent is not None:
            agent.assignment_version += 1

    await db.flush()
    logger.info(
        "placement reconciled org=%s site=%s moved=%d unassigned=%d",
        org_id,
        site_id,
        len(plan.moved),
        len(plan.unassigned),
    )
    return plan
