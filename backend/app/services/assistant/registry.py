"""Tool registry for the assistant.

Two rules govern everything in this package:

1. Tools never take an `org_id` parameter. It is bound from the session in
   `ToolContext`. A tool the model *can* pass an org_id to is a tool the model
   can be argued into passing someone else's org_id to, and no prompt
   instruction substitutes for the parameter not existing.

2. Tools call the existing service/query helpers rather than writing their own
   queries, so `org_id` + `scope_to_sites()` scoping is inherited rather than
   re-implemented (and therefore cannot drift out of sync with it).
"""

import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@dataclass
class ToolContext:
    db: AsyncSession
    user: User
    org_id: uuid.UUID
    conversation_id: uuid.UUID


ToolFn = Callable[..., Awaitable[dict]]

_REGISTRY: dict[str, ToolFn] = {}
TOOL_DECLARATIONS: list[dict] = []


def register(declaration: dict) -> Callable[[ToolFn], ToolFn]:
    """Register a tool function under its declaration's name."""

    def wrap(fn: ToolFn) -> ToolFn:
        name = declaration["name"]
        if name in _REGISTRY:
            raise ValueError(f"duplicate tool name: {name}")
        _REGISTRY[name] = fn
        TOOL_DECLARATIONS.append(declaration)
        return fn

    return wrap


async def dispatch(name: str, args: dict[str, Any], ctx: ToolContext) -> dict:
    """Execute a tool by name.

    Unknown tools and tool errors are returned as data, not raised: the loop
    feeds the result back to the model, which can then correct itself or tell
    the user plainly. A raised exception would abort the whole turn.
    """
    fn = _REGISTRY.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return await fn(ctx, **args)
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - surfaced to the model as data
        return {"error": f"{name} failed: {exc}"}
