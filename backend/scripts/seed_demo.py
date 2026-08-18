"""Seed a realistic mall-shaped demo dataset, or remove it again.

    cd backend
    PYTHONPATH=$PWD uv run python scripts/seed_demo.py          # create
    PYTHONPATH=$PWD uv run python scripts/seed_demo.py --wipe   # remove

Everything it creates is tagged so `--wipe` can find it again: the site is
named DEMO_SITE_NAME, and every row hangs off that site. Nothing outside the
demo site is touched, so this is safe to run against a database that already
has real data.

It seeds into the SUPER ADMIN'S OWN ORG by default, so a super admin sees it
as their own data rather than having to impersonate someone.

Snapshots are inline SVG data URIs, not GCS objects. The backend passes any
non-`gs://` URL straight through, so the event feed shows real thumbnails
without needing storage credentials or uploaded media.
"""

import argparse
import asyncio
import base64
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

sys.path.insert(0, ".")

from app.core.database import async_session_factory  # noqa: E402
from app.models.agent import Agent  # noqa: E402
from app.models.alert_rule import AlertRule  # noqa: E402
from app.models.camera import Camera  # noqa: E402
from app.models.camera_connection import CameraConnection  # noqa: E402
from app.models.event import Event  # noqa: E402
from app.models.footfall_count import FootfallCount  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.site import Site  # noqa: E402
from app.models.user import User  # noqa: E402

DEMO_SITE_NAME = "Demo Mall — Level 2"

# (name, scene, enabled_events, has_counting_line)
CAMERAS = [
    ("L2 Atrium North", "atrium", ["person", "crowd_spike"], False),
    ("L2 Atrium South", "atrium", ["person", "crowd_spike"], False),
    ("L2 Escalator Head", "corridor", ["person"], True),
    ("L2 Corridor West", "corridor", ["person", "loitering"], False),
    ("L2 Corridor East", "corridor", ["person", "loitering"], False),
    ("L2 Service Corridor", "corridor", ["person", "intrusion"], False),
    ("L2 Jewellery Frontage", "retail_frontage", ["person", "loitering"], False),
    ("L2 Food Court Entry", "entrance", ["person"], True),
    ("B1 Parking Ramp", "parking", ["person", "vehicle"], True),
    ("B1 Parking Bay 4", "parking", ["person", "vehicle"], False),
    ("Loading Bay", "loading_bay", ["person", "vehicle", "intrusion"], False),
    ("Staff Entrance", "entrance", ["person", "intrusion"], True),
]

# Cameras that are physically adjacent — this is what journeys walk.
CONNECTIONS = [
    ("L2 Atrium North", "L2 Escalator Head", "Escalator"),
    ("L2 Escalator Head", "L2 Corridor West", "West hallway"),
    ("L2 Corridor West", "L2 Jewellery Frontage", None),
    ("L2 Corridor East", "L2 Food Court Entry", "Food court doors"),
    ("L2 Corridor West", "L2 Service Corridor", "Staff door"),
    ("B1 Parking Ramp", "B1 Parking Bay 4", None),
]

EVENT_TEMPLATES = [
    ("person", "low", "One person walked through, nothing unusual."),
    ("person", "low", "Shopper paused briefly, then moved on."),
    ("loitering", "medium", "A person remained in this area for over four minutes."),
    ("loitering", "high", "Someone has been standing near the shutter line for nine minutes."),
    ("intrusion", "high", "Movement detected in a staff-only area outside trading hours."),
    ("intrusion", "critical", "Person entered the service corridor after the mall had closed."),
    ("vehicle", "low", "Vehicle entered the parking ramp."),
    ("vehicle", "medium", "Vehicle stopped in the loading bay outside its delivery window."),
    ("crowd_spike", "medium", "Unusually dense group forming near the atrium."),
]


def _snapshot(label: str, severity: str) -> str:
    """A small inline SVG so the feed has something to show."""
    colour = {"low": "#4ADE80", "medium": "#FBBF24", "high": "#F97316", "critical": "#EF4444"}[severity]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180">'
        f'<rect width="320" height="180" fill="#111"/>'
        f'<rect x="8" y="8" width="304" height="164" fill="none" stroke="{colour}" stroke-width="2"/>'
        f'<text x="16" y="34" fill="{colour}" font-family="monospace" font-size="13">{severity.upper()}</text>'
        f'<text x="16" y="160" fill="#A3A3A3" font-family="monospace" font-size="11">{label[:34]}</text>'
        f'<circle cx="160" cy="95" r="26" fill="none" stroke="{colour}" stroke-width="2"/>'
        f"</svg>"
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


