# Guided Onboarding Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A non-technical person plugs in Ethernet and power, scans a QR code, picks cameras, and sees a genuine "protected" result in under 15 minutes.

**Architecture:** One customer-facing wizard driven by an explicit state machine
(`box_online → waiting_claim → paired → scanning → cameras_selected →
stream_verified → zones_saved → alert_verified → protected`). State is derived
server-side from facts already in Postgres/Redis and served by a single
`GET /api/agents/{agent_id}/onboarding-status` endpoint; the wizard renders
whatever state that returns and never keeps its own parallel copy. Discovery
becomes an intentional action (`scan_now` pushed down the existing agent
control WebSocket) rather than a scheduled interval the customer waits out.

**Tech Stack:** Go 1.21+ (agent), FastAPI + SQLAlchemy 2.0 async + Redis
(backend), Next.js 16 App Router + TanStack Query (frontend).

**Spec:** The user-supplied brief in the originating conversation, reproduced
in "Spec Summary" below. There is no separate design doc; this plan carries the
spec with it.

---

## Spec Summary

1. Pairing becomes "scan a QR code": crypto-secure six-digit code, QR containing
   a short-lived opaque claim URL, never the device token.
2. Delete the duplicate `/onboard` path; consolidate on the connect wizard.
3. `POST /api/agents/{agent_id}/scan` triggers discovery immediately.
4. Camera selection is NVR-first: one credential prompt, then a channel checklist.
5. Verify a real decoded video frame before asking the user to draw zones.
6. Reuse `ZonesEditor` as an optional, single-"Watch area" guided step.
7. Two distinct tests: a delivery test (notification reaches WhatsApp/email) and
   a physical walk-test (RTSP → detection → event → alert).
8. Only then package Docker and test on real CP Plus / Hikvision / Dahua hardware.

---

## Findings That Change The Spec

These were verified against the code before planning. Three of the spec's
premises are wrong or outdated; the plan follows the code, not the brief.

**1. `GET /api/agents/{agent_id}` is implemented — the "404" is stale.**
The spec says the `/onboard` test step "polls an endpoint that is not
implemented". It is implemented (`backend/app/api/agents.py:178`) and does
return `cameras_streaming` (`backend/app/schemas/agent.py:81`). The stale
`TODO(onboarding-22a/b)` comment at the top of
`frontend/src/app/onboard/steps/test.tsx:1` predates the backend catching up.

**The spec's conclusion is still right, for a better reason.** `cameras_streaming`
counts cameras whose `status == "online"`, and that status is heartbeat-derived:
`agent/pipeline/camera_worker.py::heartbeat_payload` reports `"online" if
self._running and self.stream.is_running`, which means *a stream object exists*,
not *a frame decoded*. So the existing test can pass on a camera that has never
produced a single frame. That is exactly why Task 6 introduces a real
first-frame signal — not because the endpoint is missing.

**2. `Camera.last_frame_at` already exists but does not mean what it says.**
The column is there (`backend/app/models/camera.py:42`), so no migration is
needed for the core signal. But `backend/app/api/internal.py:214` sets it on
*every* heartbeat for any camera not explicitly rejected — regardless of
whether `frames_processed` moved. The heartbeat payload already carries
`frames_processed` per camera; the backend just ignores it. Task 6 fixes the
field to mean "we have decoded at least one frame", which is a correctness fix
to existing data, not only new plumbing.

**3. `registry.request_signal` cannot carry `scan_now`.**
`backend/app/api/agent_control.py:70` is WebRTC-specific: it demands a
`signal_answer` with an `answer` field and raises `SignalError("agent returned
no answer")` otherwise. Scan is fire-and-forget (results return via the existing
`POST /api/agents/me/discovered`). Task 4 adds a separate `send_command`
rather than bending the signaling path.

**4. Two pre-existing duplicate package pairs.** `agent/internal/localui` and
`agent/internal/local_ui` both exist, as do `agent/internal/devicepair` and
`agent/internal/pairing`. The spec asks to delete one duplicate onboarding path;
these are the same disease in the agent. Task 2 resolves the ones this feature
touches and leaves the rest alone rather than silently expanding scope.

**5. V2 is where this must be built.** `NEXT_PUBLIC_NEW_UI=true` is set in
Vercel, and `frontend/src/components/layout/app-shell.tsx:66` redirects *every*
legacy route to `/app`. A wizard built at `/cameras/connect` (V1) would be
unreachable in the environment it is meant to serve. All frontend work targets
`/app/cameras/connect`, which already carries the three-path port.

---

## Global Constraints

- **Auth:** username/password, opaque Redis-backed tokens. Never JWT. Agent uses
  its long-lived device token as `Authorization: Bearer`.
