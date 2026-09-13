"""
Hooks — the fixed moments in a turn where guardrails attach.

A hook never chooses what the model does; it validates, constrains, or adds
context around what the model already chose (ADR 0001). The events mirror
Claude Code's:

    SESSION_START   a session's first turn: hooks return context to add to the
                    customer block (profile, memory)
    PRE_TOOL_USE    before a tool runs: Allow, Deny (with feedback the model
                    reads), or Replace (serve a result without running the tool)
    POST_TOOL_USE   after a tool returns: return a modified result, or None
    STOP            the model is done: validate the reply or send it back
    SESSION_END     the customer ends the conversation: reflection

STOP and SESSION_END gain their dispatchers with the tickets that need them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from app.harness.tools import Tool, ToolResult


class HookEvent(str, Enum):
    SESSION_START = "SessionStart"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    STOP = "Stop"
    SESSION_END = "SessionEnd"


# ---------------------------------------------------------------------------
# Contexts
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SessionStartContext:
    session_id: str
    customer_id: str | None
    profile: dict[str, Any] | None
    product_usage: list[dict[str, Any]]


@dataclass
class TurnState:
    """What guardrails may know about the turn in progress. Mutable: hooks keep counters here."""

    session_id: str
    customer_id: str | None
    tool_rounds: int = 0  # model responses that carried tool calls, so far this turn
    tools_exhausted: bool = False  # set by turn_budget once it has denied a call this turn


@dataclass(frozen=True)
class ToolUseContext:
    turn: TurnState
    tool: Tool
    call_id: str
    arguments: dict[str, Any]


# ---------------------------------------------------------------------------
# PreToolUse outcomes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Allow:
    pass


@dataclass(frozen=True)
class Deny:
    feedback: str  # goes back to the model as the tool's result


@dataclass(frozen=True)
class Replace:
    result: ToolResult  # served instead of running the tool (e.g. a cache hit)


PreToolUseOutcome = Allow | Deny | Replace

SessionStartHook = Callable[[SessionStartContext], str | None]
PreToolUseHook = Callable[[ToolUseContext], PreToolUseOutcome | None]
PostToolUseHook = Callable[[ToolUseContext, ToolResult], ToolResult | None]


@dataclass(frozen=True)
class Decision:
    """A PreToolUse verdict with the name of the hook that produced it."""

    outcome: PreToolUseOutcome
    hook: str = ""


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

    def run_pre_tool_use(self, ctx: ToolUseContext) -> Decision:
        """The first hook that denies or replaces wins; otherwise the call is allowed."""
        for hook in self._hooks[HookEvent.PRE_TOOL_USE]:
            outcome = hook(ctx)
            if isinstance(outcome, (Deny, Replace)):
                return Decision(outcome, hook=getattr(hook, "__name__", type(hook).__name__))
        return Decision(Allow())

    def run_post_tool_use(self, ctx: ToolUseContext, result: ToolResult) -> ToolResult:
        """Each PostToolUse hook may hand back a modified result; None keeps the current one."""
        for hook in self._hooks[HookEvent.POST_TOOL_USE]:
            modified = hook(ctx, result)
            if modified is not None:
                result = modified
        return result
