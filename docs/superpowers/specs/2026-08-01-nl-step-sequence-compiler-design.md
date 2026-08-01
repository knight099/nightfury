# Natural-Language Step-Sequence Compiler — Design

## Problem

Authoring a `step_sequence` today requires the operator to manually build an ordered list of (zone, pose, timeout) steps through `SequenceEditor.tsx` — one dropdown/select at a time. Competitors in this space (OpenVector) let a user describe the procedure they want monitored in plain English and have the system generate the detection config automatically. This closes that gap for our existing step-sequence feature without requiring the user to understand our internal schema.

## Goal

Add a "describe it in plain English" path into the existing `SequenceEditor`:
1. User types a description of the procedure (e.g. "flag if someone leaves without paying at the counter").
2. Backend calls Gemini to translate that description, grounded in the camera's actual zone names and the fixed pose-label vocabulary, into a draft `step_sequence`.
3. The draft populates the existing editor form for review — nothing is ever written to the DB by this feature directly. The user still hits the same **Save** button that already exists.

## Non-goals

- Generating `alert_rules` or any other config type — this compiler only ever produces `step_sequence` drafts.
- Generating or chaining actions (POS/CRM writes, calls, webhooks) — that's a separate, larger initiative (an actions/integrations engine) and explicitly out of scope here.
- A conversational/chat refinement loop — v1 is single-shot: describe, generate, review, edit-if-needed, save.
- Any change to how `step_sequence` is validated, stored, or consumed by the worker — this feature only ever produces input that flows through the existing `_validate_step_sequence` and `SequenceEditor` state, both unchanged.

## Architecture

```
User types description in SequenceEditor
  → POST /api/cameras/{id}/generate-step-sequence  { description }
  → backend: SequenceCompilerClient.compile(description, zone_names, pose_labels)
      → SpendTracker.try_charge(org_id, cost) — same per-org daily cap as digests
          → if False: return { steps: [], warnings: ["daily AI budget reached..."] }
      → Gemini 2.5 Flash, text-only, structured-JSON prompt (grounded in real zone names)
      → parse JSON, strip fences
      → _validate_step_sequence(steps, camera.detection_zones)
          → if invalid: one retry with the specific validation error appended to the prompt
          → if still invalid: return steps anyway + warnings (best-effort draft)
  ← { steps: [...], warnings: [...] }
  → SequenceEditor populates `steps` state from the response
  → flows through existing zone-validation useMemo, existing Save button, existing PATCH /cameras/{id}
```

This is purely additive — no existing endpoint, table, or validation function changes behavior. The new endpoint is a pure "text in, draft JSON out" translator sitting in front of infrastructure that already exists (Task 7/8 of the pose-sequence-tracking plan).

## Backend

### New service: `backend/app/services/sequence_compiler/gemini_client.py`

Mirrors `backend/app/services/digest/gemini_client.py`'s `GeminiDigestClient` structurally:

```python
SYSTEM_PROMPT = """You translate a plain-English description of a monitored procedure
into an ordered list of steps for a camera's step-sequence tracker. Each step has a
zone (must be one of the camera's existing zone names, given below — never invent one),
an optional pose (must be exactly one of: standing, bending, crouching, sitting, reaching,
or null for "any pose"), and an optional max_seconds timeout."""

SCHEMA_HINT = """Respond ONLY with JSON matching this schema (no markdown, no commentary):
{"steps": [{"name": string, "zone": string, "pose": string | null, "max_seconds": number | null}, ...]}"""

class SequenceCompilerClient:
    def __init__(self, client, model: str = "gemini-2.5-flash"):
        self.client = client
        self.model = model

    def _build_prompt(self, description: str, zone_names: list[str], correction: str | None = None) -> str:
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"Available zones for this camera: {zone_names}\n\n"
            f"{SCHEMA_HINT}\n\n"
            f"Procedure description: {description}"
        )
        if correction:
            prompt += f"\n\nYour previous attempt was invalid: {correction}\nTry again, fixing this issue."
        return prompt

    async def compile(self, description: str, zone_names: list[str]) -> dict:
        for attempt, correction in enumerate([None, None]):
            prompt = self._build_prompt(description, zone_names, correction)
            response = await self.client.aio.models.generate_content(
                model=self.model, contents=prompt
            )
            text = response.text.strip()
            if text.startswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            try:
                parsed = json.loads(text)
                return parsed
            except (json.JSONDecodeError, AttributeError) as e:
                if attempt == 1:
                    raise
                correction = f"response was not valid JSON: {e}"
        raise RuntimeError("unreachable")
```

The validation-driven retry (as opposed to a JSON-parse-driven retry) happens one level up, in the route handler, since `_validate_step_sequence` needs the camera's `detection_zones` object, not just names — see below.

### New route: `backend/app/api/cameras.py`