- **Multi-tenancy:** every query filters by `org_id` **and** applies
  `scope_to_sites(...)`. Super-admin bypass keys off `role == "super_admin"`,
  **never** off `org_id` being null.
- **Dark mode only.** V2 pages use the oklch tokens in
  `frontend/src/components/v2/ui.tsx`. Do not re-derive the palette.
- **No credential persistence.** NVR username/password may live only in Redis
  with a TTL, only for the duration of an ONVIF resolve job. Never in Postgres,
  never in a log line.
- **No new secrets on customer hardware.** The QR payload carries an opaque
  one-time claim token, never the device token.
- **Verification:** `cd frontend && npm run build` must pass with zero type
  errors. `cd backend && uv run python -c "from app.main import app"` must
  import cleanly. `cd agent && go build ./...` must pass.
- **No TDD.** Per standing user preference, implement directly, then self-review
  each task for correctness, simplicity, SOLID, and flow. Do not write pytest
  or Go test files unless a task explicitly says to.
- **Commits:** one per task, at the end. Do not commit mid-task.

---

## File Structure

**Agent (Go)**
- `agent/internal/devicepair/client.go` — MODIFY: crypto-secure 6-digit code.
- `agent/internal/devicepair/display.go` — CREATE: terminal banner + QR render.
- `agent/internal/localui/handlers.go` — MODIFY: serve the pairing QR page.
- `agent/internal/control/commands.go` — CREATE: handle `scan_now` from backend.

**Backend (Python)**
- `backend/app/api/devices.py` — MODIFY: issue + redeem opaque claim tokens.
- `backend/app/services/device_provision_service.py` — MODIFY: claim-token store.
- `backend/app/api/agent_control.py` — MODIFY: add `send_command`.
- `backend/app/api/agents.py` — MODIFY: add `POST /{agent_id}/scan`,
  `GET /{agent_id}/onboarding-status`, NVR channel resolve.
- `backend/app/api/internal.py` — MODIFY: `last_frame_at` gated on frames.
- `backend/app/services/onboarding_status_service.py` — CREATE: state machine.
- `backend/app/api/alerts.py` — MODIFY: add test-notification endpoint.

**Frontend (TypeScript)**
- `frontend/src/app/app/cameras/connect/page.tsx` — MODIFY: wizard host.
- `frontend/src/components/v2/onboarding/` — CREATE: one file per wizard step.
- `frontend/src/app/onboard/page.tsx` — MODIFY: redirect to the wizard.

---

## Task 1: Onboarding state machine, server-side

The wizard must not invent state in React. Everything downstream reads this.

**Files:**
- Create: `backend/app/services/onboarding_status_service.py`
- Modify: `backend/app/api/agents.py` (add route)
- Modify: `backend/app/schemas/agent.py` (add response schemas)

**Interfaces:**
- Consumes: `Agent`, `Camera` models; `_load_agent_for_user` at
  `backend/app/api/agents.py:163`.
- Produces: `GET /api/agents/{agent_id}/onboarding-status` →
  `OnboardingStatusResponse`, consumed by Tasks 4, 6, 7, 8.

- [ ] **Step 1: Add the response schemas**

In `backend/app/schemas/agent.py`:

```python
class OnboardingCameraState(BaseModel):
    camera_id: uuid.UUID
    name: str
    status: str                      # online | offline | error | unassigned
    first_frame_at: datetime | None = None
    snapshot_url: str | None = None
    zones_count: int = 0
    failure_reason: str | None = None


class OnboardingStatusResponse(BaseModel):
    agent_id: uuid.UUID
    state: str                       # see STATES below
    agent_online: bool
    last_seen_at: datetime | None = None
    discovered_count: int = 0
    cameras: list[OnboardingCameraState] = []
    verified_camera_count: int = 0
    failure_reason: str | None = None
```

- [ ] **Step 2: Write the state derivation service**

Create `backend/app/services/onboarding_status_service.py`:

