"""
Hooks — the fixed moments in a turn where guardrails attach.

A hook never chooses what the model does; it validates, constrains, or adds
context around what the model already chose (ADR 0001). The events mirror
Claude Code's:

    SESSION_START   a session's first turn: hooks return context to add to the
                    customer block (profile, memory)
    PRE_TOOL_USE    before a tool runs: allow / deny with feedback / pause
    POST_TOOL_USE   after a tool returns: rewrite or annotate the result
    STOP            the model is done: validate the reply or send it back
    SESSION_END     the customer ends the conversation: reflection

Only SESSION_START has a dispatcher in this iteration; the tool and stop events
gain theirs with the tickets that introduce tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class HookEvent(str, Enum):
    SESSION_START = "SessionStart"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    STOP = "Stop"
    SESSION_END = "SessionEnd"


@dataclass(frozen=True)
class SessionStartContext:
    session_id: str
    customer_id: str | None
    profile: dict[str, Any] | None
    product_usage: list[dict[str, Any]]


SessionStartHook = Callable[[SessionStartContext], str | None]


class HookRegistry:
    """Hooks by event, run in registration order."""

    def __init__(self) -> None:
        self._hooks: dict[HookEvent, list[Callable[..., Any]]] = {event: [] for event in HookEvent}

    def register(self, event: HookEvent, hook: Callable[..., Any]) -> None:
        self._hooks[event].append(hook)

    def run_session_start(self, ctx: SessionStartContext) -> list[str]:
        """Each SessionStart hook may return text for the customer block; empties are dropped."""
        out: list[str] = []
        for hook in self._hooks[HookEvent.SESSION_START]:
            text = hook(ctx)
            if text:
                out.append(text)
        return out
