# Camera-to-Books Workflow Layer — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make event ingestion durably ordered, then add a camera-event → business-document exception layer with exactly one workflow module (Dock GRN auto-match) working end to end, from a dock camera through a Tally-synced purchase order to a human-approvable exception in the dashboard.

**Architecture:** Five layers on top of the existing event pipeline. Layer 2 tags cameras with a `camera_role` and teaches the edge pipeline to report goods observations in `metadata_extra`. Layer 3 is a workflow engine that consumes committed events off a Redis queue and writes `workflow_exceptions` rows — never inline in the ingestion request, so a workflow failure can never roll back an event. Layer 4 is a read-only Tally connector populating `expected_documents`. Layer 5 is the exception queue API and UI. Everything from Layer 2 up is inert until an operator creates a `workflow_rules` row, so existing alerting customers see no behaviour change.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + PostgreSQL + Redis (queues and pub/sub) + APScheduler (existing digest scheduler) on the backend; Python 3 dataclasses in `agent/pipeline/`; Next.js App Router + TypeScript + Tailwind + shadcn/ui + TanStack Query on the frontend.

**Spec:** `docs/superpowers/specs/2026-08-26-camera-to-books-spec.md` — read Appendix A before starting; it records four places where the spec and the actual codebase disagree.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **No `tenant_id`.** This codebase uses `org_id` (FK to `organizations.id`). Every new table carries `org_id` and, where a site is knowable, `site_id`.
- **Every read query needs both halves of tenant isolation:** an `org_id` filter (skipped only for `role == "super_admin"`) *plus* `scope_to_sites(query, <Model>.site_id, user)`. Copy the pattern from `backend/app/api/camera_setup.py:38-58`.
- **Never trust `org_id` from a request body.** Derive it from `get_current_user` (operator routes) or from the resolved camera/agent (internal routes).
- **Super-admin bypass keys off `user.role == "super_admin"`, never off `org_id is None`.**
- **No test files.** The repo owner's standing preference is direct implementation plus structured self-review. Every task ends with an explicit manual verification step and a self-review checklist. See spec Appendix A.6.
- **Off by default.** No `workflow_rules` row for a site means the engine does nothing for that site. No behaviour change for any existing org.
- **No write-back to Tally.** Drafts are stored in `workflow_exceptions.draft` and rendered in the UI. Nothing is posted to an external system in Phase 1.
- **Dark mode only** on the frontend. No light-mode styles.
- **`npm run build` must pass** in `frontend/` before any frontend task is considered done.
- **`python3 -c "from app.main import app"` must pass** from `backend/` before any backend task is considered done.
- **Alembic chain:** the current head is `80f8c57dc838` (`alembic/versions/80f8c57dc838_assistant_proposals.py`). Migrations in this plan chain off it in task order. Do not create a second head.
- **Commit after every task**, using the message given in the task's final step.

---

## File Structure

**Backend — modified**

| File | Change |
|---|---|
| `backend/app/api/internal.py` | `ingest_event` commits explicitly before any side effect; enqueues notifications and a workflow job instead of sending/broadcasting inline |
| `backend/app/services/alert_service.py` | `evaluate_event` stops sending; returns queued `NotificationJob`s and writes `AlertHistory` rows with `status="queued"` |
| `backend/app/ws/events.py` | `broadcast_to_org` becomes local-only delivery; new `publish_to_org` publishes to Redis; new subscriber task fans out to local sockets |
| `backend/app/services/digest/service.py` | switches its one `broadcast_to_org` call to `publish_to_org` |
| `backend/app/main.py` | lifespan starts the notification consumer, the workflow consumer, and the WS subscriber; registers two new routers and the Tally sync scheduler job |
| `backend/app/models/camera.py` | adds `camera_role` |
| `backend/app/models/__init__.py` | registers the four new models |
| `backend/app/schemas/camera.py` | `camera_role` on create/update/response |
| `backend/app/schemas/assignment.py` | `camera_role` on `Assignment` |
| `backend/app/api/agents.py` | assignment builder includes `camera_role` |

**Backend — created**

| File | Responsibility |
|---|---|
| `backend/app/schemas/notification_job.py` | The queued-notification envelope |
| `backend/app/services/notification_queue.py` | Enqueue + consumer loop for notification delivery |
| `backend/app/models/workflow.py` | `WorkflowRule`, `ExpectedDocument`, `WorkflowException`, `ConnectorSyncLog` |
| `backend/app/schemas/workflow.py` | Request/response models for the workflow API |
| `backend/app/services/workflows/__init__.py` | Module registry — maps `workflow_type` → evaluator |
| `backend/app/services/workflows/outcome.py` | `WorkflowOutcome` — the one shape every module returns |
| `backend/app/services/workflows/engine.py` | Loads enabled rules for an event, dispatches to modules, persists exceptions |
| `backend/app/services/workflows/dock_grn.py` | Module 3.1, hardcoded. The only module in Phase 1 |
| `backend/app/services/workflows/queue.py` | Enqueue + consumer loop for post-commit workflow evaluation |
| `backend/app/connectors/__init__.py` | Package marker |
| `backend/app/connectors/tally/client.py` | Tally XML request builder + response parser, transport-injected |
| `backend/app/connectors/tally/sync.py` | Delta pull → upsert `expected_documents` → write `connector_sync_log` |
| `backend/app/api/workflows.py` | Exception queue + rules endpoints |
| `backend/app/api/connectors.py` | Tally status + manual sync endpoints |
| `backend/alembic/versions/a1b2c3d4e5f6_camera_role.py` | Task 4 migration |
| `backend/alembic/versions/b2c3d4e5f6a7_workflow_tables.py` | Task 6 migration |

**Edge pipeline — modified**

| File | Change |
|---|---|
| `agent/pipeline/models.py` | `CameraConfig.camera_role`; `DetectedEvent.metadata` |
| `agent/pipeline/prompt_builder.py` | dock-role addendum asking for a goods block |
| `agent/pipeline/gemini_client.py` | parses the goods block onto `DetectedEvent.metadata` |
| `agent/pipeline/event_packager.py` | posts `metadata_extra` |

**Frontend — created / modified**

| File | Change |
|---|---|
| `frontend/src/app/exceptions/page.tsx` | Create — exception queue list + detail |
| `frontend/src/components/exceptions/exception-detail.tsx` | Create — snapshot / document / discrepancy diff |
| `frontend/src/components/exceptions/connector-status.tsx` | Create — Tally sync health widget |
| `frontend/src/app/settings/page.tsx` | Modify — per-site workflow toggles |
| `frontend/src/components/layout/sidebar.tsx` | Modify — "Exceptions" nav entry |
| `frontend/src/components/layout/app-shell.tsx` | Modify — same entry for the `/app` shell |
| `frontend/src/lib/api.ts` | Modify — six new client methods |
| `frontend/src/types/index.ts` | Modify — workflow types |

---

# Phase A — Durability prerequisites (spec Section 0)

Nothing downstream is trustworthy until an event is committed before anything observes it. Do these three first, in order.

> **Note on Section 0 item 4:** already fixed. `soft_delete_service.py` replaced the cascade delete and `admin.py` calls it. No task here. Verify with `grep -n "soft_delete_service" backend/app/api/admin.py` and move on.

---

### Task 1: Commit event before any side effect