```python
"""Derives onboarding state from facts already in the database.

The wizard renders whatever this returns. It deliberately keeps no state of
its own: a customer who refreshes, or resumes on their phone after starting
on a laptop, must land on the same step. Anything stored in React would be
lost on refresh and would drift from reality the moment a box went offline.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models.agent import Agent
from app.models.camera import Camera

# Ordered. Each state is "the furthest point reached", never a step counter.
STATES = [
    "waiting_claim",
    "paired",
    "scanning",
    "cameras_selected",
    "stream_verified",
    "zones_saved",
    "alert_verified",
    "protected",
]

# An agent is considered offline once it misses this much heartbeat. Matches
# the fleet sweep's staleness window so the two surfaces never disagree.
AGENT_STALE_AFTER = timedelta(seconds=90)


def _discovery_key(agent_id: uuid.UUID) -> str:
    return f"agent:discovered:{agent_id}"


def _walk_test_key(agent_id: uuid.UUID) -> str:
    return f"agent:walktest_passed:{agent_id}"


class OnboardingStatusService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def status(self, agent: Agent) -> dict:
        now = datetime.now(timezone.utc)
        last_seen = agent.last_seen_at
        if last_seen is not None and last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        agent_online = last_seen is not None and (now - last_seen) < AGENT_STALE_AFTER

        rows = await self.db.execute(
            select(Camera).where(
                Camera.agent_id == agent.id,
                Camera.deleted_at.is_(None),
            )
        )
        cameras = list(rows.scalars().all())

        redis = await get_redis()
        raw_discovered = await redis.get(_discovery_key(agent.id))
        discovered_count = 0
        if raw_discovered:
            import json
            try:
                discovered_count = len(json.loads(raw_discovered).get("devices", []))
            except (ValueError, AttributeError):
                discovered_count = 0

        walk_passed = bool(await redis.get(_walk_test_key(agent.id)))

        camera_states = [
            {
                "camera_id": c.id,
                "name": c.name,
                "status": c.status,
                "first_frame_at": c.last_frame_at,
                "snapshot_url": None,  # filled by the route, needs signing
                "zones_count": len(c.detection_zones or []),
                "failure_reason": self._camera_failure(c),
            }
            for c in cameras
        ]

        verified = [c for c in cameras if c.last_frame_at is not None]
        zoned = [c for c in verified if (c.detection_zones or [])]

        state = self._derive(
            agent_online=agent_online,
            camera_count=len(cameras),
            verified_count=len(verified),
            zoned_count=len(zoned),
            walk_passed=walk_passed,
            discovered_count=discovered_count,
        )

        return {
            "agent_id": agent.id,
            "state": state,
            "agent_online": agent_online,
            "last_seen_at": last_seen,
            "discovered_count": discovered_count,
            "cameras": camera_states,
            "verified_camera_count": len(verified),
            "failure_reason": None if agent_online else "Box is not reporting in.",
        }

    def _derive(
        self,
        *,
        agent_online: bool,
        camera_count: int,
        verified_count: int,
        zoned_count: int,
        walk_passed: bool,
        discovered_count: int,
    ) -> str:
        # Walked backwards on purpose: report the furthest point actually
        # reached, so a customer who adds a second camera later is not
        # dragged back to "scanning".
        if walk_passed and zoned_count > 0:
            return "protected"
        if walk_passed:
            return "alert_verified"
        if zoned_count > 0:
            return "zones_saved"
        if verified_count > 0:
            return "stream_verified"
        if camera_count > 0:
            return "cameras_selected"
        if discovered_count > 0:
            return "scanning"
        if agent_online:
            return "paired"
        return "waiting_claim"

    def _camera_failure(self, c: Camera) -> str | None:
        if c.status == "unassigned":
            return "No appliance is analysing this camera."
        if c.status == "error":
            return "The box could not open this camera's stream."
        if c.rtsp_url is None:
            return "Still resolving this camera's stream address."
        return None
```

- [ ] **Step 3: Add the route**

In `backend/app/api/agents.py`, after `get_agent`:

```python
@router.get("/{agent_id}/onboarding-status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingStatusResponse:
    """One source of truth for the onboarding wizard's current step."""
    agent = await _load_agent_for_user(agent_id, user, db)
    svc = OnboardingStatusService(db)
    payload = await svc.status(agent)
    for cam in payload["cameras"]:
        cam["snapshot_url"] = await signed_latest_frame_url(cam["camera_id"])
    return OnboardingStatusResponse(**payload)
```

Import `OnboardingStatusService` and `OnboardingStatusResponse` at the top.
Reuse the existing signed-URL helper that `GET /api/cameras/{id}/latest-frame`
already uses; if it is inline in `cameras.py`, extract it to
`backend/app/services/snapshot_urls.py::signed_latest_frame_url(camera_id)` and
import it from both places rather than duplicating the signing logic.

- [ ] **Step 4: Verify it imports and self-review**

Run: `cd backend && uv run python -c "from app.main import app; print('ok')"`
Expected: `ok`

