# Agentic Step-Sequence Compiler — Design

## Problem

Authoring a `step_sequence` today requires the operator to manually build an ordered list of (zone, pose, timeout) steps through `SequenceEditor.tsx` — one dropdown/select at a time — and manually create an accompanying alert rule if they want to be notified. Competitors in this space (OpenVector) let a user describe the procedure they want monitored in plain English, get asked clarifying questions when the description is ambiguous, and end up with a working configuration without touching the underlying schema.

## Goal

Replace the manual-only authoring path with a conversational one, embedded in the existing `SequenceEditor`:
1. User describes the procedure in a chat box (e.g. "flag if someone leaves without paying at the counter and text the manager").
2. The system either asks a clarifying question (ambiguous zone, missing notification target) or, once it has enough information, produces a draft: a `step_sequence` and, if implied, an accompanying `alert_rule`.
3. The draft populates the existing editor form for review — nothing is ever written to the DB by this feature directly. The user still hits the same **Save** button that already exists, which fires the same `PATCH /cameras/{id}` (and, if a notification was requested, `POST /api/alerts/rules`) that a fully manual flow would.

The chat is the on-ramp; the existing form + Save button remain the only thing that actually persists anything. This keeps the "agentic" part bounded to config assembly, not to unsupervised action-taking.

## Non-goals

- Building a new generic external-action/integration engine (custom auth, templated payloads to arbitrary POS/CRM systems, credential storage). Notifications reuse the existing `alert_rules` + `notification_service.py` infrastructure (WhatsApp/Gupshup, email/SendGrid, HMAC-signed webhook) exactly as it works for manually-created rules today.
- Multi-step/chained actions ("update CRM, then log, then notify") — one generated rule, one set of channels, matching what `alert_rules` already supports.
- Persisting anything from the conversation itself — the model only ever produces a draft; a human always confirms via the existing Save button.
- Any change to how `step_sequence`/`alert_rules` are validated, stored, or consumed downstream — this feature only ever produces input that flows through `_validate_step_sequence`, `CreateAlertRuleRequest`, and existing editor state, all unchanged.

## Architecture

Conversation state is **stateless on the backend** — the frontend holds the full message history and resends it every turn, the same shape as any simple LLM chat integration. No new session storage.

```
User sends a message in SequenceEditor's chat panel
  → POST /api/cameras/{id}/compile-sequence  { messages: [{role, content}, ...] }
  → backend: SequenceCompilerClient.turn(messages, zone_names, pose_labels, whatsapp_contacts_configured)
      → SpendTracker.try_charge(org_id, cost) — same per-org daily cap as digests, charged every turn
          → if False: return { type: "question", message: "Daily AI budget reached — build this manually, or try again tomorrow." }
      → Gemini 2.5 Flash, text-only, structured-JSON prompt, grounded in real zone names + pose labels + whether WhatsApp contacts exist
      → parse JSON: { "type": "question", "message": string }  OR  { "type": "draft", "steps": [...], "alert_rule": {...}|null }
      → if type == "draft": validate against _validate_step_sequence; on failure, one corrective re-prompt (same turn); if still invalid, return as "draft" anyway with warnings
  ← { type: "question", message } | { type: "draft", steps, alert_rule, warnings }
  → frontend appends the response to the chat thread
  → on "draft": populate the existing steps/alert_rule editor state for review — Save behaves exactly as it does for a fully manual entry
```

**Turn cap:** 5 exchanges per conversation. On the 5th user turn, the prompt is amended with an explicit instruction: "You must respond with a draft now, not another question — fill in your best guess for anything still unclear and list it in warnings instead." This bounds both cost and the chance of a conversation looping without resolving.

## Backend

### New service: `backend/app/services/sequence_compiler/gemini_client.py`