```python
class GenerateStepSequenceRequest(BaseModel):
    description: str


@router.post("/{camera_id}/generate-step-sequence")
async def generate_step_sequence(
    camera_id: uuid.UUID,
    body: GenerateStepSequenceRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")

    q = _camera_query(user).where(Camera.id == camera_id)
    result = await db.execute(q)
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    zone_names = [z.get("name") for z in (camera.detection_zones or [])]

    charged = await spend_tracker.try_charge(str(camera.org_id), APPROX_COST_PER_CALL_USD)
    if not charged:
        return {"steps": [], "warnings": ["Daily AI budget reached — build this sequence manually, or try again tomorrow."]}

    try:
        parsed = await sequence_compiler_client.compile(body.description, zone_names)
        steps = parsed.get("steps", [])
    except Exception as e:
        logger.warning(f"sequence compiler failed for camera {camera_id}: {e}")
        return {"steps": [], "warnings": ["AI generation failed — build this sequence manually."]}

    try:
        _validate_step_sequence(steps, camera.detection_zones)
        return {"steps": steps, "warnings": []}
    except HTTPException as e:
        # one retry, telling the model exactly what was wrong
        try:
            parsed_retry = await sequence_compiler_client.compile(
                body.description, zone_names, correction=e.detail
            )
            steps_retry = parsed_retry.get("steps", [])
            _validate_step_sequence(steps_retry, camera.detection_zones)
            return {"steps": steps_retry, "warnings": []}
        except Exception:
            return {
                "steps": steps,
                "warnings": [f"Generated draft has an issue: {e.detail}. Review and fix before saving."],
            }
```

(`sequence_compiler_client.compile` gains an optional `correction: str | None` param for the second call, matching the class sketch above.)

### Spend cap — explicit tradeoff

This feature calls `spend_tracker.try_charge` against the **same** `digest:spend:{org_id}:{day}` Redis key and `digest_daily_spend_cap_usd` setting that digests use — per your explicit choice to reuse the pattern exactly rather than carve out a separate budget line. Consequence: a busy digest day can exhaust the shared cap before an operator gets to author a sequence that day (and vice versa). If this turns out to be a real friction point in practice, splitting the cap is a one-line change (a new `SpendTracker` instance with its own Redis key prefix) — deferred, not designed away, since you explicitly asked for the shared-cap version.

## Frontend

### `SequenceEditor.tsx` additions

Above the existing step list:

```tsx
const [description, setDescription] = useState("");
const [genWarnings, setGenWarnings] = useState<string[]>([]);

const generateMutation = useMutation({
  mutationFn: () => api.generateStepSequence(camera.id, description),
  onSuccess: (data) => {
    if (steps.length > 0 && !window.confirm("Replace current steps with the generated draft?")) return;
    setSteps(data.steps);
    setGenWarnings(data.warnings);
  },
});
```

```tsx
<textarea
  value={description}
  onChange={(e) => setDescription(e.target.value)}
  placeholder="Describe the procedure, e.g. 'flag if someone leaves without paying at the counter'"
  className="w-full px-2 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
  rows={2}
/>
<button
  onClick={() => generateMutation.mutate()}
  disabled={!description.trim() || generateMutation.isPending}
  className="px-3 py-1.5 bg-[#1E90FF] text-white rounded text-xs hover:bg-[#3BA0FF] transition-colors disabled:opacity-50"
>
  {generateMutation.isPending ? "Generating..." : "Generate from description"}
</button>
{genWarnings.map((w, i) => (
  <div key={i} className="text-xs text-amber-400">{w}</div>
))}
```

Generated `steps` flow into the exact same `useState<StepSequenceStep[]>` the manual editor already uses — the existing `validationError` useMemo, zone `<select>` dropdowns, and Save button require zero changes. This is the entire point of the "always pre-fill, never auto-save" decision: the compiler is a draft generator bolted onto infrastructure that already enforces correctness.

### API client

`frontend/src/lib/api.ts`:
```ts
async generateStepSequence(cameraId: string, description: string) {
  return this.request<{ steps: StepSequenceStep[]; warnings: string[] }>(
    `/api/cameras/${cameraId}/generate-step-sequence`,
    { method: "POST", body: JSON.stringify({ description }) }
  );
}
```

## Error handling

Every failure path (cap exhausted, Gemini throws, JSON malformed after retry, validation still fails after retry) returns **HTTP 200** with `{"steps": [...], "warnings": [...]}` — never a hard error to the frontend. The manual editor underneath is always fully usable regardless of what the AI path does, so there's no failure mode that blocks the user from building a sequence by hand exactly as they can today.

## Testing

Per standing preference (no TDD ceremony, direct implementation + manual sanity check + self-review):
- Manual sanity check of `SequenceCompilerClient.compile()` using a fake client that returns canned JSON strings (valid, malformed, and "references a zone not in the list" cases), verifying the parse/retry/degrade branches — same style as the existing `_StubGeminiClient` fallback already in `deps.py`.
- Manual check of the route handler's three return shapes (cap exhausted, compile failure, validation failure after retry, success) using the same fake client.
- Frontend: `npm run build` clean, and a manual click-through (type a description, generate, confirm the draft lands in the editor and re-validates).

## Rollout

- No new config surface beyond the one new route and one new service class — no feature flag needed, since the manual editor is always present as a fallback regardless of whether generation succeeds.
- Shares the digest Gemini spend cap as designed above; revisit if operators report contention between digest generation and sequence authoring in the same org on the same day.