Self-review: is `_derive` total (every input combination returns a state)? Does
every query filter by the agent, which `_load_agent_for_user` has already
org-scoped? Is any credential or token in the response?

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/onboarding_status_service.py backend/app/schemas/agent.py backend/app/api/agents.py
git commit -m "feat(onboarding): derive onboarding state server-side"
```

---

## Task 2: Consolidate the duplicate onboarding path

Spec build-order item 1. Do this first — every later task otherwise has to be
done twice.

**Files:**
- Modify: `frontend/src/app/onboard/page.tsx`
- Delete: `frontend/src/app/onboard/steps/install.tsx`, `pair.tsx`,
  `discover.tsx`, `test.tsx`

**Interfaces:**
- Produces: `/onboard` permanently redirects to `/app/cameras/connect`.

- [ ] **Step 1: Replace the page with a redirect**

Replace the entire contents of `frontend/src/app/onboard/page.tsx`:

```tsx
import { redirect } from "next/navigation";

/**
 * The old four-step installer is gone. It duplicated /app/cameras/connect
 * with an incompatible model (dashboard-generated code pasted into a local
 * agent UI, versus the device-initiated code the box now prints itself),
 * and its final step verified the wrong thing.
 *
 * Kept as a redirect rather than deleted: this URL is in pilot install
 * notes and support replies, and a 404 to a customer mid-install is worse
 * than an extra file.
 */
export default function OnboardRedirect() {
  redirect("/app/cameras/connect");
}
```

- [ ] **Step 2: Delete the orphaned step components**

```bash
git rm frontend/src/app/onboard/steps/install.tsx \
       frontend/src/app/onboard/steps/pair.tsx \
       frontend/src/app/onboard/steps/discover.tsx \
       frontend/src/app/onboard/steps/test.tsx
```

- [ ] **Step 3: Confirm nothing else imports them**

Run: `cd frontend && grep -rn "onboard/steps" src || echo "no references"`
Expected: `no references`

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build`
Expected: `✓ Compiled successfully`, and `/onboard` still listed as a route.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/onboard/
git commit -m "refactor(onboarding): collapse /onboard into the connect wizard"
```

---

## Task 3: Secure six-digit pairing with a QR claim link

Spec build-order item 2.

**Files:**
- Modify: `agent/internal/devicepair/client.go:71-74`
- Create: `agent/internal/devicepair/display.go`
- Modify: `backend/app/services/device_provision_service.py`
- Modify: `backend/app/api/devices.py`
- Modify: `agent/go.mod` (add QR library)

**Interfaces:**
- Consumes: `POST /api/devices/provision` (exists,
  `backend/app/api/devices.py:29`).
- Produces: `ProvisionResponse.claim_url`; `POST /api/devices/claim` accepts
  either `code` or `claim_token`.

- [ ] **Step 1: Replace the insecure code generator**

`agent/internal/devicepair/client.go` currently does
`fmt.Sprintf("%04d", rand.Intn(10000))` with `math/rand` — 10,000 possibilities
from a non-cryptographic source. Replace:

```go
// GenerateCode returns a cryptographically secure 6-digit string.
//
// math/rand was wrong here twice over: it is not cryptographically secure,
// and 4 digits is a 10,000-value space that a claim endpoint can be walked
// through. Six digits from crypto/rand widens it 100x and removes the
// predictability; the backend's rate limit covers the rest.
func GenerateCode() (string, error) {
	n, err := cryptorand.Int(cryptorand.Reader, big.NewInt(1_000_000))
	if err != nil {
		return "", fmt.Errorf("generate pairing code: %w", err)
	}
	return fmt.Sprintf("%06d", n.Int64()), nil
}
```

Imports: replace `"math/rand"` with `cryptorand "crypto/rand"` and `"math/big"`.
Update every caller to handle the new error return; do not swallow it — a box
that cannot generate a secure code must fail loudly, not fall back.

- [ ] **Step 2: Widen the backend's code validation**

In `backend/app/services/device_provision_service.py`, find the code-format
validation and accept 6 digits. Codes are compared after
`.upper().removeprefix("NW-").strip()` (`backend/app/api/devices.py:104`), which
already handles the display prefix. Accept both 4 and 6 digits during rollout so
a box on the old firmware can still pair, and add:

```python
# 4-digit codes are legacy: boxes flashed before the crypto/rand change.
# Accept them until the pilot fleet is confirmed upgraded, then delete this.
LEGACY_CODE_LENGTH = 4
CODE_LENGTH = 6
```

- [ ] **Step 3: Issue an opaque one-time claim token**

In `device_provision_service.py`, when provisioning, also mint:

```python
claim_token = secrets.token_urlsafe(32)
```

Store it in Redis as `device:claim_token:{claim_token} -> device_id` with the
same TTL as the pairing code, and return it on the provision response. It is a
lookup handle, not a credential: possessing it lets an *authenticated* customer
claim the box, exactly as typing the six digits does. It must never be
confused with the device token.

Add to `ProvisionResponse` in `backend/app/schemas/device.py`:

```python
claim_url: str          # https://app.../connect?claim=<opaque>
```

Build it from a new `settings.app_public_url`, defaulting to
`http://localhost:3000` for local dev.