```python
SYSTEM_PROMPT = """You help configure a camera's step-sequence tracker through conversation.
A step_sequence is an ordered list of steps; each step has a zone (must be one of the
camera's existing zone names, given below — never invent one), an optional pose (must be
exactly one of: standing, bending, crouching, sitting, reaching, or null for "any pose"),
and an optional max_seconds timeout.

If the user's request implies they want to be notified (e.g. "text the manager", "email
security", "call our system"), also draft an alert_rule: event_types drawn from
{step_skipped, step_timeout, sequence_completed}, min_severity, and notify_channels drawn
from {whatsapp, email, webhook}. You cannot invent a phone number, email address, or URL —
only infer the channel type from language.

If the description is genuinely ambiguous (an unclear zone reference, a notification
channel with no clear target and no existing default) respond with a clarifying question:
{"type": "question", "message": "<one specific question>"}

Otherwise respond with the final draft:
{"type": "draft", "steps": [...], "alert_rule": {...} | null}

Respond ONLY with JSON, no markdown, no commentary. Ask at most one question at a time."""


class SequenceCompilerClient:
    def __init__(self, client, model: str = "gemini-2.5-flash"):
        self.client = client
        self.model = model

    def _build_context(self, zone_names: list[str], whatsapp_configured: bool, force_draft: bool) -> str:
        ctx = (
            f"Available zones for this camera: {zone_names}\n"
            f"Org has WhatsApp contacts configured: {whatsapp_configured}\n"
        )
        if force_draft:
            ctx += "\nThis is the final turn. Respond with a draft now, not a question."
        return ctx

    async def turn(self, messages: list[dict], zone_names: list[str], whatsapp_configured: bool, force_draft: bool = False) -> dict:
        contents = [{"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + self._build_context(zone_names, whatsapp_configured, force_draft)}]}]
        for m in messages:
            contents.append({"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]})

        response = await self.client.aio.models.generate_content(model=self.model, contents=contents)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        return json.loads(text)
```

### New route: `backend/app/api/cameras.py`

```python
class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class CompileSequenceRequest(BaseModel):
    messages: list[ChatMessage]


@router.post("/{camera_id}/compile-sequence")
async def compile_sequence(
    camera_id: uuid.UUID,
    body: CompileSequenceRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")

    q = _camera_query(user).where(Camera.id == camera_id).options(joinedload(Camera.organization))
    result = await db.execute(q)
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    user_turns = [m for m in body.messages if m.role == "user"]
    if len(user_turns) > 5:
        raise HTTPException(status_code=400, detail="Conversation too long — start a new one.")
    force_draft = len(user_turns) == 5

    zone_names = [z.get("name") for z in (camera.detection_zones or [])]
    whatsapp_configured = bool(camera.organization.whatsapp_alert_contacts)

    charged = await spend_tracker.try_charge(str(camera.org_id), APPROX_COST_PER_CALL_USD)
    if not charged:
        return {"type": "question", "message": "Daily AI budget reached — build this manually, or try again tomorrow."}

    try:
        parsed = await sequence_compiler_client.turn(
            [m.model_dump() for m in body.messages], zone_names, whatsapp_configured, force_draft,
        )
    except Exception as e:
        logger.warning(f"sequence compiler failed for camera {camera_id}: {e}")
        return {"type": "question", "message": "AI generation failed — try rephrasing, or build this manually."}

    if parsed.get("type") == "question":
        return {"type": "question", "message": parsed.get("message", "Could you clarify that?")}

    steps = parsed.get("steps", [])
    alert_rule = parsed.get("alert_rule")
    warnings: list[str] = []

    if alert_rule and "whatsapp" in alert_rule.get("notify_channels", []):
        contacts = camera.organization.whatsapp_alert_contacts or []
        if contacts:
            alert_rule["notify_contacts"] = [{"type": "whatsapp", "value": c} for c in contacts]
        else:
            warnings.append("No WhatsApp contacts configured for this org — add one in Settings before saving, or this channel won't notify anyone.")
    if alert_rule and "email" in alert_rule.get("notify_channels", []):
        warnings.append("Add a destination email address before saving.")
    if alert_rule and "webhook" in alert_rule.get("notify_channels", []):
        warnings.append("Add the destination URL for this webhook before saving.")
    if alert_rule:
        alert_rule["cameras"] = [str(camera_id)]

    try:
        _validate_step_sequence(steps, camera.detection_zones)
    except HTTPException as e:
        warnings.append(f"Generated draft has an issue: {e.detail}. Review and fix before saving.")

    return {"type": "draft", "steps": steps, "alert_rule": alert_rule, "warnings": warnings}
```

### Spend cap — explicit tradeoff