async def _target_org(db) -> Organization:
    """Prefer the super admin's own org, so they see this as their own data."""
    sa = (
        await db.execute(
            select(User).where(User.role == "super_admin", User.org_id.isnot(None))
        )
    ).scalars().first()
    if sa is not None:
        org = (await db.execute(select(Organization).where(Organization.id == sa.org_id))).scalar_one_or_none()
        if org is not None:
            return org
    org = (
        await db.execute(select(Organization).where(Organization.deleted_at.is_(None)))
    ).scalars().first()
    if org is None:
        raise SystemExit("No organisation exists to seed into. Create one first.")
    return org


async def _find_site(db, org_id: uuid.UUID) -> Site | None:
    return (
        await db.execute(
            select(Site).where(Site.org_id == org_id, Site.name == DEMO_SITE_NAME)
        )
    ).scalar_one_or_none()


async def wipe(db) -> None:
    org = await _target_org(db)
    site = await _find_site(db, org.id)
    if site is None:
        print("Nothing to wipe — no demo site found.")
        return

    cam_ids = [
        c.id for c in (await db.execute(select(Camera).where(Camera.site_id == site.id))).scalars().all()
    ]
    # Children first — events and counts reference cameras.
    await db.execute(delete(FootfallCount).where(FootfallCount.site_id == site.id))
    await db.execute(delete(CameraConnection).where(CameraConnection.site_id == site.id))
    await db.execute(delete(Event).where(Event.site_id == site.id))
    await db.execute(delete(AlertRule).where(AlertRule.site_id == site.id))
    if cam_ids:
        await db.execute(delete(Camera).where(Camera.id.in_(cam_ids)))
    await db.execute(delete(Agent).where(Agent.site_id == site.id))
    await db.execute(delete(Site).where(Site.id == site.id))
    await db.commit()
    print(f"Wiped demo data from '{org.name}' (site '{DEMO_SITE_NAME}', {len(cam_ids)} cameras).")