- [ ] **Step 4: Accept the claim token at the claim endpoint**

In `backend/app/api/devices.py::claim_device`, accept either form. `ClaimRequest`
gains `claim_token: str | None = None` and `code` becomes optional, with a
validator requiring exactly one. Resolve `claim_token` → `device_id` via Redis,
then delete the key immediately on success so it is genuinely single-use.
Rate-limit the claim endpoint by IP on the existing Redis limiter — the six-digit
space is only meaningful if it cannot be walked.

- [ ] **Step 5: Print the QR on the box**

Add `github.com/skip2/go-qrcode` to `agent/go.mod`. Create
`agent/internal/devicepair/display.go`:

```go
package devicepair

import (
	"fmt"
	"strings"

	qrcode "github.com/skip2/go-qrcode"
)

// Banner renders the pairing screen for a terminal or HDMI console.
//
// Both the QR and the digits are shown deliberately: the QR is the fast
// path, and the digits are the fallback for a customer whose phone camera
// will not focus on a CRT, a glare-lit monitor, or a serial console.
func Banner(code, claimURL string) string {
	qr, err := qrcode.New(claimURL, qrcode.Medium)
	var art string
	if err != nil {
		// A QR that will not render must not take the box down — the
		// six digits alone are still a complete pairing path.
		art = "(QR unavailable — use the code below)"
	} else {
		art = qr.ToSmallString(false)
	}

	spaced := code
	if len(code) == 6 {
		spaced = fmt.Sprintf("%s %s", code[:3], code[3:])
	}

	var b strings.Builder
	b.WriteString("\n  Nightwatch setup\n\n")
	b.WriteString(art)
	b.WriteString("\n  Scan this QR code or visit nightwatch.ai/connect\n")
	b.WriteString(fmt.Sprintf("\n  Code: %s\n\n", spaced))
	return b.String()
}
```

Call it from the pairing path in `agent/cmd/agent/main.go` where the current
`DEVICE PAIRING CODE:` line is logged, and keep printing until claimed.

- [ ] **Step 6: Serve the same banner at the local page**

`agent/internal/localui` already runs an HTTP server
(`agent/internal/localui/server.go:20`). Add a `/` handler that renders the QR
as an inline PNG data URI plus the spaced digits, so a customer on the LAN can
reach it at `http://nightwatch.local` when there is no display attached.

Note: `agent/internal/local_ui` also exists and is a near-duplicate of
`localui`. Do not merge them in this task — check which one
`agent/cmd/agent/main.go:32` actually imports (it is `localui`), use that, and
leave the other for a separate cleanup so this task stays reviewable.

- [ ] **Step 7: Verify**

Run: `cd agent && go build ./... && go vet ./...`
Expected: clean.
Run: `cd backend && uv run python -c "from app.main import app; print('ok')"`

Self-review: is the device token ever in the QR payload or the URL? Is the
claim token deleted on use? Does a code-generation failure crash loudly?

- [ ] **Step 8: Commit**

```bash
git add agent/ backend/app/api/devices.py backend/app/schemas/device.py backend/app/services/device_provision_service.py backend/app/config.py
git commit -m "feat(pairing): crypto-secure 6-digit codes and QR claim links"
```

---

## Task 4: Trigger discovery on demand

Spec build-order item 3.

**Files:**
- Modify: `backend/app/api/agent_control.py`
- Modify: `backend/app/api/agents.py`
- Create: `agent/internal/control/commands.go`

**Interfaces:**
- Consumes: `registry` from `backend/app/api/agent_control.py:117`.
- Produces: `ControlRegistry.send_command(agent_id, msg) -> None`;
  `POST /api/agents/{agent_id}/scan` → `{"status": "scanning"}`.

- [ ] **Step 1: Add a fire-and-forget command channel**

`request_signal` cannot be reused: it requires a `signal_answer` carrying an
`answer` field and raises otherwise. Add to `ControlRegistry`:

```python
    async def send_command(self, agent_id: uuid.UUID, msg: dict) -> None:
        """Push a fire-and-forget command to an agent.

        Distinct from request_signal, which is a WebRTC round-trip and
        insists on an `answer` in the reply. Commands like scan_now have no
        synchronous result — discovery lands later via
        POST /api/agents/me/discovered — so waiting for one would guarantee
        a timeout on every call.
        """
        ws = self.get(agent_id)
        if ws is None:
            raise ConnectionError("agent not connected")
        try:
            await ws.send_json(msg)
        except Exception as e:
            raise ConnectionError(f"agent socket send failed: {e}") from e
```