**Files:**
- Modify: `backend/app/api/internal.py:32-72`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ingest_event` returns `{"event_id": str, "alerts_triggered": int}` — unchanged contract. After this task, any code placed after the explicit `await db.commit()` is guaranteed to be observing a durable row. Tasks 2, 3 and 7 hang their work off that line.

**Why not fix `get_db` itself:** `get_db` is a dependency of ~97 routes. Making it commit before the response would change response semantics everywhere at once for the benefit of one route. The fix is an explicit commit at the one place ordering actually matters. A second `commit()` on an already-committed `AsyncSession` opens and commits an empty transaction — harmless — so `get_db`'s trailing commit needs no change. `expire_on_commit=False` is already set (`app/core/database.py:26`), so ORM attributes survive the commit and the response payload can be built on either side of it.

- [ ] **Step 1: Rewrite `ingest_event`'s tail**

Replace `backend/app/api/internal.py` lines 56-72 (from `db.add(event)` through the `return`) with:

```python
    db.add(event)
    await db.flush()

    alerts_triggered = await alert_service.evaluate_event(event, db)

    # Built before the commit so a failed commit costs nothing, and so the
    # signed URLs are computed once regardless of which side of the commit
    # the broadcast ends up on.
    payload = EventResponse.model_validate(event).model_dump(mode="json")
    payload["snapshot_url"] = sign_gcs_url(event.snapshot_url)
    if event.clip_url:
        payload["clip_url"] = sign_gcs_url(event.clip_url)
    event_id = str(event.id)
    org_id = str(event.org_id)

    # The ordering fix. Everything below this line observes a durable row;
    # everything above it is still rollback-able. A 503 here tells the edge
    # box to retry — it must NOT get a 201 for an event that was never
    # written, because the pipeline treats 201 as "delivered, drop it".
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("event commit failed for camera %s", body.camera_id)
        raise HTTPException(status_code=503, detail="Event not persisted, retry")

    try:
        message = {"type": "event.created", "event": payload}
        await broadcast_to_org(org_id, message)
        await broadcast_to_org("all", message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws broadcast failed for event %s: %s", event_id, exc)

    return {"event_id": event_id, "alerts_triggered": alerts_triggered}
```

- [ ] **Step 2: Verify imports still resolve**

```bash
cd backend && uv run python3 -c "from app.main import app; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Verify the ordering by hand**

Start the backend (`./start.sh`, or the backend alone per CLAUDE.md). Post an event for a camera that does not exist, then one that does:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8080/internal/events -H "X-Worker-Key: $WORKER_API_KEY" -H 'Content-Type: application/json' -d '{"camera_id":"00000000-0000-0000-0000-000000000000","timestamp":"2026-08-26T10:00:00Z","event_type":"person","confidence":0.9,"severity":"low","description":"x"}'
```

Expected: `404`, and no `event.created` frame on an open dashboard WebSocket.

Then post with a real `camera_id` from your DB and confirm `201` plus the row existing:

```bash
psql "$POSTGRES_URL" -c "select id, event_type from events order by created_at desc limit 1;"
```

Expected: the row returned by the 201's `event_id` is present.

- [ ] **Step 4: Self-review**

Check and note each:
- Is there any `await` between the `db.commit()` and the `return` that could raise and turn a persisted event into a 5xx? (The broadcast is wrapped; nothing else should be.)
- Does the 503 path leave the session usable for `get_db`'s teardown? (`rollback()` then raise — yes.)
- Does anything else in this file rely on `get_db`'s post-yield commit for a row created *before* line 56? (Check `worker_heartbeat` at line 169 — it is a separate request, unaffected.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/internal.py
git commit -m "fix(internal): commit event before broadcast and response"
```

---

### Task 2: Move notification delivery off the ingestion path

**Files:**
- Create: `backend/app/schemas/notification_job.py`
- Create: `backend/app/services/notification_queue.py`
- Modify: `backend/app/services/alert_service.py:18-61`
- Modify: `backend/app/api/internal.py` (enqueue after commit)
- Modify: `backend/app/main.py` (start the consumer in lifespan)

**Interfaces:**
- Consumes: Task 1's explicit `await db.commit()` in `ingest_event`.
- Produces:
  - `NotificationJob` (pydantic): `history_id: str, org_id: str, event_id: str, rule_id: str | None, channel: str, recipient: str, webhook_url: str | None`
  - `alert_service.evaluate_event(event, db) -> list[NotificationJob]` — **return type changes from `int`**
  - `enqueue_notifications(jobs: list[NotificationJob]) -> None`
  - `run_notification_consumer(stop_event: asyncio.Event) -> None`

- [ ] **Step 1: Find every caller of `evaluate_event` before changing its return type**

```bash
cd backend && grep -rn "evaluate_event" app/
```

Expected: `app/services/alert_service.py` (definition) and `app/api/internal.py` (one call). If any other caller appears, it must be updated in this task too — a caller expecting an `int` will silently start truthy-testing a list.

- [ ] **Step 2: Create the job envelope**

`backend/app/schemas/notification_job.py`:

```python
"""The envelope for one queued notification delivery.

Carries `history_id` rather than the AlertHistory object because the consumer
runs in a different session — and often a different process — from the request
that queued it. The row is the handoff; the queue is only a pointer to it.
"""
from pydantic import BaseModel


class NotificationJob(BaseModel):
    history_id: str
    org_id: str
    event_id: str
    rule_id: str | None = None
    channel: str
    recipient: str
    webhook_url: str | None = None
```

- [ ] **Step 3: Stop `evaluate_event` from sending**

In `backend/app/services/alert_service.py`, change the signature and body. Replace lines 18-61 with:

```python
    async def evaluate_event(self, event: Event, db: AsyncSession) -> list[NotificationJob]:
        """Decide what to send. Does not send.

        Delivery is a network call to Gupshup/SMTP/a customer webhook, and it
        used to run inline inside the ingestion request — so a slow webhook
        made the edge box's event POST slow, and a hung one held a database
        transaction open. This now writes a `queued` AlertHistory row and
        hands the actual delivery to `run_notification_consumer`.
        """
        result = await db.execute(
            select(AlertRule).where(
                AlertRule.org_id == event.org_id,
                AlertRule.enabled == True,
                AlertRule.deleted_at.is_(None),
            )
        )
        rules = result.scalars().all()
        jobs: list[NotificationJob] = []

        redis_client = await get_redis()

        for rule in rules:
            if not self._matches(rule, event):
                continue

            if await self._is_in_cooldown(redis_client, rule, event):
                continue

            for contact in rule.notify_contacts:
                history = AlertHistory(
                    org_id=event.org_id,
                    rule_id=rule.id,
                    event_id=event.id,
                    channel=contact["type"],
                    recipient=contact["value"],
                    status="queued",
                )
                db.add(history)
                await db.flush()
                jobs.append(
                    NotificationJob(
                        history_id=str(history.id),
                        org_id=str(event.org_id),
                        event_id=str(event.id),
                        rule_id=str(rule.id),
                        channel=contact["type"],
                        recipient=contact["value"],
                        webhook_url=rule.webhook_url,
                    )
                )

            await self._set_cooldown(redis_client, rule, event)

        await db.flush()
        return jobs
```

Add the import at the top of the file:

```python
from app.schemas.notification_job import NotificationJob
```

- [ ] **Step 4: Widen the `AlertHistory.status` comment**

`backend/app/models/alert_history.py:26` — update the trailing comment so the new value is documented:

```python
    status: Mapped[str] = mapped_column(String(20), default="sent")  # queued, sent, delivered, failed
```

There is no CHECK constraint on this column, so no migration is needed. Verify:

```bash
cd backend && grep -rn "alert_history" alembic/versions/ | grep -i "check"
```

Expected: no output.

- [ ] **Step 5: Create the queue and consumer**

`backend/app/services/notification_queue.py`:

```python
"""Notification delivery, decoupled from event ingestion.

A Redis list is the queue. It is deliberately not a durable job system: the
`AlertHistory` row (status `queued`) is the durable record, so a job lost to a
Redis restart is visible as a stuck `queued` row rather than a silent drop.
"""
import asyncio
import logging

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.models.alert_history import AlertHistory
from app.models.alert_rule import AlertRule
from app.models.event import Event
from app.schemas.notification_job import NotificationJob
from app.services.notification_service import notification_service

logger = logging.getLogger(__name__)

NOTIFICATION_QUEUE_KEY = "nightwatch:notifications"
# Long enough that a brief backend restart does not drop pending sends, short
# enough that a queue nobody is draining does not grow without bound.
NOTIFICATION_QUEUE_TTL_SECONDS = 3600


async def enqueue_notifications(jobs: list[NotificationJob]) -> None:
    if not jobs:
        return
    r = await get_redis()
    await r.rpush(NOTIFICATION_QUEUE_KEY, *[j.model_dump_json() for j in jobs])
    await r.expire(NOTIFICATION_QUEUE_KEY, NOTIFICATION_QUEUE_TTL_SECONDS)


async def _deliver(job: NotificationJob) -> None:
    async with async_session_factory() as db:
        event = (
            await db.execute(select(Event).where(Event.id == job.event_id))
        ).scalar_one_or_none()
        if event is None:
            # The only way to get here is a queued job for an event that was
            # never committed — which Task 1 made impossible — or a purged
            # event. Either way there is nothing to send about.
            logger.warning("notification job for missing event %s", job.event_id)
            return

        rule = None
        if job.rule_id:
            rule = (
                await db.execute(select(AlertRule).where(AlertRule.id == job.rule_id))
            ).scalar_one_or_none()

        success = await notification_service.send(
            channel=job.channel,
            recipient=job.recipient,
            event=event,
            rule=rule,
            webhook_url=job.webhook_url,
        )

        history = (
            await db.execute(
                select(AlertHistory).where(AlertHistory.id == job.history_id)
            )
        ).scalar_one_or_none()
        if history is not None:
            history.status = "sent" if success else "failed"
        await db.commit()


async def run_notification_consumer(stop_event: asyncio.Event) -> None:
    """Drain the queue until asked to stop. One delivery at a time.

    Serial delivery is intentional for now: the previous behaviour was serial
    too (inline in the request), so this changes latency ownership without also
    changing the load an org's WhatsApp/SMTP provider sees.
    """
    logger.info("notification consumer started")
    while not stop_event.is_set():
        try:
            r = await get_redis()
            item = await r.blpop(NOTIFICATION_QUEUE_KEY, timeout=5)
            if item is None:
                continue
            job = NotificationJob.model_validate_json(item[1])
            await _deliver(job)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("notification consumer iteration failed")
            await asyncio.sleep(1)
    logger.info("notification consumer stopped")
```

- [ ] **Step 6: Enqueue from `ingest_event`, after the commit**

In `backend/app/api/internal.py`, add the import:

```python
from app.services.notification_queue import enqueue_notifications
```

Change the `evaluate_event` line to keep the jobs:

```python
    notification_jobs = await alert_service.evaluate_event(event, db)
```

and immediately after the `try/except` around `db.commit()`, before the broadcast block:

```python
    await enqueue_notifications(notification_jobs)
```

and change the return to:

```python
    return {"event_id": event_id, "alerts_triggered": len(notification_jobs)}
```

- [ ] **Step 7: Start the consumer in lifespan**

In `backend/app/main.py`, inside `lifespan` (around line 112), after the scheduler block, add:

```python
    consumer_stop = asyncio.Event()
    app.state.consumer_stop = consumer_stop
    background_tasks = [asyncio.create_task(run_notification_consumer(consumer_stop))]
    app.state.background_tasks = background_tasks
```

and in the shutdown half (after the scheduler shutdown, around line 168):

```python
    consumer_stop.set()
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
```

Add the imports at the top:

```python
import asyncio
from app.services.notification_queue import run_notification_consumer
```

(If `asyncio` is already imported, do not import it twice.)

- [ ] **Step 8: Verify end to end**

```bash
cd backend && uv run python3 -c "from app.main import app; print('ok')"
```

Start the backend and watch for `notification consumer started` in the log. Post a real event that matches an enabled alert rule, then:

```bash
psql "$POSTGRES_URL" -c "select status, channel, recipient, sent_at from alert_history order by sent_at desc limit 5;"
```

Expected: the row appears as `queued` and flips to `sent` (or `failed`) within a few seconds — not instantly, which is the proof it left the request path.

Also confirm the queue drains rather than accumulating:

```bash
redis-cli -u "$REDIS_URL" llen nightwatch:notifications
```

Expected: `0` shortly after posting.

- [ ] **Step 9: Self-review**

- Does any code path still `await notification_service.send` inside a request? (`grep -rn "notification_service.send" backend/app/` — the escalation sweep at `app/services/alert_escalation.py` is a scheduled job, not a request, so it may stay; note whether it does.)
- If the consumer dies, what is visible? (Stuck `queued` rows — confirm that is true and not `sent`.)
- Is `org_id` on the job used for anything security-relevant? (It is not — delivery targets come from the rule. Confirm no code reads it as an authorization input.)

- [ ] **Step 10: Commit**

```bash
git add backend/app/schemas/notification_job.py backend/app/services/notification_queue.py backend/app/services/alert_service.py backend/app/models/alert_history.py backend/app/api/internal.py backend/app/main.py
git commit -m "fix(alerts): queue notification delivery instead of sending inline"
```

---

### Task 3: Redis pub/sub for WebSocket fan-out

**Files:**
- Modify: `backend/app/ws/events.py`
- Modify: `backend/app/api/internal.py` (switch to `publish_to_org`)
- Modify: `backend/app/services/digest/service.py:176`
- Modify: `backend/app/main.py` (start the subscriber)

**Interfaces:**
- Consumes: Task 2's `background_tasks` / `consumer_stop` pattern in lifespan.
- Produces:
  - `publish_to_org(org_id: str, data: dict) -> None` — publishes to Redis; the **only** function producers should call
  - `broadcast_to_org(org_id: str, data: dict) -> None` — unchanged signature, now local-socket delivery only, called by the subscriber
  - `run_ws_subscriber(stop_event: asyncio.Event) -> None`

**Why both functions:** per-subscriber site filtering (`Subscriber.may_see`) has to happen where the sockets are, which is per replica. So the message crosses replicas unfiltered and is filtered on arrival. Keeping the two names distinct makes it impossible to accidentally deliver locally-only from a producer.

- [ ] **Step 1: Add publish + subscriber to `backend/app/ws/events.py`**

Add at the top of the file:

```python
import asyncio
import json

from app.core.redis import get_redis
```

and after the existing `ConnectionManager` / `manager` definitions, add:

```python
# One channel for every org. Fan-out is cheap (each replica already filters
# per subscriber) and a channel-per-org would mean subscribing and
# unsubscribing on every socket connect, which is more moving parts for no
# gain at the fleet sizes this runs at.
WS_CHANNEL = "nightwatch:ws:events"


async def publish_to_org(org_id: str, data: dict) -> None:
    """Publish to every backend replica. Producers call this, not broadcast.

    The in-process `broadcast_to_org` only ever reached sockets attached to the
    replica that handled the request, so with more than one replica most
    dashboards silently missed most events. This makes delivery independent of
    which replica the producer happened to land on.
    """
    r = await get_redis()
    await r.publish(WS_CHANNEL, json.dumps({"org_id": org_id, "data": data}))


async def run_ws_subscriber(stop_event: asyncio.Event) -> None:
    """Receive published messages and hand them to this replica's sockets."""
    logger.info("ws subscriber started")
    while not stop_event.is_set():
        try:
            r = await get_redis()
            pubsub = r.pubsub()
            await pubsub.subscribe(WS_CHANNEL)
            try:
                while not stop_event.is_set():
                    msg = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=5
                    )
                    if msg is None:
                        continue
                    envelope = json.loads(msg["data"])
                    await manager.broadcast_to_org(
                        envelope["org_id"], envelope["data"]
                    )
            finally:
                await pubsub.unsubscribe(WS_CHANNEL)
                await pubsub.close()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("ws subscriber iteration failed")
            await asyncio.sleep(1)
    logger.info("ws subscriber stopped")
```

Leave the existing module-level `broadcast_to_org` helper exactly as it is — it is now the local-delivery leg.

- [ ] **Step 2: Point producers at `publish_to_org`**

In `backend/app/api/internal.py`, change the import to:

```python
from app.ws.events import publish_to_org
```

and both calls in `ingest_event` to `await publish_to_org(...)`.

In `backend/app/services/digest/service.py`, change the import on line 24 to `publish_to_org` and the call on line 176 to `await publish_to_org(...)`.

- [ ] **Step 3: Confirm no producer still calls the local function**

```bash
cd backend && grep -rn "broadcast_to_org" app/ | grep -v "app/ws/events.py"
```

Expected: no output.

- [ ] **Step 4: Start the subscriber in lifespan**

In `backend/app/main.py`, extend the `background_tasks` list from Task 2:

```python
    background_tasks = [
        asyncio.create_task(run_notification_consumer(consumer_stop)),
        asyncio.create_task(run_ws_subscriber(consumer_stop)),
    ]
```

Add the import:

```python
from app.ws.events import run_ws_subscriber
```

- [ ] **Step 5: Verify fan-out across two processes**

```bash
cd backend && uv run python3 -c "from app.main import app; print('ok')"
```

Run two backend instances on different ports:

```bash
cd backend && uv run uvicorn app.main:app --port 8080
```

```bash
cd backend && uv run uvicorn app.main:app --port 8081
```

Open a dashboard WebSocket against **8081**, then POST an event to **8080**. Expected: the `event.created` frame arrives on the 8081 socket. Before this task it would not have.

Also confirm site filtering still holds: connect as a user with a non-empty `sites_access` that excludes the event's site, and confirm no frame arrives.

- [ ] **Step 6: Self-review**

- Is the payload JSON-serializable in every producer? (`internal.py` uses `model_dump(mode="json")`; check the digest payload at `service.py:176` for `datetime` or `UUID` values that `json.dumps` would reject — if present, stringify them.)
- Does a Redis outage break event ingestion? (`publish_to_org` is inside the `try/except` in `ingest_event` — confirm it still is after the rename.)
- Does the subscriber leak a pubsub connection on repeated failures? (The `finally` unsubscribes and closes — confirm.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/ws/events.py backend/app/api/internal.py backend/app/services/digest/service.py backend/app/main.py
git commit -m "fix(ws): fan out event broadcasts over Redis pub/sub"
```

---

# Phase B — Enrichment layer (spec Layer 2)

A workflow cannot ask "is this a dock camera?" until cameras have roles, and Module 3.1 cannot compare quantities until the pipeline reports them. Spec Appendix A.4 records why the second half is needed at all.

---

### Task 4: `camera_role` on cameras

**Files:**
- Modify: `backend/app/models/camera.py:39` (after `sensitivity`)
- Create: `backend/alembic/versions/a1b2c3d4e5f6_camera_role.py`
- Modify: `backend/app/schemas/camera.py` (`CreateCameraRequest`, `UpdateCameraRequest`, `CameraResponse`)
- Modify: `backend/app/schemas/assignment.py` (`Assignment`)
- Modify: `backend/app/api/internal.py:140-153` (assignment construction)
- Modify: `frontend/src/types/index.ts` (`Camera`)

**Interfaces:**
- Consumes: nothing.
- Produces: `Camera.camera_role: str | None`, one of `dock`, `shelf`, `bin`, `floor`, `dispatch`, `packing`, `gate`, `other`, or `NULL`. `NULL` means "not classified", and every workflow module treats `NULL` as "this workflow does not apply" — never as a default role. Task 8's `dock_grn` module and Task 7's engine both read it.

**Why a closed enum with a CHECK constraint:** the same reasoning as `scene_type` in agentic setup. A free-text role means a typo (`"docks"`) silently disables a workflow with no error anywhere, and workflow selection is exactly where silence is most expensive.

- [ ] **Step 1: Add the column to the model**

In `backend/app/models/camera.py`, after the `sensitivity` line (line 39), add:

```python
    # What this camera watches, in business terms — the input the workflow
    # engine selects on. NULL means unclassified, which every workflow reads
    # as "does not apply". Deliberately separate from `enabled_events`: what
    # the vision model looks for and what the back office does with the
    # result are different decisions with different owners.
    camera_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
```

- [ ] **Step 2: Write the migration**

`backend/alembic/versions/a1b2c3d4e5f6_camera_role.py`:

```python
"""camera_role — what a camera watches, in business terms

Revision ID: a1b2c3d4e5f6
Revises: 80f8c57dc838
Create Date: 2026-08-26

Nullable with no default: every existing camera stays unclassified, and an
unclassified camera is invisible to every workflow. That is what makes the
whole workflow layer opt-in for existing orgs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "80f8c57dc838"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("camera_role", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        "ck_cameras_camera_role",
        "cameras",
        "camera_role IS NULL OR camera_role IN "
        "('dock','shelf','bin','floor','dispatch','packing','gate','other')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_cameras_camera_role", "cameras", type_="check")
    op.drop_column("cameras", "camera_role")
```

- [ ] **Step 3: Thread it through the schemas**

In `backend/app/schemas/camera.py`:

- `CreateCameraRequest`: add `camera_role: str | None = None`
- `UpdateCameraRequest`: add `camera_role: str | None = None`
- `CameraResponse`: add `camera_role: str | None = None`

In `backend/app/schemas/assignment.py`, add to `Assignment` after `sensitivity`:

```python
    camera_role: str | None = None
```

- [ ] **Step 4: Include it in the assignment payload**

In `backend/app/api/internal.py`, in the `Assignment(...)` construction (line ~140), add after `sensitivity=camera.sensitivity,`:

```python
            camera_role=camera.camera_role,
```

- [ ] **Step 5: Confirm the camera write paths carry it**

```bash
cd backend && grep -n "sensitivity" app/api/cameras.py
```

For every place `sensitivity` is read off a create/update request and assigned to the model, add the matching `camera_role` line. If the update handler uses `model_dump(exclude_unset=True)` and `setattr`, nothing more is needed — verify which it is and note it.

- [ ] **Step 6: Add the frontend type**

In `frontend/src/types/index.ts`, on the `Camera` interface add:

```ts
  camera_role?: "dock" | "shelf" | "bin" | "floor" | "dispatch" | "packing" | "gate" | "other" | null;
```

- [ ] **Step 7: Apply and verify**

```bash
cd backend && uv run alembic upgrade head
```

```bash
psql "$POSTGRES_URL" -c "\d cameras" | grep -i camera_role
```

Expected: the column exists.

Confirm the constraint actually rejects a bad value:

```bash
psql "$POSTGRES_URL" -c "update cameras set camera_role='docks' where id = (select id from cameras limit 1);"
```

Expected: `ERROR: new row for relation "cameras" violates check constraint "ck_cameras_camera_role"`.

Then set a real one and confirm it reaches the agent:

```bash
psql "$POSTGRES_URL" -c "update cameras set camera_role='dock' where id = (select id from cameras limit 1);"
curl -s localhost:8080/internal/assignments -H "X-Worker-Key: $WORKER_API_KEY" | python3 -m json.tool | grep -A1 camera_role
```

Expected: `"camera_role": "dock"` on that camera.

```bash
cd frontend && npm run build
```

Expected: build passes.

- [ ] **Step 8: Self-review**

- Does adding a nullable column with a CHECK lock the `cameras` table meaningfully? (On Postgres 12+, `ADD COLUMN ... NULL` is instant; the `CHECK` requires a full scan without `NOT VALID`. At current camera counts this is fine — note the size you saw. If `cameras` is large in production, the constraint should be added `NOT VALID` then `VALIDATE CONSTRAINT` separately.)
- Is `camera_role` writable by anyone who should not set it? (It goes through the same camera update route as `sensitivity` — same authorization, confirm.)
- Does the agent tolerate the new assignment field before Task 5 ships? (Pydantic on the backend, `dict.get` on the pipeline — confirm the pipeline does not use a strict schema that would reject an unknown key.)

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/camera.py backend/alembic/versions/a1b2c3d4e5f6_camera_role.py backend/app/schemas/camera.py backend/app/schemas/assignment.py backend/app/api/internal.py backend/app/api/cameras.py frontend/src/types/index.ts
git commit -m "feat(cameras): add camera_role for workflow selection"
```

---

### Task 5: Dock goods observation in the edge pipeline

**Files:**
- Modify: `agent/pipeline/models.py:5-45` (`CameraConfig`), `:57-63` (`DetectedEvent`)
- Modify: `agent/pipeline/prompt_builder.py`
- Modify: `agent/pipeline/gemini_client.py:268-274`
- Modify: `agent/pipeline/event_packager.py:59-71`

**Interfaces:**
- Consumes: Task 4's `camera_role` on the assignment payload.
- Produces: `Event.metadata_extra["goods"]` on events from `camera_role="dock"` cameras, shaped exactly:

```json
{"goods": {"carton_count": 12, "pallet_count": 2, "visible_refs": ["PO-4471"], "goods_confidence": 0.72}}
```

`carton_count` and `pallet_count` are integers or `null`. `visible_refs` is a possibly-empty list of strings read off labels/paperwork. `goods_confidence` is a float 0–1 **separate from the event confidence** — the model can be certain a delivery is happening and unsure how many cartons. Task 8's `dock_grn` module reads exactly these four keys and nothing else.

**Why this task exists:** spec Section 3.1 says the pallet/carton count is "existing Gemini Vision output". It is not — see spec Appendix A.4. The prompt has no goods fields and `event_packager` never sends `metadata_extra` at all. Without this task Module 3.1 has no observed quantity to compare against.

- [ ] **Step 1: Add the fields to the pipeline dataclasses**

In `agent/pipeline/models.py`, in `CameraConfig` after `sensitivity`:

```python
    # Mirrors Camera.camera_role from the backend. None = unclassified, which
    # means no role-specific prompt addendum and no goods reporting.
    camera_role: str | None = None
```

and in `from_assignment`, after `sensitivity=...`:

```python
            camera_role=a.get("camera_role"),
```

In `DetectedEvent`, after `bounding_boxes`:

```python
    # Role-specific structured observations, passed through to the backend as
    # `metadata_extra`. Empty for every camera without a role addendum, so the
    # existing event shape is unchanged for existing deployments.
    metadata: dict = field(default_factory=dict)
```

- [ ] **Step 2: Add the dock addendum to the prompt**

In `agent/pipeline/prompt_builder.py`, add above `class PromptBuilder`:

```python
DOCK_ADDENDUM = """

This camera watches a receiving dock. In ADDITION to the schema above, include
a top-level "goods" object:

  "goods": {{
    "carton_count": <int or null>,
    "pallet_count": <int or null>,
    "visible_refs": ["<any PO / delivery-challan / invoice number legible in the frame>"],
    "goods_confidence": <float 0.0-1.0>
  }}

Rules for "goods":
- Count only items being loaded or unloaded, not stock already stored on racks
- Use null, never 0, when you cannot see well enough to count
- "goods_confidence" is your certainty about the COUNTS, not about the event
- Read reference numbers only if actually legible. Never infer or complete a
  partially visible number — a wrong PO number silently matches the wrong
  document, which is worse than no match"""
```

and at the end of `PromptBuilder.build`, replace the bare `return SYSTEM_TEMPLATE.format(...)` with:

```python
        prompt = SYSTEM_TEMPLATE.format(
            camera_name=camera_config.name,
            site_name=camera_config.site_name,
            timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
            timezone=camera_config.timezone,
            enabled_events=", ".join(camera_config.enabled_events),
            zones_section=zones_section,
            sensitivity=camera_config.sensitivity,
        )
        if camera_config.camera_role == "dock":
            prompt += DOCK_ADDENDUM
        return prompt
```

Keep the existing keyword arguments exactly as they already appear in the file — the list above is illustrative of the call, not a replacement for whatever arguments are currently passed.

- [ ] **Step 3: Parse the goods block**

In `agent/pipeline/gemini_client.py`, inside `_parse_response`, before the `for event_data in data.get("events", []):` loop:

```python
        # "goods" is a sibling of "events", not a member of one — a frame has
        # one goods observation regardless of how many events it produced.
        goods = data.get("goods")
        metadata = {}
        if isinstance(goods, dict):
            refs = goods.get("visible_refs") or []
            metadata["goods"] = {
                "carton_count": goods.get("carton_count"),
                "pallet_count": goods.get("pallet_count"),
                "visible_refs": [str(r) for r in refs if r][:10],
                "goods_confidence": float(goods.get("goods_confidence") or 0.0),
            }
```

and in the `DetectedEvent(...)` construction, add:

```python
                metadata=dict(metadata),
```

`dict(metadata)` rather than `metadata` so two events parsed from one frame do not share a mutable dict.

- [ ] **Step 4: Post it to the backend**

In `agent/pipeline/event_packager.py`, in the `self.api.post_event({...})` payload, after `"ai_model": config.gemini_model,`:

```python
            "metadata_extra": event.metadata,
```

- [ ] **Step 5: Verify the prompt and the parse without a camera**

```bash
cd agent/pipeline && python3 -c "
from models import CameraConfig
from prompt_builder import PromptBuilder
c = CameraConfig(camera_id='x', org_id='y', name='Dock 1', ingest_mode='rtsp_pull', camera_role='dock')
p = PromptBuilder().build(c)
assert 'goods' in p, 'dock addendum missing'
c2 = CameraConfig(camera_id='x', org_id='y', name='Lobby', ingest_mode='rtsp_pull')
assert 'goods' not in PromptBuilder().build(c2), 'addendum leaked to non-dock camera'
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 6: Verify end to end against a real stream**

Follow the local RTSP setup already used for the supervision refactor (`mediamtx` plus a looped clip — see `docs/superpowers/plans/2026-08-21-supervision-tracking-refactor.md`). Set that camera's `camera_role='dock'`, run the pipeline, and after an event fires:

```bash
psql "$POSTGRES_URL" -c "select event_type, metadata_extra from events order by created_at desc limit 3;"
```

Expected: `metadata_extra` contains a `goods` object on dock-camera events and is `{}` on others.

- [ ] **Step 7: Self-review**

- Does a non-dock camera's payload change at all? (It should be byte-identical apart from `"metadata_extra": {}` — confirm the backend treats that the same as absent.)
- Does `_load_camera_configs()` in `agent/pipeline/supervisor.py` (the local `cameras.json` cold-start fallback) pass `camera_role` through? This fallback has silently dropped config fields before — that exact bug was found and fixed for `counting_lines`/`step_sequence`. Check it and fix it here if not.
- Is `goods_confidence` ever conflated with event confidence anywhere downstream? (It must not be — they answer different questions.)
- Does a model returning `"carton_count": 0` instead of `null` change the meaning? (Yes, badly — `0` means "I counted zero", `null` means "I couldn't count". The prompt says so; confirm the parser does not coerce one to the other.)

- [ ] **Step 8: Commit**

```bash
git add agent/pipeline/models.py agent/pipeline/prompt_builder.py agent/pipeline/gemini_client.py agent/pipeline/event_packager.py agent/pipeline/supervisor.py
git commit -m "feat(pipeline): report dock goods observations in metadata_extra"
```

---

# Phase C — Workflow layer (spec Layers 3 and 5)

---

### Task 6: Workflow data model

**Files:**
- Create: `backend/app/models/workflow.py`
- Create: `backend/alembic/versions/b2c3d4e5f6a7_workflow_tables.py`
- Modify: `backend/app/models/__init__.py`

**Interfaces:**
- Consumes: Task 4's `camera_role` (indirectly — rules select cameras by role at evaluation time, not by FK).
- Produces four models. Later tasks depend on these exact attribute names:
  - `WorkflowRule`: `id, org_id, site_id, workflow_type, config, enabled, created_at, updated_at`
  - `ExpectedDocument`: `id, org_id, site_id, source, doc_type, external_ref, payload, doc_date, status, synced_at`
  - `WorkflowException`: `id, org_id, site_id, event_id, workflow_rule_id, workflow_type, status, matched_document_id, discrepancy, draft, note, created_at, resolved_at, resolved_by`
  - `ConnectorSyncLog`: `id, org_id, connector, status, records_pulled, error, run_at`

**Design notes to preserve in the code comments:**
- `workflow_type` and `doc_type` carry the full Phase 2/3 enum values now. The CHECK constraint is the cheap part; a second migration to widen it later is the expensive part.
- `WorkflowException.draft` is separate from `discrepancy`. `discrepancy` is "what disagreed"; `draft` is "the GRN we would write". Spec Section 7 forbids writing the draft anywhere, so it lives in the exception row and nowhere else.
- `unique(site_id, workflow_type)` on `workflow_rules` — one configuration of a workflow per site. Two enabled `dock_grn_match` rules for one site would produce two exceptions per event with no way to say which is authoritative.
- `unique(org_id, source, doc_type, external_ref)` on `expected_documents` — the connector re-pulls overlapping windows every 15 minutes, so upsert-by-natural-key is what keeps a re-sync from duplicating every open PO.

- [ ] **Step 1: Write the models**

`backend/app/models/workflow.py`:

```python
"""The workflow / exception layer: rules, synced documents, exceptions, sync log.

This is the "Camera-to-Books" layer. A camera event is compared against a
document pulled from the customer's system of record, and the comparison
produces either an auto-cleared draft or an exception a human resolves.

Nothing here writes to an external system. An `auto_cleared` exception is a
draft awaiting human export, not a posted entry — see the spec's Section 7.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# The full Phase 1-3 set, declared up front. Widening a CHECK constraint later
# needs a migration; listing a value a module does not exist for yet costs
# nothing, because a rule can only be created through an API that validates
# against the registry of implemented modules.
WORKFLOW_TYPES = (
    "dock_grn_match",
    "vendor_overbill_check",
    "backdoor_receiving",
    "material_issue_bom_check",
    "low_stock_procurement_trigger",
    "shelf_stock_level_estimate",
    "dispatch_order_verification",
    "freight_dock_scheduling",
    "vendor_scorecard_rollup",
    "demand_trend_feed",
)

DOC_TYPES = ("po", "grn", "invoice", "bom", "sales_order", "stock_on_hand")
EXCEPTION_STATUSES = ("open", "approved", "rejected", "auto_cleared")


def _sql_in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class WorkflowRule(Base):
    """One workflow, enabled and configured for one site.

    A site with no row for a workflow_type does not run that workflow. That is
    the entire opt-in mechanism — there is no global default and no implicit
    enablement anywhere.
    """

    __tablename__ = "workflow_rules"
    __table_args__ = (
        CheckConstraint(
            f"workflow_type IN ({_sql_in(WORKFLOW_TYPES)})",
            name="ck_workflow_rules_type",
        ),
        UniqueConstraint("site_id", "workflow_type", name="uq_workflow_rule_site_type"),
        Index("ix_workflow_rules_site_enabled", "site_id", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False
    )
    workflow_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # Per-workflow knobs. For dock_grn_match: {"quantity_tolerance_pct": 5,
    # "match_window_hours": 24, "min_goods_confidence": 0.5}.
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ExpectedDocument(Base):
    """A document pulled from the customer's system of record.

    Read-only mirror. Nothing in NightWatch edits these; the connector owns
    every column, and a change made in Tally wins on the next sync.
    """

    __tablename__ = "expected_documents"
    __table_args__ = (
        CheckConstraint("source IN ('tally','manual')", name="ck_expected_documents_source"),
        CheckConstraint(
            f"doc_type IN ({_sql_in(DOC_TYPES)})", name="ck_expected_documents_type"
        ),
        UniqueConstraint(
            "org_id", "source", "doc_type", "external_ref", name="uq_expected_document_ref"
        ),
        # The matching query: open documents of a type, for a site, in a date
        # window. This index is what keeps that lookup off a sequential scan
        # once an org has a year of purchase orders.
        Index("ix_expected_documents_lookup", "site_id", "doc_type", "status", "doc_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    # Nullable: Tally has no concept of a NightWatch site, so a document is
    # only site-attributed when the org maps one. An unattributed document is
    # matchable org-wide.
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # The identifier a human would read off the paperwork: "PO-4471".
    external_ref: Mapped[str] = mapped_column(Text, nullable=False)
    # The parsed document, stored whole. Modules read named keys out of it;
    # storing it verbatim means a module added later does not need a re-sync.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    doc_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "open" / "closed" as reported by the source system.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WorkflowException(Base):
    """One workflow's verdict on one event.

    Rows are written for `auto_cleared` as well as `open`, because "the camera
    and the paperwork agreed" is the answer to an audit question and needs to
    survive as a record, not just as the absence of an exception.
    """

    __tablename__ = "workflow_exceptions"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_sql_in(EXCEPTION_STATUSES)})", name="ck_workflow_exceptions_status"
        ),
        CheckConstraint(
            f"workflow_type IN ({_sql_in(WORKFLOW_TYPES)})",
            name="ck_workflow_exceptions_type",
        ),
        # One verdict per (event, workflow). Re-evaluating an event — a retried
        # queue job, a redelivered message — must update, never duplicate.
        UniqueConstraint("event_id", "workflow_type", name="uq_workflow_exception_event_type"),
        Index("ix_workflow_exceptions_queue", "site_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id"), nullable=False
    )
    # Nullable so an exception survives the deletion of the rule that made it.
    # The verdict is a historical fact; the rule is current configuration.
    workflow_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_rules.id", ondelete="SET NULL"), nullable=True
    )
    workflow_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    matched_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("expected_documents.id"), nullable=True
    )
    # What disagreed: {"field": "quantity", "expected": 20, "observed": 12, ...}
    discrepancy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # What we WOULD write, if a human exports it. Never posted anywhere.
    draft: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class ConnectorSyncLog(Base):
    """One connector run. The answer to "is our Tally data stale?"."""

    __tablename__ = "connector_sync_log"
    __table_args__ = (
        CheckConstraint("connector IN ('tally')", name="ck_connector_sync_log_connector"),
        CheckConstraint("status IN ('ok','error')", name="ck_connector_sync_log_status"),
        Index("ix_connector_sync_log_org_run", "org_id", "run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    connector: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    records_pulled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 2: Register the models**

In `backend/app/models/__init__.py`, add the import after the `Proposal` import:

```python
from app.models.workflow import (
    ConnectorSyncLog,
    ExpectedDocument,
    WorkflowException,
    WorkflowRule,
)
```

and add `"WorkflowRule"`, `"ExpectedDocument"`, `"WorkflowException"`, `"ConnectorSyncLog"` to `__all__`.

- [ ] **Step 3: Write the migration**

`backend/alembic/versions/b2c3d4e5f6a7_workflow_tables.py`:

```python
"""workflow layer — rules, expected documents, exceptions, connector sync log

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-26

Purely additive. No existing table is altered, and no org runs any workflow
until a workflow_rules row exists for one of its sites.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WORKFLOW_TYPES_SQL = (
    "'dock_grn_match','vendor_overbill_check','backdoor_receiving',"
    "'material_issue_bom_check','low_stock_procurement_trigger',"
    "'shelf_stock_level_estimate','dispatch_order_verification',"
    "'freight_dock_scheduling','vendor_scorecard_rollup','demand_trend_feed'"
)
DOC_TYPES_SQL = "'po','grn','invoice','bom','sales_order','stock_on_hand'"


def upgrade() -> None:
    op.create_table(
        "workflow_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("workflow_type", sa.String(length=40), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_workflow_rules_type", "workflow_rules", f"workflow_type IN ({WORKFLOW_TYPES_SQL})"
    )
    op.create_unique_constraint(
        "uq_workflow_rule_site_type", "workflow_rules", ["site_id", "workflow_type"]
    )
    op.create_index("ix_workflow_rules_site_enabled", "workflow_rules", ["site_id", "enabled"])

    op.create_table(
        "expected_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("doc_type", sa.String(length=20), nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("doc_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_expected_documents_source", "expected_documents", "source IN ('tally','manual')"
    )
    op.create_check_constraint(
        "ck_expected_documents_type", "expected_documents", f"doc_type IN ({DOC_TYPES_SQL})"
    )
    op.create_unique_constraint(
        "uq_expected_document_ref",
        "expected_documents",
        ["org_id", "source", "doc_type", "external_ref"],
    )
    op.create_index(
        "ix_expected_documents_lookup",
        "expected_documents",
        ["site_id", "doc_type", "status", "doc_date"],
    )

    op.create_table(
        "workflow_exceptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id"), nullable=False),
        sa.Column(
            "workflow_rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("workflow_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column(
            "matched_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("expected_documents.id"),
            nullable=True,
        ),
        sa.Column("discrepancy", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("draft", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_check_constraint(
        "ck_workflow_exceptions_status",
        "workflow_exceptions",
        "status IN ('open','approved','rejected','auto_cleared')",
    )
    op.create_check_constraint(
        "ck_workflow_exceptions_type",
        "workflow_exceptions",
        f"workflow_type IN ({WORKFLOW_TYPES_SQL})",
    )
    op.create_unique_constraint(
        "uq_workflow_exception_event_type", "workflow_exceptions", ["event_id", "workflow_type"]
    )
    op.create_index(
        "ix_workflow_exceptions_queue", "workflow_exceptions", ["site_id", "status", "created_at"]
    )

    op.create_table(
        "connector_sync_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("connector", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("records_pulled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("run_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_connector_sync_log_connector", "connector_sync_log", "connector IN ('tally')"
    )
    op.create_check_constraint(
        "ck_connector_sync_log_status", "connector_sync_log", "status IN ('ok','error')"
    )
    op.create_index("ix_connector_sync_log_org_run", "connector_sync_log", ["org_id", "run_at"])


def downgrade() -> None:
    op.drop_table("connector_sync_log")
    op.drop_table("workflow_exceptions")
    op.drop_table("expected_documents")
    op.drop_table("workflow_rules")
```

- [ ] **Step 4: Apply and verify**

```bash
cd backend && uv run alembic upgrade head && uv run python3 -c "from app.main import app; print('ok')"
```

```bash
psql "$POSTGRES_URL" -c "\dt workflow_rules" -c "\dt expected_documents" -c "\dt workflow_exceptions" -c "\dt connector_sync_log"
```

Expected: all four tables listed.

Confirm there is still exactly one alembic head:

```bash
cd backend && uv run alembic heads
```

Expected: one line, `b2c3d4e5f6a7 (head)`.

- [ ] **Step 5: Self-review**

- Does `downgrade()` drop in FK-safe order? (Children before parents — `workflow_exceptions` references both `workflow_rules` and `expected_documents`, so it must drop first. Confirm the order above is right.)
- Is `org_id` on every new table, and is `site_id` non-nullable everywhere a site is genuinely knowable? (It is nullable only on `expected_documents`, for the documented reason.)
- Does the `uq_workflow_exception_event_type` constraint make re-evaluation safe, or will it raise on the second run? (It will raise unless Task 7's engine upserts — note this and make sure Task 7 handles it.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/workflow.py backend/app/models/__init__.py backend/alembic/versions/b2c3d4e5f6a7_workflow_tables.py
git commit -m "feat(workflows): add workflow rules, expected documents, exceptions, sync log"
```

---

### Task 7: Workflow engine and post-commit job queue

**Files:**
- Create: `backend/app/services/workflows/__init__.py`
- Create: `backend/app/services/workflows/outcome.py`
- Create: `backend/app/services/workflows/engine.py`
- Create: `backend/app/services/workflows/queue.py`
- Modify: `backend/app/api/internal.py` (enqueue after commit)
- Modify: `backend/app/main.py` (start the workflow consumer)

**Interfaces:**
- Consumes: Task 1's explicit commit; Task 2's consumer/lifespan pattern; Task 6's four models.
- Produces:
  - `WorkflowOutcome` (dataclass): `verdict: Literal["match","exception","ignore"], matched_document_id: uuid.UUID | None = None, discrepancy: dict = {}, draft: dict = {}`
  - `MODULES: dict[str, WorkflowModule]` in `services/workflows/__init__.py`, where `WorkflowModule` is `Callable[[Event, Camera, WorkflowRule, AsyncSession], Awaitable[WorkflowOutcome]]`
  - `register(workflow_type: str)` — decorator used by Task 8
  - `evaluate_event_workflows(event_id: uuid.UUID, db: AsyncSession) -> int` — returns exceptions written
  - `enqueue_workflow_job(event_id: str) -> None`
  - `run_workflow_consumer(stop_event: asyncio.Event) -> None`

**Why off the request path:** a workflow reads Postgres, may read `expected_documents` across a date range, and will eventually call a connector. Running that inside `ingest_event` would put back-office latency on the edge box's event POST — which is the exact problem Task 2 just removed for notifications. Running it in a *separate session after commit* also means a workflow bug can never roll back an event.

**Why the module signature takes the `Camera`:** `camera_role` is the primary selector for every camera-native module, and re-querying the camera in each module would be N+1 across a batch. The engine loads it once.

- [ ] **Step 1: The outcome type**

`backend/app/services/workflows/outcome.py`:

```python
"""The single shape every workflow module returns.

Three verdicts, deliberately:

* `ignore` — this workflow has nothing to say about this event. No row.
* `match`  — the camera and the paperwork agreed. Row written `auto_cleared`,
             carrying the draft a human may export.
* `exception` — they disagreed, or the paperwork is missing. Row written
             `open`, carrying the discrepancy.

`match` writes a row rather than staying silent because "we checked and it was
fine" is itself the audit answer. A missing row would be indistinguishable from
"the workflow never ran".
"""
import uuid
from dataclasses import dataclass, field
from typing import Literal

Verdict = Literal["match", "exception", "ignore"]


@dataclass
class WorkflowOutcome:
    verdict: Verdict
    matched_document_id: uuid.UUID | None = None
    # What disagreed. Empty for `match`.
    discrepancy: dict = field(default_factory=dict)
    # What we would write into the books, if a human exports it. Never posted.
    draft: dict = field(default_factory=dict)

    @classmethod
    def ignore(cls) -> "WorkflowOutcome":
        return cls(verdict="ignore")
```

- [ ] **Step 2: The registry**

`backend/app/services/workflows/__init__.py`:

```python
"""Registry of implemented workflow modules.

The database CHECK constraint lists every workflow_type in the roadmap; this
dict lists the ones that actually exist. The rules API validates against THIS,
so an operator cannot enable a workflow that has no code behind it and then
wonder why nothing happens.

Deliberately not a generic rule DSL. Each module is hardcoded Python. The
shared shape gets extracted once several modules exist and have shown what is
genuinely common — not before.
"""
import uuid
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.models.event import Event
from app.models.workflow import WorkflowRule
from app.services.workflows.outcome import WorkflowOutcome

WorkflowModule = Callable[
    [Event, Camera, WorkflowRule, AsyncSession], Awaitable[WorkflowOutcome]
]

MODULES: dict[str, WorkflowModule] = {}


def register(workflow_type: str):
    def decorator(fn: WorkflowModule) -> WorkflowModule:
        MODULES[workflow_type] = fn
        return fn

    return decorator


def implemented_types() -> list[str]:
    return sorted(MODULES)


# Import modules for their side effect of registering. Keep at the bottom:
# they import `register` from this module.
from app.services.workflows import dock_grn  # noqa: E402,F401
```

Note: `dock_grn` does not exist until Task 8. Until then, comment out that last import line and leave a `# TODO(Task 8)` — this is the one place the plan permits a temporary stub, because the alternative is a task that cannot be run at all. Task 8's first step uncomments it.

- [ ] **Step 3: The engine**

`backend/app/services/workflows/engine.py`:

```python
"""Runs every enabled workflow for one committed event.

Called only from the workflow consumer, never from a request. The event is
already durable by the time this runs — see `ingest_event`.
"""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.models.event import Event
from app.models.workflow import WorkflowException, WorkflowRule
from app.services.workflows import MODULES

logger = logging.getLogger(__name__)


async def evaluate_event_workflows(event_id: uuid.UUID, db: AsyncSession) -> int:
    """Evaluate every enabled workflow for this event's site. Returns rows written."""
    event = (
        await db.execute(select(Event).where(Event.id == event_id))
    ).scalar_one_or_none()
    if event is None:
        # Only reachable if the event was purged between enqueue and drain.
        logger.warning("workflow job for missing event %s", event_id)
        return 0

    rules = (
        await db.execute(
            select(WorkflowRule).where(
                WorkflowRule.site_id == event.site_id,
                WorkflowRule.enabled.is_(True),
            )
        )
    ).scalars().all()
    if not rules:
        return 0

    camera = (
        await db.execute(select(Camera).where(Camera.id == event.camera_id))
    ).scalar_one_or_none()
    if camera is None:
        logger.warning("workflow job for event %s with missing camera", event_id)
        return 0

    written = 0
    for rule in rules:
        module = MODULES.get(rule.workflow_type)
        if module is None:
            # A rule for a workflow whose code was removed or not yet shipped.
            # Silence is correct here: the rules API refuses to create these,
            # so this only happens across a rollback of a module.
            continue

        try:
            outcome = await module(event, camera, rule, db)
        except Exception:  # noqa: BLE001
            # One broken module must not stop the others, and must never make
            # the event look unprocessed. Log loudly, skip, continue.
            logger.exception(
                "workflow %s failed for event %s", rule.workflow_type, event_id
            )
            continue

        if outcome.verdict == "ignore":
            continue

        if await _upsert_exception(event, rule, outcome, db):
            written += 1

    await db.commit()
    return written


async def _upsert_exception(event, rule, outcome, db: AsyncSession) -> bool:
    """Write or refresh the verdict. Never duplicates, never overwrites a human.

    `uq_workflow_exception_event_type` makes a second evaluation of the same
    event a constraint violation rather than a duplicate — but a redelivered
    queue message is normal, so this updates instead. A row a human has already
    resolved is left completely alone: re-running the matcher must not silently
    reopen or re-clear something someone signed off on.
    """
    existing = (
        await db.execute(
            select(WorkflowException).where(
                WorkflowException.event_id == event.id,
                WorkflowException.workflow_type == rule.workflow_type,
            )
        )
    ).scalar_one_or_none()

    status = "auto_cleared" if outcome.verdict == "match" else "open"

    if existing is not None:
        if existing.status in ("approved", "rejected"):
            return False
        existing.status = status
        existing.workflow_rule_id = rule.id
        existing.matched_document_id = outcome.matched_document_id
        existing.discrepancy = outcome.discrepancy
        existing.draft = outcome.draft
        return False

    db.add(
        WorkflowException(
            org_id=event.org_id,
            site_id=event.site_id,
            event_id=event.id,
            workflow_rule_id=rule.id,
            workflow_type=rule.workflow_type,
            status=status,
            matched_document_id=outcome.matched_document_id,
            discrepancy=outcome.discrepancy,
            draft=outcome.draft,
        )
    )
    return True
```

- [ ] **Step 4: The queue**

`backend/app/services/workflows/queue.py`:

```python
"""Post-commit workflow evaluation queue.

Same shape as the notification queue and for the same reason: the work is
slow, it must not be inside the ingestion request, and it must not run until
the event is durable.
"""
import asyncio
import logging
import uuid

from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.services.workflows.engine import evaluate_event_workflows

logger = logging.getLogger(__name__)

WORKFLOW_QUEUE_KEY = "nightwatch:workflow_jobs"
WORKFLOW_QUEUE_TTL_SECONDS = 3600


async def enqueue_workflow_job(event_id: str) -> None:
    r = await get_redis()
    await r.rpush(WORKFLOW_QUEUE_KEY, event_id)
    await r.expire(WORKFLOW_QUEUE_KEY, WORKFLOW_QUEUE_TTL_SECONDS)


async def run_workflow_consumer(stop_event: asyncio.Event) -> None:
    logger.info("workflow consumer started")
    while not stop_event.is_set():
        try:
            r = await get_redis()
            item = await r.blpop(WORKFLOW_QUEUE_KEY, timeout=5)
            if item is None:
                continue
            event_id = uuid.UUID(item[1])
            async with async_session_factory() as db:
                written = await evaluate_event_workflows(event_id, db)
            if written:
                logger.info("wrote %d workflow exception(s) for event %s", written, event_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("workflow consumer iteration failed")
            await asyncio.sleep(1)
    logger.info("workflow consumer stopped")
```

- [ ] **Step 5: Enqueue after the commit**

In `backend/app/api/internal.py`, add the import:

```python
from app.services.workflows.queue import enqueue_workflow_job
```

and inside the same `try/except` that wraps the broadcast, so a Redis outage degrades workflows and live updates rather than failing an ingestion whose event is already persisted:

```python
    try:
        await enqueue_workflow_job(event_id)
        message = {"type": "event.created", "event": payload}
        await broadcast_to_org(org_id, message)
        await broadcast_to_org("all", message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("post-commit fan-out failed for event %s: %s", event_id, exc)
```

(After Task 3 the two `broadcast_to_org` calls are `publish_to_org`. If Task 3 is already done, use those names.)

`enqueue_notifications` from Task 2 stays where it is, immediately after the commit and outside this block — a lost alert is a different severity from a lost workflow evaluation, and it should surface as an error rather than a warning.
- [ ] **Step 6: Start the consumer**

In `backend/app/main.py`, add to `background_tasks`:

```python
        asyncio.create_task(run_workflow_consumer(consumer_stop)),
```

and the import:

```python
from app.services.workflows.queue import run_workflow_consumer
```

- [ ] **Step 7: Verify the no-op path**

```bash
cd backend && uv run python3 -c "from app.main import app; print('ok')"
```

Start the backend, confirm `workflow consumer started` appears, POST an event for a site with no `workflow_rules` row, and confirm:

```bash
redis-cli -u "$REDIS_URL" llen nightwatch:workflow_jobs
psql "$POSTGRES_URL" -c "select count(*) from workflow_exceptions;"
```

Expected: queue length `0` (drained), exception count `0`. This is the "off by default" guarantee — an org with no rules gets a drained queue and no rows.

- [ ] **Step 8: Self-review**

- Does the consumer use its own session, separate from the request's? (It must — confirm `async_session_factory()` and not a passed-in session.)
- Can a workflow exception ever prevent an event from being returned to the edge box? (Step 5 puts the enqueue inside the broadcast's `try/except` — re-read it and confirm no `await` between the commit and the `return` can escape as a 5xx on a persisted event.)
- Does `_upsert_exception` respect a human decision on redelivery? (Yes for `approved`/`rejected`. Consider: should an `auto_cleared` row a human has *seen* be silently re-cleared? Note your reasoning.)
- Is `evaluate_event_workflows` scoped correctly? (It loads rules by `event.site_id`, which comes from the camera, which came from an authenticated agent. There is no user input in this path at all — confirm.)

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/workflows/ backend/app/api/internal.py backend/app/main.py
git commit -m "feat(workflows): add workflow engine and post-commit evaluation queue"
```

---

### Task 8: Module 3.1 — Dock GRN auto-match

**Files:**
- Create: `backend/app/services/workflows/dock_grn.py`
- Modify: `backend/app/services/workflows/__init__.py` (uncomment the import from Task 7 Step 2)

**Interfaces:**
- Consumes: Task 5's `metadata_extra["goods"]`; Task 6's `ExpectedDocument`; Task 7's `register` / `WorkflowOutcome`.
- Produces: a registered module under `"dock_grn_match"`. Its `config` keys, which Task 10's rules API validates and Task 11's settings UI edits:
  - `quantity_tolerance_pct: float` (default `5.0`)
  - `match_window_hours: int` (default `24`)
  - `min_goods_confidence: float` (default `0.5`)

**The matching rule, stated once so the code and the UI cannot drift:**

1. Ignore unless `camera.camera_role == "dock"`.
2. Ignore unless the event carries a `goods` block with `goods_confidence >= min_goods_confidence` and at least one of `carton_count` / `pallet_count` that is not `None`.
3. Candidate documents: `ExpectedDocument` with `doc_type in ("po","grn")`, `status == "open"`, same `org_id`, `site_id` either matching the event's site or `NULL`, and `doc_date` within `match_window_hours` of the event.
4. If the goods block has `visible_refs`, prefer a candidate whose `external_ref` matches one (case-insensitive, whitespace-stripped). A ref match is decisive — if a ref matched, only that document is considered.
5. Otherwise, if exactly one candidate remains, use it. **If more than one remains and no ref matched, that is an exception, not a guess** — `discrepancy.reason = "ambiguous_document"` listing the candidates.
6. No candidates at all → exception, `reason = "no_matching_document"`. This is the back-door-receiving signal in miniature, and the spec's 3.3 will build on it.
7. With one document: compare observed cartons against `payload["expected_quantity"]`. Within tolerance → `match` with a draft GRN. Outside → `exception` with expected vs. observed.

**Why ambiguity is an exception rather than a best guess:** picking one of two open POs by proximity would produce a draft GRN against the wrong purchase order, and the whole point of a draft is that a human trusts it enough to key it in. A wrong match is worse than no match — the spec says as much about reference numbers, and it holds for documents too.

- [ ] **Step 1: Enable the registry import**

In `backend/app/services/workflows/__init__.py`, uncomment the bottom import:

```python
from app.services.workflows import dock_grn  # noqa: E402,F401
```

- [ ] **Step 2: Write the module**

`backend/app/services/workflows/dock_grn.py`:

```python
"""Module 3.1 — Dock GRN auto-match.

Compares what a dock camera saw arriving against the open purchase order or
GRN for that site, and produces either a draft goods-receipt note a human can
key in, or an exception describing exactly what disagreed.

Hardcoded on purpose. This is the first module; the shared shape gets factored
out once there are several to factor.

Nothing here writes to Tally. `auto_cleared` means "we checked and it matched,
here is the draft" — not "posted".
"""
import logging
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.models.event import Event
from app.models.workflow import ExpectedDocument, WorkflowRule
from app.services.workflows import register
from app.services.workflows.outcome import WorkflowOutcome

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE_PCT = 5.0
DEFAULT_WINDOW_HOURS = 24
DEFAULT_MIN_GOODS_CONFIDENCE = 0.5
# More candidates than this and listing them in the exception stops being
# useful to the human reading it; the message says "narrow the window".
MAX_LISTED_CANDIDATES = 10


def _normalise_ref(value: str) -> str:
    return "".join(str(value).split()).upper()


@register("dock_grn_match")
async def evaluate(
    event: Event, camera: Camera, rule: WorkflowRule, db: AsyncSession
) -> WorkflowOutcome:
    if camera.camera_role != "dock":
        return WorkflowOutcome.ignore()

    config = rule.config or {}
    tolerance_pct = float(config.get("quantity_tolerance_pct", DEFAULT_TOLERANCE_PCT))
    window_hours = int(config.get("match_window_hours", DEFAULT_WINDOW_HOURS))
    min_confidence = float(
        config.get("min_goods_confidence", DEFAULT_MIN_GOODS_CONFIDENCE)
    )

    goods = (event.metadata_extra or {}).get("goods")
    if not isinstance(goods, dict):
        return WorkflowOutcome.ignore()

    if float(goods.get("goods_confidence") or 0.0) < min_confidence:
        # The model saw a delivery but could not count it. Reporting a
        # discrepancy off an uncertain count would manufacture disputes.
        return WorkflowOutcome.ignore()

    carton_count = goods.get("carton_count")
    pallet_count = goods.get("pallet_count")
    if carton_count is None and pallet_count is None:
        return WorkflowOutcome.ignore()

    window_start = event.timestamp - timedelta(hours=window_hours)
    window_end = event.timestamp + timedelta(hours=window_hours)

    candidates = (
        await db.execute(
            select(ExpectedDocument).where(
                ExpectedDocument.org_id == event.org_id,
                ExpectedDocument.doc_type.in_(("po", "grn")),
                ExpectedDocument.status == "open",
                or_(
                    ExpectedDocument.site_id == event.site_id,
                    ExpectedDocument.site_id.is_(None),
                ),
                or_(
                    ExpectedDocument.doc_date.is_(None),
                    ExpectedDocument.doc_date.between(window_start, window_end),
                ),
            )
        )
    ).scalars().all()

    refs = {_normalise_ref(r) for r in (goods.get("visible_refs") or []) if r}
    if refs:
        by_ref = [d for d in candidates if _normalise_ref(d.external_ref) in refs]
        if by_ref:
            # A legible reference number beats every heuristic. If it matched
            # more than one document the source data is inconsistent, and that
            # is worth surfacing rather than resolving silently.
            candidates = by_ref

    if not candidates:
        return WorkflowOutcome(
            verdict="exception",
            discrepancy={
                "reason": "no_matching_document",
                "observed": {"carton_count": carton_count, "pallet_count": pallet_count},
                "visible_refs": sorted(refs),
                "window_hours": window_hours,
                "message": (
                    "Goods were observed at the dock with no open purchase order "
                    "or GRN for this site in the matching window."
                ),
            },
        )

    if len(candidates) > 1:
        return WorkflowOutcome(
            verdict="exception",
            discrepancy={
                "reason": "ambiguous_document",
                "observed": {"carton_count": carton_count, "pallet_count": pallet_count},
                "candidates": [
                    {
                        "id": str(d.id),
                        "external_ref": d.external_ref,
                        "doc_type": d.doc_type,
                        "doc_date": d.doc_date.isoformat() if d.doc_date else None,
                    }
                    for d in candidates[:MAX_LISTED_CANDIDATES]
                ],
                "candidate_count": len(candidates),
                "message": (
                    "More than one open document could match this delivery and no "
                    "reference number was legible. Pick the right one rather than "
                    "letting the system guess."
                ),
            },
        )

    document = candidates[0]
    expected_qty = document.payload.get("expected_quantity")

    if expected_qty is None:
        return WorkflowOutcome(
            verdict="exception",
            matched_document_id=document.id,
            discrepancy={
                "reason": "document_has_no_quantity",
                "observed": {"carton_count": carton_count, "pallet_count": pallet_count},
                "external_ref": document.external_ref,
                "message": (
                    "Matched a document that carries no expected quantity, so there "
                    "is nothing to compare against."
                ),
            },
        )

    observed_qty = carton_count if carton_count is not None else pallet_count
    expected_qty = float(expected_qty)
    # A zero-quantity document cannot have a percentage tolerance. Treat any
    # observed goods against it as a discrepancy rather than dividing by zero.
    if expected_qty == 0:
        variance_pct = 100.0 if observed_qty else 0.0
    else:
        variance_pct = abs(observed_qty - expected_qty) / expected_qty * 100.0

    draft = {
        "doc_type": "grn",
        "against_ref": document.external_ref,
        "against_document_id": str(document.id),
        "observed_quantity": observed_qty,
        "expected_quantity": expected_qty,
        "counted_unit": "carton" if carton_count is not None else "pallet",
        "received_at": event.timestamp.isoformat(),
        "camera_id": str(event.camera_id),
        "event_id": str(event.id),
        "vendor": document.payload.get("vendor"),
        # Stated in the draft itself so it survives being copied out of the UI.
        "note": "Draft prepared from a camera observation. Not posted to any system.",
    }

    if variance_pct <= tolerance_pct:
        return WorkflowOutcome(
            verdict="match", matched_document_id=document.id, draft=draft
        )

    return WorkflowOutcome(
        verdict="exception",
        matched_document_id=document.id,
        discrepancy={
            "reason": "quantity_mismatch",
            "field": "quantity",
            "expected": expected_qty,
            "observed": observed_qty,
            "variance_pct": round(variance_pct, 2),
            "tolerance_pct": tolerance_pct,
            "external_ref": document.external_ref,
            "message": (
                f"Camera counted {observed_qty} against {expected_qty} expected on "
                f"{document.external_ref} — {round(variance_pct, 1)}% variance, "
                f"tolerance is {tolerance_pct}%."
            ),
        },
        draft=draft,
    )
```

- [ ] **Step 3: Verify the registry picked it up**

```bash
cd backend && uv run python3 -c "
from app.services.workflows import implemented_types
print(implemented_types())
"
```

Expected: `['dock_grn_match']`.

- [ ] **Step 4: Verify all three branches by hand**

Seed a site with a rule and a document, then drive events through. Replace the UUIDs with real ones from your DB.

```bash
psql "$POSTGRES_URL" <<'SQL'
insert into workflow_rules (id, org_id, site_id, workflow_type, config, enabled)
select gen_random_uuid(), org_id, id, 'dock_grn_match',
       '{"quantity_tolerance_pct": 5, "match_window_hours": 24, "min_goods_confidence": 0.5}'::jsonb,
       true
from sites limit 1;

insert into expected_documents (id, org_id, site_id, source, doc_type, external_ref, payload, doc_date, status)
select gen_random_uuid(), org_id, id, 'manual', 'po', 'PO-4471',
       '{"expected_quantity": 20, "vendor": "Acme Supplies"}'::jsonb, now(), 'open'
from sites limit 1;
SQL
```

Now POST three events against a camera whose `camera_role='dock'` on that site (use the `/internal/events` curl from Task 1, adding `metadata_extra`):

| Case | `metadata_extra` | Expected exception row |
|---|---|---|
| Match | `{"goods":{"carton_count":20,"pallet_count":null,"visible_refs":["PO-4471"],"goods_confidence":0.9}}` | `status=auto_cleared`, `draft.expected_quantity=20` |
| Mismatch | `{"goods":{"carton_count":12,"pallet_count":null,"visible_refs":["PO-4471"],"goods_confidence":0.9}}` | `status=open`, `discrepancy.reason=quantity_mismatch`, `variance_pct=40` |
| No data | `{}` | no row at all |

Check with:

```bash
psql "$POSTGRES_URL" -c "select workflow_type, status, discrepancy->>'reason', draft->>'against_ref' from workflow_exceptions order by created_at desc limit 5;"
```

Then delete the seeded `PO-4471` and re-post the match case. Expected: `status=open`, `reason=no_matching_document`. Then insert two open POs with no ref in the goods block and confirm `reason=ambiguous_document`.

- [ ] **Step 5: Self-review**

- Does the module ever mutate `event`, `camera`, or `rule`? (It must not — the engine owns persistence. Confirm read-only.)
- Is `org_id` filtered on the candidate query? (Yes, `ExpectedDocument.org_id == event.org_id`. This is the cross-tenant boundary for this whole feature — a missing filter here would match one customer's delivery against another's purchase order. Read the query again and confirm.)
- Does the `site_id IS NULL` branch widen matching further than intended? (It allows org-wide unattributed documents to match any site. That is deliberate for Tally data with no site mapping — confirm it cannot cross orgs, which is the only boundary that matters.)
- Does comparing cartons against a document whose `expected_quantity` is in a different unit produce a nonsense variance? (Yes — and Phase 1 has no unit reconciliation. Confirm `draft.counted_unit` records what was actually counted so a human can see the mismatch, and note this as a known limitation for the Phase 1 pilot.)
- Is `variance_pct` computed the way an accountant would expect? (Against expected, not against observed. Check the zero-expected branch does not silently pass.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/workflows/dock_grn.py backend/app/services/workflows/__init__.py
git commit -m "feat(workflows): add dock GRN auto-match module"
```

---

# Phase D — Connector layer (spec Layer 4)

---

### Task 9: Tally connector (read-only)

**Files:**
- Create: `backend/app/connectors/__init__.py`
- Create: `backend/app/connectors/tally/__init__.py`
- Create: `backend/app/connectors/tally/client.py`
- Create: `backend/app/connectors/tally/sync.py`
- Modify: `backend/app/main.py` (scheduler job)

**Interfaces:**
- Consumes: Task 6's `ExpectedDocument` and `ConnectorSyncLog`.
- Produces:
  - `TallyConfig`: `base_url: str, company_name: str, enabled: bool, site_id: uuid.UUID | None` — read from `Organization.settings["tally"]`
  - `TallyClient(config, transport)` with `async def fetch(report: str, from_date: date, to_date: date) -> list[TallyDocument]`
  - `TallyDocument` (pydantic): `doc_type, external_ref, payload, doc_date, status`
  - `sync_org(org, db) -> ConnectorSyncLog`
  - `run_tally_sync_sweep() -> None` — the scheduled entry point, one org at a time
  - `HttpTransport` — the default transport; `AgentTransport` is Phase 2's drop-in replacement

**Why a transport seam:** spec Section 4 says most customers' Tally is on-prem and unreachable from the cloud, and that the production path is likely an agent bridge — but says to confirm topology with a pilot before building it. `TallyClient` therefore takes a transport object with one method. Phase 1 ships `HttpTransport`; Phase 2 can add an agent-relayed transport without `sync.py` changing at all. Building `sync.py` against a transport costs nothing now and saves a rewrite later.

**Configuration lives in `Organization.settings["tally"]`**, matching how `retention_days` and digest settings already work. No new settings table.

```json
{"tally": {"enabled": true, "base_url": "http://10.0.0.9:9000", "company_name": "Acme Traders", "site_id": null}}
```

- [ ] **Step 1: Write the client**

`backend/app/connectors/tally/client.py`:

```python
"""Tally XML-over-HTTP client.

Tally exposes an XML request/response endpoint (default port 9000) on the
machine it runs on. There is no REST API, no auth header, and no pagination —
the request names a report and a date range, and the response is one XML
document.

The transport is injected. Phase 1 ships an HTTP transport that assumes the
backend can reach Tally directly (VPN, port-forward, or cloud-hosted Tally).
Most real deployments will need a relay through the customer's edge agent
instead; that is a different transport and nothing else changes.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Tally reports we pull, mapped to the doc_type we store them as.
REPORT_DOC_TYPES = {
    "Purchase Order Outstandings": "po",
    "Purchase Register": "invoice",
    "Stock Summary": "stock_on_hand",
}

REQUEST_TEMPLATE = """<ENVELOPE>
  <HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>
  <BODY><EXPORTDATA><REQUESTDESC>
    <REPORTNAME>{report}</REPORTNAME>
    <STATICVARIABLES>
      <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
      <SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY>
      <SVFROMDATE>{from_date}</SVFROMDATE>
      <SVTODATE>{to_date}</SVTODATE>
    </STATICVARIABLES>
  </REQUESTDESC></EXPORTDATA></BODY>
</ENVELOPE>"""


@dataclass
class TallyConfig:
    base_url: str
    company_name: str
    enabled: bool = False
    # Optional mapping of this org's whole Tally company to one NightWatch
    # site. None means documents are stored unattributed and match org-wide.
    site_id: uuid.UUID | None = None

    @classmethod
    def from_org_settings(cls, settings: dict | None) -> "TallyConfig | None":
        raw = (settings or {}).get("tally")
        if not isinstance(raw, dict) or not raw.get("base_url"):
            return None
        site_id = raw.get("site_id")
        return cls(
            base_url=str(raw["base_url"]).rstrip("/"),
            company_name=str(raw.get("company_name", "")),
            enabled=bool(raw.get("enabled", False)),
            site_id=uuid.UUID(site_id) if site_id else None,
        )


class TallyDocument(BaseModel):
    doc_type: str
    external_ref: str
    payload: dict
    doc_date: datetime | None = None
    status: str = "open"


class Transport(Protocol):
    async def post_xml(self, base_url: str, body: str) -> str: ...


class HttpTransport:
    """Direct HTTP to a reachable Tally instance."""

    def __init__(self, timeout_seconds: float = 20.0):
        self._timeout = timeout_seconds

    async def post_xml(self, base_url: str, body: str) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                base_url, content=body.encode("utf-8"),
                headers={"Content-Type": "text/xml"},
            )
            response.raise_for_status()
            return response.text


def _text(node, tag: str) -> str | None:
    found = node.find(tag)
    return found.text.strip() if found is not None and found.text else None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    # Tally emits YYYYMMDD in export XML.
    for fmt in ("%Y%m%d", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    logger.warning("unparseable Tally date %r", value)
    return None


class TallyClient:
    def __init__(self, config: TallyConfig, transport: Transport | None = None):
        self._config = config
        self._transport = transport or HttpTransport()

    async def fetch(
        self, report: str, from_date: date, to_date: date
    ) -> list[TallyDocument]:
        doc_type = REPORT_DOC_TYPES[report]
        body = REQUEST_TEMPLATE.format(
            report=report,
            company=self._config.company_name,
            from_date=from_date.strftime("%Y%m%d"),
            to_date=to_date.strftime("%Y%m%d"),
        )
        xml = await self._transport.post_xml(self._config.base_url, body)
        return self._parse(xml, doc_type)

    def _parse(self, xml: str, doc_type: str) -> list[TallyDocument]:
        """Parse one export response into documents.

        Tally's export XML is not schema-stable across versions or company
        configurations, so this reads a small set of named fields and stores
        the rest of the row verbatim in `payload`. A field this parser does
        not know about is preserved rather than dropped, which is what lets a
        later module use it without a re-sync.
        """
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            raise ValueError(f"Tally returned unparseable XML: {exc}") from exc

        documents: list[TallyDocument] = []
        for node in root.iter():
            if node.tag not in ("VOUCHER", "STOCKITEM", "PURCHASEORDER"):
                continue

            external_ref = (
                _text(node, "VOUCHERNUMBER")
                or _text(node, "ORDERNUMBER")
                or _text(node, "NAME")
            )
            if not external_ref:
                continue

            payload = {
                child.tag.lower(): (child.text or "").strip()
                for child in node
                if child.text and child.text.strip()
            }

            quantity = (
                _text(node, "BILLEDQTY")
                or _text(node, "ORDERQTY")
                or _text(node, "CLOSINGBALANCE")
            )
            if quantity is not None:
                # Tally writes quantities as "20 Nos". Keep the number for
                # comparison and the original string for the human reading it.
                head = quantity.split()[0].replace(",", "")
                try:
                    payload["expected_quantity"] = float(head)
                except ValueError:
                    logger.warning("unparseable Tally quantity %r", quantity)
                payload["expected_quantity_raw"] = quantity

            vendor = _text(node, "PARTYLEDGERNAME") or _text(node, "PARTYNAME")
            if vendor:
                payload["vendor"] = vendor

            documents.append(
                TallyDocument(
                    doc_type=doc_type,
                    external_ref=external_ref,
                    payload=payload,
                    doc_date=_parse_date(_text(node, "DATE")),
                    status="closed" if _text(node, "ISCANCELLED") == "Yes" else "open",
                )
            )
        return documents
```

- [ ] **Step 2: Write the sync**

`backend/app/connectors/tally/sync.py`:

```python
"""Scheduled read-only pull from Tally into `expected_documents`.

Overlapping windows on purpose: each run re-pulls the last `LOOKBACK_DAYS`, so
a document edited in Tally after it was first synced is corrected on the next
pass. That only works because the upsert key is the document's natural key,
not a surrogate id.

Nothing is written back to Tally. Ever, in Phase 1.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.connectors.tally.client import (
    REPORT_DOC_TYPES,
    TallyClient,
    TallyConfig,
)
from app.core.database import async_session_factory
from app.models.organization import Organization
from app.models.workflow import ConnectorSyncLog, ExpectedDocument

logger = logging.getLogger(__name__)

# How far back each run re-reads. Wide enough that an edit to last week's
# purchase order is picked up, narrow enough that a sync is a small query.
LOOKBACK_DAYS = 30


async def sync_org(org: Organization, db) -> ConnectorSyncLog:
    config = TallyConfig.from_org_settings(org.settings)
    if config is None or not config.enabled:
        raise ValueError("Tally is not configured for this organization")

    client = TallyClient(config)
    to_date = date.today()
    from_date = to_date - timedelta(days=LOOKBACK_DAYS)

    pulled = 0
    error: str | None = None
    try:
        for report in REPORT_DOC_TYPES:
            documents = await client.fetch(report, from_date, to_date)
            for doc in documents:
                stmt = (
                    pg_insert(ExpectedDocument)
                    .values(
                        org_id=org.id,
                        site_id=config.site_id,
                        source="tally",
                        doc_type=doc.doc_type,
                        external_ref=doc.external_ref,
                        payload=doc.payload,
                        doc_date=doc.doc_date,
                        status=doc.status,
                        synced_at=datetime.now(timezone.utc),
                    )
                    .on_conflict_do_update(
                        constraint="uq_expected_document_ref",
                        set_={
                            "payload": doc.payload,
                            "doc_date": doc.doc_date,
                            "status": doc.status,
                            "site_id": config.site_id,
                            "synced_at": datetime.now(timezone.utc),
                        },
                    )
                )
                await db.execute(stmt)
                pulled += 1
    except Exception as exc:  # noqa: BLE001
        # The log row is the point of this function. A failed sync that leaves
        # no record is indistinguishable from a sync that never ran, and the
        # UI's staleness banner depends on being able to tell those apart.
        error = f"{type(exc).__name__}: {exc}"[:2000]
        logger.exception("tally sync failed for org %s", org.id)

    log = ConnectorSyncLog(
        org_id=org.id,
        connector="tally",
        status="error" if error else "ok",
        records_pulled=pulled,
        error=error,
    )
    db.add(log)
    await db.commit()
    return log


async def run_tally_sync_sweep() -> None:
    """Sync every org that has Tally enabled. One org at a time.

    Serial by design: a connector pull must not compete with event ingestion
    for connections, and the orgs running this are counted in tens, not
    thousands. Revisit when that stops being true, not before.
    """
    async with async_session_factory() as db:
        orgs = (
            await db.execute(
                select(Organization).where(Organization.deleted_at.is_(None))
            )
        ).scalars().all()

    for org in orgs:
        config = TallyConfig.from_org_settings(org.settings)
        if config is None or not config.enabled:
            continue
        async with async_session_factory() as db:
            try:
                await sync_org(org, db)
            except Exception:  # noqa: BLE001
                logger.exception("tally sweep failed for org %s", org.id)
```

Create empty `backend/app/connectors/__init__.py` and `backend/app/connectors/tally/__init__.py`.

- [ ] **Step 3: Schedule it**

In `backend/app/main.py`, inside the `if scheduler is not None:` block alongside the other sweeps:

```python
                # Every 15 minutes, per the spec. The workflow layer compares
                # against whatever this last pulled, so sync staleness is
                # match staleness — the UI surfaces the last run for exactly
                # this reason.
                scheduler.add_job(
                    run_tally_sync_sweep,
                    "interval",
                    minutes=15,
                    id="tally_sync_sweep",
                    replace_existing=True,
                )
```

with the import:

```python
from app.connectors.tally.sync import run_tally_sync_sweep
```

- [ ] **Step 4: Verify the parser without a Tally instance**

```bash
cd backend && uv run python3 -c "
from app.connectors.tally.client import TallyClient, TallyConfig
xml = '''<ENVELOPE><VOUCHER><VOUCHERNUMBER>PO-4471</VOUCHERNUMBER><DATE>20260825</DATE><ORDERQTY>20 Nos</ORDERQTY><PARTYLEDGERNAME>Acme Supplies</PARTYLEDGERNAME></VOUCHER></ENVELOPE>'''
c = TallyClient(TallyConfig(base_url='http://x', company_name='Acme'))
docs = c._parse(xml, 'po')
assert len(docs) == 1, docs
d = docs[0]
assert d.external_ref == 'PO-4471', d.external_ref
assert d.payload['expected_quantity'] == 20.0, d.payload
assert d.payload['vendor'] == 'Acme Supplies'
assert d.doc_date.year == 2026
print('ok')
"
```

Expected: `ok`.

Also confirm bad XML fails loudly rather than silently returning nothing:

```bash
cd backend && uv run python3 -c "
from app.connectors.tally.client import TallyClient, TallyConfig
c = TallyClient(TallyConfig(base_url='http://x', company_name='Acme'))
try:
    c._parse('not xml', 'po')
    print('FAIL: silent')
except ValueError as e:
    print('ok:', e)
"
```

Expected: `ok: Tally returned unparseable XML: ...`.

- [ ] **Step 5: Verify the sweep skips unconfigured orgs**

```bash
cd backend && uv run python3 -c "from app.main import app; print('ok')"
```

Start the backend with no org configured for Tally. Expected: the sweep runs on schedule and writes **no** `connector_sync_log` rows, because every org is skipped before a client is constructed.

```bash
psql "$POSTGRES_URL" -c "select count(*) from connector_sync_log;"
```

Expected: `0`.

Then configure one org against a deliberately unreachable URL:

```bash
psql "$POSTGRES_URL" -c "update organizations set settings = settings || '{\"tally\":{\"enabled\":true,\"base_url\":\"http://127.0.0.1:9999\",\"company_name\":\"Test\"}}'::jsonb where id = (select id from organizations limit 1);"
```

Expected after the next sweep: one `connector_sync_log` row with `status='error'` and a populated `error` — **not** a crashed scheduler.

- [ ] **Step 6: Validate the discrepancy math against a real Tally export**

This is the spec's Section 9 gate and it is not optional before any pilot claim. Obtain one real Tally XML export (a Purchase Order Outstandings report from a pilot or demo company), run it through `TallyClient._parse`, and check by hand that `expected_quantity` matches what the report shows for at least five documents. Record the result — company, report, date, documents checked — in the commit message.

If no real export is available yet, say so explicitly and do not mark this step done. The spec's rule stands: no "audit-ready" or "reconciliation" claim to any prospect until this has been checked.

- [ ] **Step 7: Self-review**

- Is `httpx` already a backend dependency? (`grep httpx backend/requirements.txt backend/pyproject.toml` — add it if not, and say so.)
- Can `sync_org` be reached with an org the caller does not own? (It takes an `Organization` object, and Task 10's endpoint must load that object with the usual org filter. Confirm the endpoint does, not this function.)
- Does the upsert ever move a document between orgs? (The conflict key includes `org_id`, so no — confirm by reading the constraint.)
- Does a partial failure mid-report leave half a sync committed? (Yes — the commit is at the end, but the exception is caught before it. Decide whether that is right: a partial pull with an `error` log is more useful than an all-or-nothing rollback, but say so explicitly rather than leaving it implicit.)
- Is the base URL an SSRF risk? (It is operator-configured per org, and the backend will POST to it. Note whether org settings are super-admin-only or org-admin-editable, and whether that is acceptable. If org admins can set it, this is a real finding worth raising before pilot.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/connectors/ backend/app/main.py
git commit -m "feat(connectors): add read-only Tally document sync"
```

---

# Phase E — Surfaces (spec Layer 5, Sections 5 and 6)

---

### Task 10: Workflow and connector API

**Files:**
- Create: `backend/app/schemas/workflow.py`
- Create: `backend/app/api/workflows.py`
- Create: `backend/app/api/connectors.py`
- Modify: `backend/app/main.py` (register both routers)

**Interfaces:**
- Consumes: Tasks 6, 7, 8, 9.
- Produces the six endpoints from spec Section 5:

```
GET  /api/workflows/exceptions?site_id=&status=&workflow_type=&limit=&offset=
POST /api/workflows/exceptions/{id}/resolve      {action: "approve"|"reject", note?: string}
GET  /api/workflows/rules?site_id=
POST /api/workflows/rules                        {site_id, workflow_type, config, enabled}
GET  /api/connectors/tally/status
POST /api/connectors/tally/sync
```

Response models Task 11 consumes verbatim:
- `WorkflowExceptionResponse`: `id, site_id, event_id, workflow_type, status, matched_document_id, discrepancy, draft, note, created_at, resolved_at, resolved_by, event (EventSummary), document (DocumentSummary | null)`
- `EventSummary`: `id, camera_id, camera_name, timestamp, event_type, description, snapshot_url`
- `DocumentSummary`: `id, doc_type, external_ref, payload, doc_date, status`
- `WorkflowRuleResponse`: `id, site_id, workflow_type, config, enabled, created_at, updated_at`
- `TallyStatusResponse`: `configured, enabled, last_run_at, last_status, records_pulled, error, stale`

- [ ] **Step 1: Write the schemas**

`backend/app/schemas/workflow.py`:

```python
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EventSummary(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    camera_name: str
    timestamp: datetime
    event_type: str
    description: str | None = None
    snapshot_url: str | None = None


class DocumentSummary(BaseModel):
    id: uuid.UUID
    doc_type: str
    external_ref: str
    payload: dict
    doc_date: datetime | None = None
    status: str


class WorkflowExceptionResponse(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    event_id: uuid.UUID
    workflow_type: str
    status: str
    matched_document_id: uuid.UUID | None = None
    discrepancy: dict = {}
    draft: dict = {}
    note: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by: uuid.UUID | None = None
    event: EventSummary | None = None
    document: DocumentSummary | None = None


class ExceptionListResponse(BaseModel):
    items: list[WorkflowExceptionResponse]
    total: int


class ResolveExceptionRequest(BaseModel):
    action: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=2000)


class WorkflowRuleResponse(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    workflow_type: str
    config: dict
    enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UpsertWorkflowRuleRequest(BaseModel):
    site_id: uuid.UUID
    workflow_type: str
    config: dict = {}
    enabled: bool = True


class TallyStatusResponse(BaseModel):
    configured: bool
    enabled: bool
    last_run_at: datetime | None = None
    last_status: str | None = None
    records_pulled: int | None = None
    error: str | None = None
    # True when the last successful run is older than the staleness threshold,
    # or when there has never been one. The UI banners on this rather than
    # recomputing the threshold client-side, so there is one definition.
    stale: bool = True
```

- [ ] **Step 2: Write the workflows API**

`backend/app/api/workflows.py`:

```python
"""Operator-facing endpoints for the workflow exception queue.

Resolving an exception records a human decision. It does not write to any
external system — the draft is for a human to key in, and Phase 1 deliberately
has no write-back path at all.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    get_current_user,
    scope_to_sites,
    user_may_access_site,
)
from app.models.camera import Camera
from app.models.event import Event
from app.models.site import Site
from app.models.user import User
from app.models.workflow import ExpectedDocument, WorkflowException, WorkflowRule
from app.schemas.workflow import (
    DocumentSummary,
    EventSummary,
    ExceptionListResponse,
    ResolveExceptionRequest,
    UpsertWorkflowRuleRequest,
    WorkflowExceptionResponse,
    WorkflowRuleResponse,
)
from app.services.gcs import sign_gcs_url
from app.services.workflows import implemented_types

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

MAX_PAGE_SIZE = 100


@router.get("/exceptions", response_model=ExceptionListResponse)
async def list_exceptions(
    site_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    workflow_type: str | None = Query(default=None),
    limit: int = Query(default=50, le=MAX_PAGE_SIZE, ge=1),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(WorkflowException, Event, Camera, ExpectedDocument)
        .join(Event, WorkflowException.event_id == Event.id)
        .join(Camera, Event.camera_id == Camera.id)
        .outerjoin(
            ExpectedDocument,
            WorkflowException.matched_document_id == ExpectedDocument.id,
        )
    )
    if user.role != "super_admin":
        q = q.where(WorkflowException.org_id == user.org_id)
    q = scope_to_sites(q, WorkflowException.site_id, user)

    if site_id is not None:
        if not user_may_access_site(user, site_id):
            raise HTTPException(status_code=404, detail="Site not found")
        q = q.where(WorkflowException.site_id == site_id)
    if status is not None:
        q = q.where(WorkflowException.status == status)
    if workflow_type is not None:
        q = q.where(WorkflowException.workflow_type == workflow_type)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows = (
        await db.execute(
            q.order_by(WorkflowException.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()

    return ExceptionListResponse(
        items=[_to_response(exc, event, camera, doc) for exc, event, camera, doc in rows],
        total=total,
    )


def _to_response(exc, event, camera, document) -> WorkflowExceptionResponse:
    return WorkflowExceptionResponse(
        id=exc.id,
        site_id=exc.site_id,
        event_id=exc.event_id,
        workflow_type=exc.workflow_type,
        status=exc.status,
        matched_document_id=exc.matched_document_id,
        discrepancy=exc.discrepancy or {},
        draft=exc.draft or {},
        note=exc.note,
        created_at=exc.created_at,
        resolved_at=exc.resolved_at,
        resolved_by=exc.resolved_by,
        event=EventSummary(
            id=event.id,
            camera_id=camera.id,
            camera_name=camera.name,
            timestamp=event.timestamp,
            event_type=event.event_type,
            description=event.description,
            snapshot_url=sign_gcs_url(event.snapshot_url),
        ),
        document=(
            DocumentSummary(
                id=document.id,
                doc_type=document.doc_type,
                external_ref=document.external_ref,
                payload=document.payload or {},
                doc_date=document.doc_date,
                status=document.status,
            )
            if document is not None
            else None
        ),
    )


@router.post("/exceptions/{exception_id}/resolve", response_model=WorkflowExceptionResponse)
async def resolve_exception(
    exception_id: uuid.UUID,
    body: ResolveExceptionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(WorkflowException, Event, Camera, ExpectedDocument)
        .join(Event, WorkflowException.event_id == Event.id)
        .join(Camera, Event.camera_id == Camera.id)
        .outerjoin(
            ExpectedDocument,
            WorkflowException.matched_document_id == ExpectedDocument.id,
        )
        .where(WorkflowException.id == exception_id)
    )
    if user.role != "super_admin":
        q = q.where(WorkflowException.org_id == user.org_id)
    q = scope_to_sites(q, WorkflowException.site_id, user)

    row = (await db.execute(q)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Exception not found")
    exc, event, camera, document = row

    if exc.status in ("approved", "rejected"):
        # Idempotent-ish rather than silently overwriting: two operators
        # working the same queue should see a conflict, not a last-write-wins
        # that erases the first decision.
        raise HTTPException(status_code=409, detail="Exception already resolved")

    exc.status = "approved" if body.action == "approve" else "rejected"
    exc.note = body.note
    exc.resolved_at = datetime.now(timezone.utc)
    exc.resolved_by = user.id
    await db.flush()

    return _to_response(exc, event, camera, document)


@router.get("/rules", response_model=list[WorkflowRuleResponse])
async def list_rules(
    site_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(WorkflowRule)
    if user.role != "super_admin":
        q = q.where(WorkflowRule.org_id == user.org_id)
    q = scope_to_sites(q, WorkflowRule.site_id, user)
    if site_id is not None:
        if not user_may_access_site(user, site_id):
            raise HTTPException(status_code=404, detail="Site not found")
        q = q.where(WorkflowRule.site_id == site_id)

    rules = (await db.execute(q.order_by(WorkflowRule.workflow_type))).scalars().all()
    return [WorkflowRuleResponse.model_validate(r) for r in rules]


@router.post("/rules", response_model=WorkflowRuleResponse)
async def upsert_rule(
    body: UpsertWorkflowRuleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enable or reconfigure one workflow for one site.

    Validated against the registry of IMPLEMENTED modules, not the database's
    CHECK constraint. The constraint lists the roadmap; the registry lists what
    actually runs. Letting an operator enable a roadmap entry would produce a
    rule that silently never fires.
    """
    if body.workflow_type not in implemented_types():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown workflow type. Available: {', '.join(implemented_types())}",
        )

    # org_id comes from the SITE, resolved under the caller's scope — never
    # from the request body.
    site_q = select(Site).where(Site.id == body.site_id, Site.deleted_at.is_(None))
    if user.role != "super_admin":
        site_q = site_q.where(Site.org_id == user.org_id)
    site_q = scope_to_sites(site_q, Site.id, user)
    site = (await db.execute(site_q)).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")

    existing = (
        await db.execute(
            select(WorkflowRule).where(
                WorkflowRule.site_id == site.id,
                WorkflowRule.workflow_type == body.workflow_type,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = WorkflowRule(
            org_id=site.org_id,
            site_id=site.id,
            workflow_type=body.workflow_type,
        )
        db.add(existing)

    existing.config = body.config
    existing.enabled = body.enabled
    await db.flush()
    return WorkflowRuleResponse.model_validate(existing)
```

- [ ] **Step 3: Write the connectors API**

`backend/app/api/connectors.py`:

```python
"""Connector health and manual sync.

Manual sync is rate-limited because it is a network call into a customer's
own infrastructure, and a refresh button that hammers their Tally box is a
support ticket.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.tally.client import TallyConfig
from app.connectors.tally.sync import sync_org
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.redis import get_redis
from app.models.organization import Organization
from app.models.user import User
from app.models.workflow import ConnectorSyncLog
from app.schemas.workflow import TallyStatusResponse

router = APIRouter(prefix="/api/connectors", tags=["connectors"])

# Matches the scheduled interval. A last-good-sync older than this means the
# scheduler is not running or the customer's Tally is unreachable — either
# way the matching data is stale and the UI must say so.
STALE_AFTER = timedelta(minutes=45)
MANUAL_SYNC_COOLDOWN_SECONDS = 60


async def _load_org(user: User, db: AsyncSession) -> Organization:
    org = (
        await db.execute(
            select(Organization).where(
                Organization.id == user.org_id, Organization.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.get("/tally/status", response_model=TallyStatusResponse)
async def tally_status(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    org = await _load_org(user, db)
    config = TallyConfig.from_org_settings(org.settings)

    last = (
        await db.execute(
            select(ConnectorSyncLog)
            .where(
                ConnectorSyncLog.org_id == org.id,
                ConnectorSyncLog.connector == "tally",
            )
            .order_by(ConnectorSyncLog.run_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    last_ok = (
        await db.execute(
            select(ConnectorSyncLog.run_at)
            .where(
                ConnectorSyncLog.org_id == org.id,
                ConnectorSyncLog.connector == "tally",
                ConnectorSyncLog.status == "ok",
            )
            .order_by(ConnectorSyncLog.run_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    stale = last_ok is None or (datetime.now(timezone.utc) - last_ok) > STALE_AFTER

    return TallyStatusResponse(
        configured=config is not None,
        enabled=bool(config and config.enabled),
        last_run_at=last.run_at if last else None,
        last_status=last.status if last else None,
        records_pulled=last.records_pulled if last else None,
        error=last.error if last else None,
        stale=stale,
    )


@router.post("/tally/sync", response_model=TallyStatusResponse)
async def trigger_tally_sync(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    require_role(user, "admin")
    org = await _load_org(user, db)

    r = await get_redis()
    key = f"tally:manual_sync:{org.id}"
    if not await r.set(key, "1", ex=MANUAL_SYNC_COOLDOWN_SECONDS, nx=True):
        raise HTTPException(
            status_code=429,
            detail=f"A sync was already triggered. Try again in {MANUAL_SYNC_COOLDOWN_SECONDS}s.",
        )

    try:
        await sync_org(org, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await tally_status(user=user, db=db)
```

Check `require_role`'s exact contract at `backend/app/core/dependencies.py:138` before using it — confirm whether it raises or returns, and what role names it accepts.

- [ ] **Step 4: Register the routers**

In `backend/app/main.py`, next to the other `include_router` calls:

```python
app.include_router(workflows_router)
app.include_router(connectors_router)
```

with imports matching the file's existing style:

```python
from app.api.workflows import router as workflows_router
from app.api.connectors import router as connectors_router
```

- [ ] **Step 5: Verify the endpoints**

```bash
cd backend && uv run python3 -c "from app.main import app; print('ok')"
```

Log in and exercise each endpoint (substitute your token):

```bash
curl -s localhost:8080/api/workflows/exceptions -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

```bash
curl -s -X POST localhost:8080/api/workflows/rules -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"site_id":"<SITE_UUID>","workflow_type":"dock_grn_match","config":{"quantity_tolerance_pct":5},"enabled":true}' | python3 -m json.tool
```

Expected: the rule is created. Then confirm an unimplemented type is refused:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8080/api/workflows/rules -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"site_id":"<SITE_UUID>","workflow_type":"demand_trend_feed","enabled":true}'
```

Expected: `400`.

```bash
curl -s localhost:8080/api/connectors/tally/status -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: `configured` and `enabled` reflect the org's settings, `stale` is `true` with no successful run.

- [ ] **Step 6: Verify tenant isolation by hand**

This is the check that matters most on this feature — the whole point is comparing one customer's cameras against one customer's books.

Create an exception under org A. Log in as a user in org B and:

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/api/workflows/exceptions/<ORG_A_EXCEPTION_ID>/resolve -X POST -H "Authorization: Bearer $ORG_B_TOKEN" -H 'Content-Type: application/json' -d '{"action":"approve"}'
```

Expected: `404` (not 403 — the row must not be acknowledged to exist).

```bash
curl -s localhost:8080/api/workflows/exceptions -H "Authorization: Bearer $ORG_B_TOKEN" | python3 -c "import json,sys; print(json.load(sys.stdin)['total'])"
```

Expected: `0`.

Then repeat with a **site-restricted** user in org A whose `sites_access` excludes the exception's site. Expected: also `404` and `0`. Org filtering alone is not enough — both halves are required, and this is where a missing `scope_to_sites` would show up.

- [ ] **Step 7: Self-review**

- Does every query in both files have both the org filter and `scope_to_sites`? Read each one and tick it off individually. (`list_exceptions`, `resolve_exception`, `list_rules`, `upsert_rule`'s site lookup.)
- Does `upsert_rule` take `org_id` from anywhere other than the resolved `Site`? (It must not.)
- Does `resolve_exception` let a user resolve an `auto_cleared` row? (Currently yes — that is intended: "I looked at the auto-clear and I accept it" is a real action. Confirm you agree, and that re-resolving an already `approved`/`rejected` row 409s.)
- Does the count query double-count on the outer join? (`ExpectedDocument` is joined on a nullable FK to a unique id, so one row max — confirm.)
- Is `sign_gcs_url` safe to call with `None`? (Check its implementation; `snapshot_url` is nullable on `Event`.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/workflow.py backend/app/api/workflows.py backend/app/api/connectors.py backend/app/main.py
git commit -m "feat(workflows): add exception queue and connector status API"
```

---

### Task 11: Exceptions queue UI, settings toggles, connector widget

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/components/exceptions/connector-status.tsx`
- Create: `frontend/src/components/exceptions/exception-detail.tsx`
- Create: `frontend/src/app/exceptions/page.tsx`
- Modify: `frontend/src/components/layout/sidebar.tsx`
- Modify: `frontend/src/components/layout/app-shell.tsx`
- Modify: `frontend/src/app/settings/page.tsx`

**Interfaces:**
- Consumes: Task 10's six endpoints and their exact response shapes.
- Produces: the `/exceptions` route and six `api` client methods — `getWorkflowExceptions`, `resolveWorkflowException`, `getWorkflowRules`, `upsertWorkflowRule`, `getTallyStatus`, `triggerTallySync`.

**Design constraints:** dark mode only, TanStack Query for all fetching, match the visual language of `frontend/src/app/setup/page.tsx` (it is the closest existing page — a review queue with per-item approve actions). The detail view is the point of the whole feature: an operator has to be able to see the snapshot, the document, and exactly what disagreed, side by side, without clicking through to three places.

- [ ] **Step 1: Add the types**

Append to `frontend/src/types/index.ts`:

```ts
// ─── Workflow / exception layer ─────────────────────────────────────────────

export type WorkflowType = "dock_grn_match";

export type ExceptionStatus = "open" | "approved" | "rejected" | "auto_cleared";

export interface ExceptionEventSummary {
  id: string;
  camera_id: string;
  camera_name: string;
  timestamp: string;
  event_type: string;
  description: string | null;
  snapshot_url: string | null;
}

export interface ExpectedDocumentSummary {
  id: string;
  doc_type: string;
  external_ref: string;
  payload: Record<string, unknown>;
  doc_date: string | null;
  status: string;
}

export interface WorkflowException {
  id: string;
  site_id: string;
  event_id: string;
  workflow_type: WorkflowType;
  status: ExceptionStatus;
  matched_document_id: string | null;
  discrepancy: Record<string, unknown>;
  draft: Record<string, unknown>;
  note: string | null;
  created_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
  event: ExceptionEventSummary | null;
  document: ExpectedDocumentSummary | null;
}

export interface WorkflowExceptionList {
  items: WorkflowException[];
  total: number;
}

export interface WorkflowRule {
  id: string;
  site_id: string;
  workflow_type: WorkflowType;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface TallyStatus {
  configured: boolean;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
  records_pulled: number | null;
  error: string | null;
  stale: boolean;
}
```

- [ ] **Step 2: Add the client methods**

In `frontend/src/lib/api.ts`, add the new types to the import block at the top, then add before the closing `}` of the class:

```ts
  // ─── Workflow exceptions ─────────────────────────────────────────────────

  async getWorkflowExceptions(params: {
    site_id?: string;
    status?: string;
    workflow_type?: string;
    limit?: number;
    offset?: number;
  } = {}) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== "") as [string, string][]
    ).toString();
    return this.request<WorkflowExceptionList>(
      `/api/workflows/exceptions${qs ? `?${qs}` : ""}`
    );
  }

  async resolveWorkflowException(id: string, action: "approve" | "reject", note?: string) {
    return this.request<WorkflowException>(`/api/workflows/exceptions/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ action, note }),
    });
  }

  async getWorkflowRules(siteId?: string) {
    const qs = siteId ? `?site_id=${siteId}` : "";
    return this.request<WorkflowRule[]>(`/api/workflows/rules${qs}`);
  }

  async upsertWorkflowRule(body: {
    site_id: string;
    workflow_type: string;
    config?: Record<string, unknown>;
    enabled: boolean;
  }) {
    return this.request<WorkflowRule>("/api/workflows/rules", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  async getTallyStatus() {
    return this.request<TallyStatus>("/api/connectors/tally/status");
  }

  async triggerTallySync() {
    return this.request<TallyStatus>("/api/connectors/tally/sync", { method: "POST" });
  }
```

- [ ] **Step 3: The connector status widget**

`frontend/src/components/exceptions/connector-status.tsx`:

```tsx
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";

/**
 * Tally sync health.
 *
 * Staleness is decided server-side and rendered here. Two places computing
 * "is this stale" from a timestamp is two places that can disagree, and an
 * operator resolving a quantity mismatch needs to know whether the number they
 * are comparing against is current.
 */
export function ConnectorStatus() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["tally-status"],
    queryFn: () => api.getTallyStatus(),
    refetchInterval: 60_000,
  });

  const sync = useMutation({
    mutationFn: () => api.triggerTallySync(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tally-status"] });
      qc.invalidateQueries({ queryKey: ["workflow-exceptions"] });
    },
  });

  if (isLoading || !data?.configured) return null;

  const tone = !data.enabled
    ? "border-zinc-800 text-zinc-400"
    : data.stale
    ? "border-amber-700/60 text-amber-300"
    : "border-zinc-800 text-zinc-400";

  return (
    <div className={`flex items-center justify-between gap-4 rounded-lg border ${tone} bg-zinc-950 px-4 py-3 text-sm`}>
      <div className="min-w-0">
        <span className="font-medium text-zinc-200">Tally</span>{" "}
        {!data.enabled ? (
          <span>configured but disabled.</span>
        ) : data.stale ? (
          <span>
            last successful sync is out of date
            {data.last_run_at ? ` (last run ${new Date(data.last_run_at).toLocaleString()})` : ", and there has never been one"}.
            Document matches may be comparing against old figures.
          </span>
        ) : (
          <span>
            synced {new Date(data.last_run_at as string).toLocaleString()} —{" "}
            {data.records_pulled ?? 0} records.
          </span>
        )}
        {data.error ? (
          <p className="mt-1 truncate text-xs text-red-400" title={data.error}>
            {data.error}
          </p>
        ) : null}
      </div>
      <button
        onClick={() => sync.mutate()}
        disabled={sync.isPending || !data.enabled}
        className="flex shrink-0 items-center gap-2 rounded-md border border-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-900 disabled:opacity-40"
      >
        <RefreshCw className={`h-3.5 w-3.5 ${sync.isPending ? "animate-spin" : ""}`} />
        Sync now
      </button>
    </div>
  );
}
```

- [ ] **Step 4: The detail view**

`frontend/src/components/exceptions/exception-detail.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { WorkflowException } from "@/types";
import { api } from "@/lib/api";

const REASON_LABELS: Record<string, string> = {
  quantity_mismatch: "Quantity mismatch",
  no_matching_document: "No matching document",
  ambiguous_document: "More than one possible document",
  document_has_no_quantity: "Document has no quantity to compare",
};

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-zinc-900 py-1.5 text-sm last:border-0">
      <span className="text-zinc-500">{label}</span>
      <span className="text-right text-zinc-200">{value}</span>
    </div>
  );
}

/**
 * Snapshot, document, and diff, side by side.
 *
 * The three panes are the whole product: an operator deciding whether a short
 * delivery is real needs the frame, the paperwork, and the arithmetic in one
 * view. Making them click through to the event page to see the snapshot is how
 * a queue turns into a rubber stamp.
 */
export function ExceptionDetail({ exception }: { exception: WorkflowException }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");

  const resolve = useMutation({
    mutationFn: (action: "approve" | "reject") =>
      api.resolveWorkflowException(exception.id, action, note || undefined),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflow-exceptions"] }),
  });

  const d = exception.discrepancy ?? {};
  const reason = typeof d.reason === "string" ? d.reason : null;
  const resolved = exception.status === "approved" || exception.status === "rejected";

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
          <h4 className="mb-2 text-xs uppercase tracking-wide text-zinc-500">What the camera saw</h4>
          {exception.event?.snapshot_url ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={exception.event.snapshot_url}
              alt={exception.event.description ?? "Event snapshot"}
              className="mb-3 w-full rounded border border-zinc-900"
            />
          ) : (
            <p className="mb-3 text-sm text-zinc-500">No snapshot.</p>
          )}
          <Field label="Camera" value={exception.event?.camera_name ?? "—"} />
          <Field
            label="Time"
            value={exception.event ? new Date(exception.event.timestamp).toLocaleString() : "—"}
          />
          <Field label="Detected" value={exception.event?.event_type ?? "—"} />
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
          <h4 className="mb-2 text-xs uppercase tracking-wide text-zinc-500">What the books say</h4>
          {exception.document ? (
            <>
              <Field label="Reference" value={exception.document.external_ref} />
              <Field label="Type" value={exception.document.doc_type.toUpperCase()} />
              <Field
                label="Date"
                value={
                  exception.document.doc_date
                    ? new Date(exception.document.doc_date).toLocaleDateString()
                    : "—"
                }
              />
              <Field label="Status" value={exception.document.status} />
              {Object.entries(exception.document.payload)
                .filter(([k]) => ["expected_quantity", "expected_quantity_raw", "vendor"].includes(k))
                .map(([k, v]) => (
                  <Field key={k} label={k.replace(/_/g, " ")} value={String(v)} />
                ))}
            </>
          ) : (
            <p className="text-sm text-zinc-500">
              No document was matched. That is itself the finding.
            </p>
          )}
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
          <h4 className="mb-2 text-xs uppercase tracking-wide text-zinc-500">What disagreed</h4>
          {reason ? (
            <p className="mb-2 text-sm font-medium text-amber-300">
              {REASON_LABELS[reason] ?? reason}
            </p>
          ) : null}
          {typeof d.message === "string" ? (
            <p className="mb-3 text-sm text-zinc-300">{d.message}</p>
          ) : null}
          {d.expected !== undefined ? <Field label="Expected" value={String(d.expected)} /> : null}
          {d.observed !== undefined ? <Field label="Observed" value={String(d.observed)} /> : null}
          {d.variance_pct !== undefined ? (
            <Field label="Variance" value={`${String(d.variance_pct)}%`} />
          ) : null}
          {d.tolerance_pct !== undefined ? (
            <Field label="Tolerance" value={`${String(d.tolerance_pct)}%`} />
          ) : null}
        </div>
      </div>

      {Object.keys(exception.draft ?? {}).length > 0 ? (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
          <h4 className="mb-1 text-xs uppercase tracking-wide text-zinc-500">Draft entry</h4>
          <p className="mb-2 text-xs text-zinc-500">
            Prepared for a human to key in. Nothing has been posted to Tally or any other
            system.
          </p>
          <pre className="max-h-56 overflow-auto rounded bg-black/40 p-3 text-xs text-zinc-300">
            {JSON.stringify(exception.draft, null, 2)}
          </pre>
        </div>
      ) : null}

      {resolved ? (
        <p className="text-sm text-zinc-500">
          {exception.status === "approved" ? "Approved" : "Rejected"}
          {exception.resolved_at ? ` on ${new Date(exception.resolved_at).toLocaleString()}` : ""}
          {exception.note ? ` — "${exception.note}"` : ""}
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Note (optional)"
            className="min-w-0 flex-1 rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600"
          />
          <button
            onClick={() => resolve.mutate("approve")}
            disabled={resolve.isPending}
            className="rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 hover:bg-white disabled:opacity-40"
          >
            Approve
          </button>
          <button
            onClick={() => resolve.mutate("reject")}
            disabled={resolve.isPending}
            className="rounded-md border border-zinc-800 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-900 disabled:opacity-40"
          >
            Reject
          </button>
        </div>
      )}
      {resolve.isError ? (
        <p className="text-sm text-red-400">
          {resolve.error instanceof Error ? resolve.error.message : "Could not resolve."}
        </p>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 5: The queue page**

`frontend/src/app/exceptions/page.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { ConnectorStatus } from "@/components/exceptions/connector-status";
import { ExceptionDetail } from "@/components/exceptions/exception-detail";
import type { ExceptionStatus } from "@/types";

const STATUS_TABS: { value: ExceptionStatus | "all"; label: string }[] = [
  { value: "open", label: "Needs review" },
  { value: "auto_cleared", label: "Auto-cleared" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "all", label: "All" },
];

export default function ExceptionsPage() {
  const [status, setStatus] = useState<ExceptionStatus | "all">("open");
  const [siteId, setSiteId] = useState<string>("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const { data: sites } = useQuery({ queryKey: ["sites"], queryFn: () => api.getSites() });

  const { data, isLoading } = useQuery({
    queryKey: ["workflow-exceptions", status, siteId],
    queryFn: () =>
      api.getWorkflowExceptions({
        status: status === "all" ? undefined : status,
        site_id: siteId || undefined,
      }),
    refetchInterval: 30_000,
  });

  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-100">Exceptions</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Where a camera and the paperwork disagreed. Approving records your decision — it
          does not write anything back to Tally.
        </p>
      </div>

      <ConnectorStatus />

      <div className="flex flex-wrap items-center gap-2">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setStatus(tab.value)}
            className={`rounded-md px-3 py-1.5 text-sm ${
              status === tab.value
                ? "bg-zinc-100 text-zinc-900"
                : "border border-zinc-800 text-zinc-400 hover:bg-zinc-900"
            }`}
          >
            {tab.label}
          </button>
        ))}
        <select
          value={siteId}
          onChange={(e) => setSiteId(e.target.value)}
          className="ml-auto rounded-md border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-sm text-zinc-300"
        >
          <option value="">All sites</option>
          {sites?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : !data?.items.length ? (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-8 text-center">
          <p className="text-sm text-zinc-400">Nothing here.</p>
          <p className="mt-1 text-xs text-zinc-600">
            Exceptions appear once a workflow is enabled for a site in Settings and a camera
            with a business role produces a matching event.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {data.items.map((exc) => (
            <div key={exc.id} className="rounded-lg border border-zinc-800 bg-zinc-950">
              <button
                onClick={() => setExpanded(expanded === exc.id ? null : exc.id)}
                className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm text-zinc-200">
                    {typeof exc.discrepancy?.message === "string"
                      ? exc.discrepancy.message
                      : "Camera observation matched the expected document."}
                  </p>
                  <p className="mt-0.5 text-xs text-zinc-600">
                    {exc.event?.camera_name ?? "Unknown camera"} ·{" "}
                    {new Date(exc.created_at).toLocaleString()}
                  </p>
                </div>
                <span
                  className={`shrink-0 rounded px-2 py-0.5 text-xs ${
                    exc.status === "open"
                      ? "bg-amber-500/10 text-amber-300"
                      : exc.status === "auto_cleared"
                      ? "bg-emerald-500/10 text-emerald-300"
                      : "bg-zinc-800 text-zinc-400"
                  }`}
                >
                  {exc.status.replace("_", " ")}
                </span>
              </button>
              {expanded === exc.id ? (
                <div className="border-t border-zinc-900 p-4">
                  <ExceptionDetail exception={exc} />
                </div>
              ) : null}
            </div>
          ))}
          <p className="pt-1 text-xs text-zinc-600">
            {data.items.length} of {data.total}
          </p>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Add the nav entries**

In `frontend/src/components/layout/sidebar.tsx`, add to `navItems` after the Alerts entry:

```ts
  { href: "/exceptions", label: "Exceptions", icon: ClipboardCheck, tourId: "nav-exceptions" },
```

and add `ClipboardCheck` to the `lucide-react` import.

In `frontend/src/components/layout/app-shell.tsx`, add the matching entry to its nav array (it uses `{ href, label, icon }` with no `tourId`):

```ts
  { href: "/exceptions", label: "Exceptions", icon: ClipboardCheck },
```

- [ ] **Step 7: Add the per-site workflow toggle to Settings**

In `frontend/src/app/settings/page.tsx`, add a section following the file's existing card/section pattern:

```tsx
function WorkflowSettings({ siteId }: { siteId: string }) {
  const qc = useQueryClient();
  const { data: rules } = useQuery({
    queryKey: ["workflow-rules", siteId],
    queryFn: () => api.getWorkflowRules(siteId),
    enabled: !!siteId,
  });

  const rule = rules?.find((r) => r.workflow_type === "dock_grn_match");
  const tolerance = Number(rule?.config?.quantity_tolerance_pct ?? 5);

  const save = useMutation({
    mutationFn: (body: { enabled: boolean; tolerance: number }) =>
      api.upsertWorkflowRule({
        site_id: siteId,
        workflow_type: "dock_grn_match",
        enabled: body.enabled,
        config: {
          quantity_tolerance_pct: body.tolerance,
          match_window_hours: Number(rule?.config?.match_window_hours ?? 24),
          min_goods_confidence: Number(rule?.config?.min_goods_confidence ?? 0.5),
        },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflow-rules", siteId] }),
  });

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4">
      <h3 className="text-sm font-medium text-zinc-200">Dock GRN auto-match</h3>
      <p className="mt-1 text-xs text-zinc-500">
        Compares what a dock camera sees arriving against the open purchase order for this
        site. Only runs on cameras whose role is set to “dock”.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={!!rule?.enabled}
            onChange={(e) => save.mutate({ enabled: e.target.checked, tolerance })}
          />
          Enabled
        </label>
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          Tolerance
          <input
            type="number"
            min={0}
            max={100}
            step={0.5}
            defaultValue={tolerance}
            onBlur={(e) =>
              save.mutate({ enabled: !!rule?.enabled, tolerance: Number(e.target.value) })
            }
            className="w-20 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1 text-sm"
          />
          %
        </label>
      </div>
      {save.isError ? (
        <p className="mt-2 text-sm text-red-400">
          {save.error instanceof Error ? save.error.message : "Could not save."}
        </p>
      ) : null}
    </div>
  );
}
```

Render it inside the settings page's site section, passing the currently-selected site id. Match whatever pattern that page already uses for choosing a site — do not add a second site selector.

- [ ] **Step 8: Build and verify in the browser**

```bash
cd frontend && npm run build
```

Expected: build passes with no type errors.

Then, with the backend running and the Task 8 seed data in place:

1. Open `/settings`, enable Dock GRN auto-match for a site, set tolerance to 5%.
2. Open `/exceptions`. Confirm the empty state renders when nothing has fired.
3. POST the mismatch event from Task 8 Step 4. Within 30 seconds the row appears under "Needs review".
4. Expand it. Confirm all three panes render: snapshot, document with `PO-4471`, and "Camera counted 12 against 20 expected".
5. Approve it with a note. Confirm it moves to the Approved tab and the note is shown.
6. Approve it again via the API directly and confirm a `409` surfaces as a visible error, not a silent no-op.
7. Check the Tally widget renders its stale banner when no successful sync exists.

- [ ] **Step 9: Self-review**

- Is any color hard-coded for light mode? (Dark only — check every `bg-`/`text-` class against the rest of the app.)
- Does the page ever render `discrepancy` values with `dangerouslySetInnerHTML` or otherwise trust server strings as markup? (It must not — `d.message` originates from backend template strings, but `document.payload` values come from a customer's Tally instance and are attacker-influenceable in principle. Confirm everything renders as text.)
- Does the query key include every filter? (`status` and `siteId` — a missing one shows stale results after a filter change.)
- Does the empty state tell the operator what to do, or just that there is nothing? (It should name the two prerequisites: a rule in Settings, and a camera with a role.)
- Does approving invalidate the list so the row actually moves? (`invalidateQueries({queryKey: ["workflow-exceptions"]})` — confirm the prefix matches the full key.)

- [ ] **Step 10: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/lib/api.ts frontend/src/components/exceptions/ frontend/src/app/exceptions/ frontend/src/components/layout/sidebar.tsx frontend/src/components/layout/app-shell.tsx frontend/src/app/settings/page.tsx
git commit -m "feat(frontend): add workflow exception queue and connector status"
```

---

## Phase 1 acceptance

Phase 1 is done when all of these hold at once, checked by hand:

- [ ] An event POSTed to `/internal/events` returns `201` only after its row is committed; a forced commit failure returns `503` and produces no WebSocket frame, no notification, and no workflow exception.
- [ ] Notification delivery happens after the response, visible as an `AlertHistory` row transitioning `queued` → `sent`.
- [ ] An event posted to one backend replica reaches a dashboard socket attached to a different replica.
- [ ] A site with no `workflow_rules` row produces no `workflow_exceptions` rows and a drained workflow queue.
- [ ] With the rule enabled and `PO-4471` synced: a 20-carton observation produces `auto_cleared` with a draft; a 12-carton observation produces `open` with `variance_pct: 40`; a missing document produces `no_matching_document`; two candidate documents with no legible ref produce `ambiguous_document`.
- [ ] A user in another org gets `404` and `total: 0` on every workflow endpoint, and so does a site-restricted user in the same org whose scope excludes the site.
- [ ] The Tally sweep skips unconfigured orgs silently and records an `error` row for a configured-but-unreachable one, without killing the scheduler.
- [ ] `TallyClient._parse` has been run against at least one real Tally export and the quantities verified by hand against the report (spec Section 9 gate — until this is done, no "audit-ready" or "reconciliation" claim to any prospect).
- [ ] `cd backend && uv run python3 -c "from app.main import app"` and `cd frontend && npm run build` both pass.

## Known limitations to carry into Phase 2

State these plainly rather than discovering them in a pilot:

1. **No unit reconciliation.** A carton count compared against a document whose quantity is in pieces produces a meaningless variance. `draft.counted_unit` records what was counted so a human can spot it, but nothing detects it.
2. **One observation per event, no aggregation across a delivery.** A truck unloaded over twenty minutes produces many events, each matched independently against the same PO. Phase 2 needs a delivery-session concept.
3. **Tally must be reachable from the backend.** The agent-bridge transport is designed for (the `Transport` protocol) but not built — see spec Appendix A.5.
4. **Goods counts come from a vision model with no ground truth.** Every number in a discrepancy is an estimate. The UI says "camera counted", never "received" — keep that wording; the footfall feature already established that estimates presented as counts are the thing that destroys trust in the product.
