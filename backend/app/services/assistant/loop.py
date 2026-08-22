"""The tool-calling loop that runs one user turn end to end.

Ties together the tool registry (Task 2) and the Gemini client (Task 4):
build contents from history, call the model, dispatch any function calls it
asks for, feed the results back, and repeat until the model stops calling
tools or the iteration bound is hit.

Bounded and metered by design — see MAX_ITERATIONS and the per-iteration
``spend.try_charge`` call below. Both are load-bearing: an unbounded
tool-calling loop against a paid API is a cost incident and a latency
failure, and a spend cap that only sees the first call of a multi-iteration
turn is not a cap.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.services.assistant.gemini import APPROX_COST_PER_TURN_USD
from app.services.assistant.registry import ToolContext, TOOL_DECLARATIONS, dispatch
from app.services.chat_service import ChatTurn

MAX_ITERATIONS = 5


class SpendCapReached(Exception):
    """Raised when a per-org/site spend cap would be exceeded mid-turn.

    Deliberately does NOT subclass RuntimeError: Task 6 catches this
    separately (-> 429) from RuntimeError (-> 503, raised by
    AssistantGeminiClient.generate() when Gemini itself is unavailable).
    Collapsing the two into one exception type would collapse that HTTP
    status distinction too.
    """


@dataclass
class AssistantResult:
    text: str
    proposal_ids: list[uuid.UUID] = field(default_factory=list)
    navigate: str | None = None
    turns: int = 0
    stopped_early: bool = False


def _function_calls(response: Any) -> list:
    """Return the function calls in a Gemini response, or [] if none.

    Reads ``response.candidates[0].content.parts[*].function_call`` directly
    rather than relying on the SDK's own ``response.function_calls``
    convenience property, so this also works against the plain fake response
    objects used in manual verification (which mimic the attribute shape but
    aren't real ``GenerateContentResponse`` instances).
    """
    candidates = getattr(response, "candidates", None)
    if not candidates:
        return []
    content = candidates[0].content
    if not content or not content.parts:
        return []
    return [part.function_call for part in content.parts if part.function_call is not None]


def _model_turn(response: Any) -> Any:
    """Echo the model's own content (the turn that requested tool calls)
    back into ``contents`` verbatim, so the next call sees exactly what it
    said, including the function_call parts.
    """
    return response.candidates[0].content


def _tool_result_turn(name: str, result: dict) -> Any:
    """Build a contents entry carrying a tool's result back to the model.

    Per the google-genai SDK (see Models._generate_content's handling of
    automatic function calling in models.py), function response parts are
    wrapped in a Content with role="user" — there is no separate "function"
    or "tool" role in the Content.role contract (it only accepts "user" or
    "model").
    """
    from google.genai import types  # type: ignore

    return types.Content(
        role="user",
        parts=[types.Part.from_function_response(name=name, response=result)],
    )


def _build_contents(history: Sequence[ChatTurn], user_message: str) -> list:
    """Turn prior chat history plus the new user message into the initial
    ``contents`` list for the first model call of this turn.

    The system prompt is NOT included here — the client attaches it via
    ``config.system_instruction`` (Task 4), so prepending it into contents
    would duplicate it.
    """
    from google.genai import types  # type: ignore

    contents: list = []
    for turn in history:
        role = "user" if turn.role == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=turn.content)]))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_message)]))
    return contents


async def run_turn(*, client, spend, ctx: ToolContext, history, user_message: str) -> AssistantResult:
    """Run one user turn to completion.

    Bounded at MAX_ITERATIONS for both cost and latency. Every iteration is
    charged against the spend cap — a five-iteration turn costs roughly five
    times a single chat turn, and a cap that only sees the opening call is
    not a cap.
    """
    contents = _build_contents(history, user_message)
    proposal_ids: list[uuid.UUID] = []
    navigate: str | None = None
    turns = 0

    while turns < MAX_ITERATIONS:
        if not await spend.try_charge(ctx.org_id, APPROX_COST_PER_TURN_USD, site_id=None):
            raise SpendCapReached()

        turns += 1
        response = await client.generate(contents=contents, tools=TOOL_DECLARATIONS)
        calls = _function_calls(response)
        if not calls:
            return AssistantResult(
                text=(response.text or "").strip(),
                proposal_ids=proposal_ids,
                navigate=navigate,
                turns=turns,
                stopped_early=False,
            )

        contents.append(_model_turn(response))
        for call in calls:
            result = await dispatch(call.name, dict(call.args or {}), ctx)
            if "proposal_id" in result:
                proposal_ids.append(uuid.UUID(result["proposal_id"]))
            if "navigate" in result:
                navigate = result["navigate"]
            contents.append(_tool_result_turn(call.name, result))

    # Hit the bound. Say so rather than implying the answer is complete —
    # this is a security product, and a conclusive-sounding but unfinished
    # answer is worse than an honest admission of failure.
    return AssistantResult(
        text=(
            "I stopped after several steps without finishing. "
            "Could you narrow the question?"
        ),
        proposal_ids=proposal_ids,
        navigate=navigate,
        turns=turns,
        stopped_early=True,
    )