- [ ] **Step 2: Add the scan route**

In `backend/app/api/agents.py`:

```python
@router.post("/{agent_id}/scan", status_code=status.HTTP_202_ACCEPTED)
async def trigger_scan(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ask a paired box to run ONVIF discovery right now.

    202, not 200: the scan has been asked for, not completed. Results arrive
    asynchronously at POST /api/agents/me/discovered and surface through the
    onboarding-status endpoint.
    """
    agent = await _load_agent_for_user(agent_id, user, db)
    try:
        await registry.send_command(agent.id, {"type": "scan_now"})
    except ConnectionError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The box is not connected right now. Check its power and network.",
        )
    return {"status": "scanning"}
```

- [ ] **Step 3: Handle scan_now on the agent**

Create `agent/internal/control/commands.go` with a handler that, on
`{"type":"scan_now"}`, runs the same discovery-and-report the interval reporter
already runs (`agent/internal/discovery/report.go`), then returns. Guard it with
a mutex so two rapid scan requests do not run concurrent probes, and rate-limit
to one scan per 10 seconds — a customer mashing "Scan again" must not flood
the LAN with WS-Discovery multicast.

Wire it into the control socket's receive loop next to the existing
`signal_offer` handling.

- [ ] **Step 4: Verify**

Run: `cd agent && go build ./...` and
`cd backend && uv run python -c "from app.main import app; print('ok')"`