async def seed(db) -> None:
    random.seed(7)  # stable output across runs
    org = await _target_org(db)

    if await _find_site(db, org.id) is not None:
        print(f"Demo site already exists in '{org.name}'. Run with --wipe first to reseed.")
        return

    now = datetime.now(timezone.utc)
    site = Site(org_id=org.id, name=DEMO_SITE_NAME, address="Demo Mall, Level 2", timezone="Asia/Kolkata")
    db.add(site)
    await db.flush()

    # Two appliances, so the fleet view shows real placement across a fleet.
    # One is healthy; one has not beaten in a while, which is what makes the
    # "not reporting" state visible.
    healthy = Agent(
        org_id=org.id, site_id=site.id, machine_id="edge-box-01",
        pubkey="demo", device_token_hash="demo", status="online",
        capacity_cameras=8, capacity_source="measured", load_state="ok",
        last_seen_at=now - timedelta(seconds=20), version="1.4.2",
    )
    stale = Agent(
        org_id=org.id, site_id=site.id, machine_id="edge-box-02",
        pubkey="demo", device_token_hash="demo", status="online",
        capacity_cameras=6, capacity_source="declared", load_state="ok",
        last_seen_at=now - timedelta(minutes=14), version="1.4.2",
    )
    db.add_all([healthy, stale])
    await db.flush()

    cameras: dict[str, Camera] = {}
    for i, (name, scene, events, has_line) in enumerate(CAMERAS):
        # Fill the healthy box first, then the stale one; leave the last
        # camera unassigned so the "not being analysed" state is visible.
        if i < 8:
            agent_id, status = healthy.id, "online"
        elif i < len(CAMERAS) - 1:
            agent_id, status = stale.id, "online"
        else:
            agent_id, status = None, "unassigned"

        cam = Camera(
            org_id=org.id, site_id=site.id, agent_id=agent_id, name=name,
            ingest_mode="rtsp_pull", rtsp_url=f"rtsp://10.0.2.{20 + i}/stream1",
            enabled_events=events,
            detection_zones=[{"name": scene.replace("_", " ").title(), "points": [[80, 60], [560, 60], [560, 380], [80, 380]]}],
            counting_lines=([{"name": "Doorway", "x1": 320, "y1": 60, "x2": 320, "y2": 380}] if has_line else []),
            sensitivity="high" if scene in ("loading_bay", "corridor") else "medium",
            status=status, idle_fps=1.0, active_fps=5.0,
            last_frame_at=now - timedelta(seconds=random.randint(2, 40)) if status == "online" else None,
        )
        db.add(cam)
        cameras[name] = cam
    await db.flush()

    for a, b, label in CONNECTIONS:
        ca, cb = cameras[a].id, cameras[b].id
        lo, hi = (ca, cb) if str(ca) < str(cb) else (cb, ca)
        db.add(CameraConnection(org_id=org.id, site_id=site.id, camera_a_id=lo, camera_b_id=hi, label=label))

    # Events across the last 7 days, weighted to recent hours so the dashboard
    # and the 24h stats both look alive.
    online_cams = [c for c in cameras.values() if c.status == "online"]
    total = 0
    for day in range(7):
        for _ in range(random.randint(14, 26)):
            cam = random.choice(online_cams)
            etype, sev, desc = random.choice(EVENT_TEMPLATES)
            if etype not in cam.enabled_events:
                etype, sev, desc = "person", "low", "One person walked through, nothing unusual."
            ts = now - timedelta(days=day, hours=random.uniform(0, 23), minutes=random.uniform(0, 59))

            # Older events are mostly worked; recent ones mostly still open,
            # so the shift-handover filter has something to show.
            if day == 0:
                status = random.choice(["new", "new", "new", "acknowledged"])
            elif day == 1:
                status = random.choice(["new", "acknowledged", "resolved"])
            else:
                status = random.choice(["resolved", "resolved", "dismissed"])

            db.add(Event(
                org_id=org.id, camera_id=cam.id, site_id=site.id, timestamp=ts,
                event_type=etype, confidence=round(random.uniform(0.62, 0.97), 2),
                severity=sev, description=desc, bounding_boxes=[],
                snapshot_url=_snapshot(cam.name, sev), ai_model="gemini-2.0-flash",
                status=status,
                acknowledged_at=ts + timedelta(minutes=random.randint(1, 12)) if status != "new" else None,
                resolved_at=ts + timedelta(minutes=random.randint(13, 90)) if status in ("resolved", "dismissed") else None,
                feedback=random.choice([None, None, "approved", "rejected"]),
                metadata_extra={},
            ))
            total += 1

    # Footfall on the cameras that have a counting line: a believable daily
    # curve, quiet overnight and busy late afternoon.
    line_cams = [c for c in cameras.values() if c.counting_lines]
    buckets = 0
    for cam in line_cams:
        for hours_ago in range(48):
            bucket = now - timedelta(hours=hours_ago)
            hour = bucket.astimezone(timezone.utc).hour
            base = 0 if hour < 8 or hour > 22 else (14 if 16 <= hour <= 20 else 6)
            if base == 0:
                continue
            db.add(FootfallCount(
                org_id=org.id, site_id=site.id, camera_id=cam.id,
                line_name=cam.counting_lines[0]["name"], bucket_at=bucket,
                count_in=max(0, base + random.randint(-4, 6)),
                count_out=max(0, base + random.randint(-5, 5)),
            ))
            buckets += 1

    db.add(AlertRule(
        org_id=org.id, site_id=site.id, name="After-hours intrusion — escalate",
        cameras=[], event_types=["intrusion"], min_severity="high",
        time_window={"start": "22:00", "end": "06:00", "days": []}, zones=[],
        notify_channels=["whatsapp"], notify_contacts=[{"type": "whatsapp", "value": "+910000000000"}],
        cooldown_seconds=120, enabled=True,
        escalation=[
            {"after_seconds": 300, "channels": ["whatsapp"], "contacts": [{"type": "whatsapp", "value": "+910000000001"}]},
            {"after_seconds": 900, "channels": ["whatsapp"], "contacts": [{"type": "whatsapp", "value": "+910000000002"}]},
        ],
    ))

    await db.commit()
    print(f"Seeded into org '{org.name}':")
    print(f"  site         {DEMO_SITE_NAME}")
    print(f"  appliances   2 (edge-box-01 healthy, edge-box-02 stale for ~14min)")
    print(f"  cameras      {len(CAMERAS)}  (11 placed, 1 left unassigned on purpose)")
    print(f"  connections  {len(CONNECTIONS)}  (drives journeys on /map)")
    print(f"  events       {total} over 7 days, mixed severity and incident status")
    print(f"  footfall     {buckets} hourly buckets across {len(line_cams)} counting lines")
    print(f"  alert rule   1, with a 2-rung escalation ladder")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wipe", action="store_true", help="remove the demo data instead of creating it")
    args = ap.parse_args()
    async with async_session_factory() as db:
        await (wipe(db) if args.wipe else seed(db))


if __name__ == "__main__":
    asyncio.run(main())