Every turn (question or draft) charges `spend_tracker.try_charge` against the **same** `digest:spend:{org_id}:{day}` Redis key and `digest_daily_spend_cap_usd` setting that digests use, per your explicit choice to reuse the pattern exactly. A multi-turn conversation now costs proportionally more than the old single-shot design — a 5-turn conversation is 5 charges, not 1–2. If this becomes a real cost or contention concern in practice, splitting the cap is a one-line change (a separate `SpendTracker` instance with its own Redis key prefix); deferred, not designed away.

## Frontend

### `SequenceEditor.tsx` additions

A chat panel replaces the single textarea+button:

```tsx
type ChatMsg = { role: "user" | "assistant"; content: string };

const [messages, setMessages] = useState<ChatMsg[]>([]);
const [input, setInput] = useState("");
const [genWarnings, setGenWarnings] = useState<string[]>([]);
const [draftAlertRule, setDraftAlertRule] = useState<AlertRuleDraft | null>(null);

const turnMutation = useMutation({
  mutationFn: (nextMessages: ChatMsg[]) => api.compileSequence(camera.id, nextMessages),
  onSuccess: (data, nextMessages) => {
    if (data.type === "question") {
      setMessages([...nextMessages, { role: "assistant", content: data.message }]);
      return;
    }
    setMessages([...nextMessages, { role: "assistant", content: "Here's what I've put together — review it below." }]);
    setSteps(data.steps);
    setDraftAlertRule(data.alert_rule);
    setGenWarnings(data.warnings);
  },
});

const send = () => {
  if (!input.trim()) return;
  const next = [...messages, { role: "user" as const, content: input.trim() }];
  setMessages(next);
  setInput("");
  turnMutation.mutate(next);
};
```

Chat bubbles render `messages` in order; a text input + Send button appends to the thread. When a `"draft"` response arrives, `steps` and `draftAlertRule` populate the **same** editable state the manual form already uses — the existing `validationError` useMemo, zone `<select>` dropdowns, notification channel chips, and Save button require no changes beyond accepting `draftAlertRule` as an initial value. This is the same "always pre-fill, never auto-save" principle as before, just reached conversationally instead of in one shot.

On **Save**: `PATCH /cameras/{id}` with `step_sequence` (unchanged), and, if `draftAlertRule` is present and confirmed (webhook/email targets filled in per the warnings), `POST /api/alerts/rules` with the existing `CreateAlertRuleRequest` shape — no new alert-creation logic.

### API client

`frontend/src/lib/api.ts`:
```ts
async compileSequence(cameraId: string, messages: { role: string; content: string }[]) {
  return this.request<{
    type: "question" | "draft";
    message?: string;
    steps?: StepSequenceStep[];
    alert_rule?: AlertRuleDraft | null;
    warnings?: string[];
  }>(`/api/cameras/${cameraId}/compile-sequence`, {
    method: "POST",
    body: JSON.stringify({ messages }),
  });
}
```

## Error handling

Every failure path (cap exhausted, Gemini throws, malformed JSON, validation failure) returns a normal `"question"` or `"draft"` response shape — never a hard error from the compiler itself (the only hard error is the 400 for exceeding the turn cap, which the frontend should never trigger since it stops sending after 5 user turns). The manual editor underneath is always fully usable regardless of how the conversation goes.

## Testing

Per standing preference (no TDD ceremony, direct implementation + manual sanity check + self-review):
- Manual sanity check of `SequenceCompilerClient.turn()` using a fake client returning canned `"question"` and `"draft"` JSON, verifying both response shapes parse correctly and `force_draft` context actually changes the prompt sent.
- Manual check of the route handler: cap exhausted, compiler failure, a `"question"` passthrough, a `"draft"` with WhatsApp contacts present vs. absent, and the turn-cap 400 at 6 user turns.
- Frontend: `npm run build` clean, and a manual click-through simulating a short back-and-forth (ambiguous description → clarifying question → answer → draft lands in the editor and re-validates).

## Rollout

- No new config surface beyond the one new route and one new service class — no feature flag needed, since the manual editor is always present as a fallback regardless of whether generation succeeds.
- Shares the digest Gemini spend cap as designed above; revisit if operators report contention or if multi-turn conversations noticeably increase daily Gemini spend beyond what the shared cap comfortably allows.