Self-review: does `send_command` normalise every transport failure to
`ConnectionError` like `request_signal` does? Is the 409 message written for a
customer, not an engineer?

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/agent_control.py backend/app/api/agents.py agent/internal/control/
git commit -m "feat(onboarding): scan_now command for immediate LAN discovery"
```

---

## Task 5: NVR-first camera selection

Spec build-order item 4.

**Files:**
- Modify: `backend/app/api/agents.py` (new resolve-channels route)
- Modify: `agent/internal/discovery/` (ONVIF profile enumeration)

**Interfaces:**
- Produces: `POST /api/agents/{agent_id}/nvr-channels` with
  `{xaddr, username, password}` → `202`, results readable from
  `GET /api/agents/{agent_id}/discover`.

- [ ] **Step 1: Add the credential-scoped channel resolve route**

```python
@router.post("/{agent_id}/nvr-channels", status_code=status.HTTP_202_ACCEPTED)
async def resolve_nvr_channels(
    agent_id: uuid.UUID,
    payload: NvrChannelsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Enumerate an NVR's channels using credentials supplied once.

    The credentials are written to Redis with a short TTL purely so the
    agent's next poll can pick them up, and are deleted by the agent on
    read. They are never written to Postgres and never logged: an NVR
    password is the customer's whole security perimeter, and a support
    engineer reading logs must not be able to see it.
    """
    agent = await _load_agent_for_user(agent_id, user, db)
    redis = await get_redis()
    key = f"agent:nvr_creds:{agent.id}"
    await redis.setex(
        key,
        NVR_CREDS_TTL_SECONDS,   # 120
        json.dumps({
            "xaddr": payload.xaddr,
            "username": payload.username,
            "password": payload.password,
        }),
    )
    try:
        await registry.send_command(agent.id, {"type": "resolve_channels"})
    except ConnectionError:
        await redis.delete(key)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The box is not connected right now.",
        )
    return {"status": "resolving"}
```

Add `NVR_CREDS_TTL_SECONDS = 120` and the `NvrChannelsRequest` schema
(`xaddr: str`, `username: str`, `password: str`). Mark the password field so it
never renders in FastAPI's OpenAPI examples.

- [ ] **Step 2: Enumerate channels on the agent**

In the agent, on `resolve_channels`: `GET` the creds key from Redis via a new
authenticated backend endpoint (the agent has no direct Redis access), call
ONVIF `GetProfiles` + `GetStreamUri` per profile against the supplied `xaddr`,
and report the resulting channel list to `POST /api/agents/me/discovered` with a
`channels` array per device. Delete the creds key immediately after use.

Never log the password. When logging failures, log the `xaddr` and the ONVIF
fault code only.

- [ ] **Step 3: Verify and self-review**

Run: `cd agent && go build ./...`, `cd backend && uv run python -c "from app.main import app"`

Self-review: grep the diff for any log line that could interpolate the password.
Confirm the Redis key has a TTL on every path, including the error path.

- [ ] **Step 4: Commit**

```bash
git add backend/ agent/
git commit -m "feat(onboarding): NVR channel enumeration from one credential prompt"
```

---

## Task 6: Make "stream verified" mean a decoded frame

Spec build-order item 5. This is also a correctness fix to existing data — see
Finding 2.

**Files:**
- Modify: `backend/app/api/internal.py:212-215`

**Interfaces:**
- Produces: `Camera.last_frame_at` set only when frames were actually decoded.
  Task 1's `stream_verified` state depends on this being truthful.

- [ ] **Step 1: Gate last_frame_at on real frame progress**

The heartbeat payload already carries `frames_processed` per camera
(`agent/pipeline/camera_worker.py::heartbeat_payload`). The backend currently
ignores it and stamps `last_frame_at` on every non-rejected report. Replace the
block at `backend/app/api/internal.py:212-215`:

```python
        camera.status = "unassigned" if raw_id in rejected else status_value
        # last_frame_at must mean "we have decoded video from this camera",
        # not "the box mentioned this camera". Onboarding shows the customer
        # a green "Camera connected" off this field, and a pipeline that has
        # opened a stream but never decoded a frame is exactly the failure
        # that check exists to catch.
        if raw_id not in rejected and frames_by_camera.get(raw_id, 0) > 0:
            camera.last_frame_at = now
        camera.worker_id = body.worker_id
```

Build `frames_by_camera` alongside the existing `footfall_by_camera` parsing,
reading `frames_processed` from each camera's heartbeat entry.

- [ ] **Step 2: Verify**

Run: `cd backend && uv run python -c "from app.main import app; print('ok')"`

Self-review: `frames_processed` is cumulative, not per-interval — confirm
`> 0` is the right test (it is: any nonzero total means at least one frame has
ever been decoded, which is precisely the onboarding question). Confirm cameras
absent from a heartbeat are untouched rather than reset.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/internal.py
git commit -m "fix(onboarding): last_frame_at only when frames actually decoded"
```

---

## Task 7: Test notification and physical walk-test

Spec build-order item 7.

**Files:**
- Modify: `backend/app/api/alerts.py`
- Modify: `backend/app/services/onboarding_status_service.py`

**Interfaces:**
- Produces: `POST /api/alerts/test` → `{"delivered": bool, "detail": str}`;
  `GET /api/agents/{agent_id}/walk-test` → `{"passed": bool, "event_id": ...}`.

- [ ] **Step 1: Add the delivery test**

In `backend/app/api/alerts.py`, add a route that sends a system-labelled
notification through the existing alert engine to the caller's configured
WhatsApp/email contacts. It must not invoke Gemini and must not create an
`Event` row — it proves the delivery channel works and nothing else. Label the
message body explicitly as a test so a customer never mistakes it for a real
detection. Rate-limit to a few per hour per org.

- [ ] **Step 2: Add walk-test detection**

Add a route that looks for any `Event` on the given agent's cameras with a
`timestamp` newer than a `since` query parameter, and returns the first match.
The frontend polls it for up to two minutes. On the first pass, write
`agent:walktest_passed:{agent_id}` to Redis (no TTL) so Task 1's state machine
can report `alert_verified` / `protected` on later visits.

- [ ] **Step 3: Verify and commit**

```bash
cd backend && uv run python -c "from app.main import app; print('ok')"
git add backend/
git commit -m "feat(onboarding): notification delivery test and walk-test verification"
```

---

## Task 8: The wizard UI

Spec build-order items 4 (UI half), 6, and 7 (UI half).

**Files:**
- Modify: `frontend/src/app/app/cameras/connect/page.tsx`
- Create: `frontend/src/components/v2/onboarding/WizardHost.tsx`
- Create: `frontend/src/components/v2/onboarding/StepScanning.tsx`
- Create: `frontend/src/components/v2/onboarding/StepSelectCameras.tsx`
- Create: `frontend/src/components/v2/onboarding/StepVerifyStream.tsx`
- Create: `frontend/src/components/v2/onboarding/StepWatchArea.tsx`
- Create: `frontend/src/components/v2/onboarding/StepProtected.tsx`

**Interfaces:**
- Consumes: `GET /api/agents/{id}/onboarding-status` (Task 1),
  `POST /api/agents/{id}/scan` (Task 4), `POST /api/agents/{id}/nvr-channels`
  (Task 5), `POST /api/alerts/test` (Task 7).
- Consumes: `ZonesEditor` at
  `frontend/src/components/cameras/ZonesEditor.tsx:8`, whose current signature
  is `{ camera: Camera; onClose: () => void }`.

- [ ] **Step 1: Add the API client methods**

In `frontend/src/lib/api.ts`, add typed methods for each route above, and the
matching response interfaces in `frontend/src/types/index.ts`. Follow the
existing method style exactly; do not construct URLs inline in components.

- [ ] **Step 2: Build the wizard host**

`WizardHost` polls `onboarding-status` every 3s and renders the step matching
`state`. It holds **no** step state of its own — the server's `state` field is
the only driver, so a refresh resumes exactly where the customer was. Render a
persistent progress rail using the `STATES` order from Task 1.

- [ ] **Step 3: Build the scanning step**

Renders the spec's progress copy verbatim:

```
✓ Nightwatch box connected
⏳ Looking for your NVR…
✓ Found CP Plus NVR — 8 channels
```

with a "Scan again" button calling `POST /scan`. Surface the 409 body as the
customer-facing message rather than a generic failure.

- [ ] **Step 4: Build NVR-first selection**

One credential form per discovered NVR (`Username` / `Password` / `Connect`),
then a channel checklist with a `Protect N cameras` button. The password input
must be `type="password"` and must never be written to component state that is
serialised anywhere (no query keys, no localStorage).

- [ ] **Step 5: Build stream verification**

Shows a per-camera row with a spinner until `first_frame_at` is non-null, then
the `snapshot_url` thumbnail and "Camera connected". Show `failure_reason`
verbatim when present. Do not advance automatically until at least one camera
verifies — this is the step that catches a wrong NVR password.

- [ ] **Step 6: Build the watch-area step**

Wrap the existing `ZonesEditor`. Copy, verbatim from the spec:

```
Which area should Nightwatch watch?
[ Draw area ]  [ Skip for now ]

Recommended: draw only entrances, gates, doors, and restricted areas.
```

Constrain to a single zone named `Watch area` for pilots. `ZonesEditor` takes
`{ camera, onClose }` and saves via `api.updateCamera(camera.id, {
detection_zones })` internally — do not duplicate that save; pass a wrapper
`onClose` that re-polls onboarding status.

- [ ] **Step 7: Build the two tests**

"Send test notification" → `POST /api/alerts/test`, then the walk-test poll with
the spec's copy:

```
✓ Notification delivered
Now walk through Main Gate.
⏳ Waiting for a real camera event…
✓ Person detected — Main Gate is protected
```

Time out at two minutes with a retry, never a dead end.

- [ ] **Step 8: Build and self-review**

Run: `cd frontend && npm run build`
Expected: `✓ Compiled successfully`.

Self-review: does any component keep step state that the server also owns? Is
the NVR password anywhere it could be persisted? Does every step have a loading,
empty, and error state per `frontend/CLAUDE.md`?

- [ ] **Step 9: Commit**

```bash
git add frontend/
git commit -m "feat(onboarding): guided wizard driven by server-side state"
```

---

## Task 9: Package and test on real hardware

Spec build-order item 8. Do not start this before Tasks 1-8 are merged.

- [ ] **Step 1: Single Docker image**

Build one image that runs the Go agent and supervises the Python pipeline, per
the existing `agent/Dockerfile`. Verify a cold start with no config produces the
QR banner on stdout within 10 seconds.

- [ ] **Step 2: Walk the full flow on a CP Plus NVR**

Time it end to end from power-on to `protected`. The target is 15 minutes for a
non-technical operator. Record where the time actually goes.

- [ ] **Step 3: Repeat on Hikvision and Dahua**

Record per-brand ONVIF quirks in
`docs/superpowers/specs/2026-05-28-home-camera-plugin-design.md`.

- [ ] **Step 4: Update docs**

Update `CLAUDE.md` / `AGENTS.md` (mirrors — edit both) status sections, and
remove the "No end-to-end test against a real camera" entry from Known Gaps
once it is genuinely done.

---

## Self-Review Notes

**Spec coverage.** Build-order items 1→Task 2, 2→Task 3, 3→Task 4, 4→Tasks 5+8,
5→Tasks 6+8, 6→Task 8, 7→Tasks 7+8, 8→Task 9. The state machine itself is
Task 1, which the spec implies but does not list.

**Deliberate deviations, all recorded in Findings above:** the `/onboard` 404 is
stale, so Task 2 is justified by duplication rather than breakage;
`last_frame_at` needs fixing rather than adding; `request_signal` cannot carry
commands; the UI targets V2 because V1 is unreachable behind the flag.

**Known risk.** Task 5 puts an NVR password through Redis. The spec suggests
encrypting it to the agent's public key as a later hardening step; that is not
in this plan. The mitigation here is a 120s TTL, delete-on-read, and no logging.
If pilots go beyond trusted installers, do the pubkey encryption before then.
