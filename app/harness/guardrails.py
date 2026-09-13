"""
Guardrails — deterministic checks that attach to hooks.

Each guardrail validates or constrains a tool call the model already chose;
none selects a tool for it (ADR 0001). This module holds the ones every tool
needs: a per-turn budget, a result size cap, and a per-session result cache.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from dataclasses import dataclass

from app.harness.hooks import Deny, HookEvent, HookRegistry, Replace, ToolUseContext
from app.harness.tools import ToolResult

TRUNCATION_NOTE = "\n\n[truncated: showing {shown} of {total} characters]"


# ---------------------------------------------------------------------------
# turn_budget — PreToolUse
# ---------------------------------------------------------------------------
def make_turn_budget(rounds: int):
    def turn_budget(ctx: ToolUseContext) -> Deny | None:
        if ctx.turn.tool_rounds > rounds:
            ctx.turn.tools_exhausted = True  # the harness reads this to force a text answer next
            return Deny(
                f"this turn has used its {rounds} rounds of tool calls. "
                "Answer the customer now with what you already have; say what you could not check."
            )
        return None

    return turn_budget


# ---------------------------------------------------------------------------
# result_cap — PostToolUse
# ---------------------------------------------------------------------------
def cap_result(result: ToolResult, max_chars: int) -> ToolResult | None:
    """The result truncated at a boundary with a note, or None if it already fits."""
    text = result.content
    if len(text) <= max_chars:
        return None
    cut = _boundary(text, max_chars)
    note = TRUNCATION_NOTE.format(shown=cut, total=len(text))
    return ToolResult(content=text[:cut] + note, is_error=result.is_error, meta={**result.meta, "truncated": True})


def make_result_cap(max_chars: int):
    def result_cap(ctx: ToolUseContext, result: ToolResult) -> ToolResult | None:
        return cap_result(result, max_chars)

    return result_cap


def _boundary(text: str, limit: int) -> int:
    """Cut at the last line, sentence, or JSON boundary before `limit` — never mid-word."""
    window = text[:limit]
    # The latest boundary in the tail of the window wins; boundaries are ranked only
    # to break ties between a structural marker and a plain space at the same spot.
    best = 0
    for marker in ("},", "],", '",', ". ", "\n", " "):
        idx = window.rfind(marker)
        if idx > limit * 6 // 10 and idx + len(marker.rstrip()) > best:
            best = idx + len(marker.rstrip())
    return best or limit


# ---------------------------------------------------------------------------
# tool cache — PreToolUse lookup, PostToolUse store
# ---------------------------------------------------------------------------
@dataclass
class _Entry:
    result: ToolResult
    expires_at: float


class ToolCache:
    """Per-session cache of tool results with a TTL and bounded size.

    Identical calls (same tool, same arguments) within a session are served
    from here instead of hitting SQLite or the knowledge index again.
    """

    def __init__(self, ttl_seconds: float, max_entries_per_session: int = 50, max_sessions: int = 200):
        self.ttl = ttl_seconds
        self.max_entries = max_entries_per_session
        self.max_sessions = max_sessions
        self._sessions: OrderedDict[str, OrderedDict[str, _Entry]] = OrderedDict()

    @staticmethod
    def key(tool_name: str, arguments: dict) -> str:
        return tool_name + ":" + json.dumps(arguments, sort_keys=True, ensure_ascii=False)

    def get(self, session_id: str, key: str) -> ToolResult | None:
        entries = self._sessions.get(session_id)
        if not entries:
            return None
        entry = entries.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            del entries[key]
            return None
        entries.move_to_end(key)
        self._sessions.move_to_end(session_id)
        return entry.result

    def put(self, session_id: str, key: str, result: ToolResult) -> None:
        entries = self._sessions.setdefault(session_id, OrderedDict())
        entries[key] = _Entry(result=result, expires_at=time.monotonic() + self.ttl)
        entries.move_to_end(key)
        while len(entries) > self.max_entries:
            entries.popitem(last=False)
        self._sessions.move_to_end(session_id)
        while len(self._sessions) > self.max_sessions:
            self._sessions.popitem(last=False)


def make_tool_cache_hooks(cache: ToolCache):
    def tool_cache_lookup(ctx: ToolUseContext) -> Replace | None:
        if not ctx.tool.cacheable:
            return None
        hit = cache.get(ctx.turn.session_id, ToolCache.key(ctx.tool.name, ctx.arguments))
        if hit is None:
            return None
        return Replace(ToolResult(content=hit.content, is_error=hit.is_error, meta={**hit.meta, "cached": True}))

    def tool_cache_store(ctx: ToolUseContext, result: ToolResult) -> None:
        if ctx.tool.cacheable and not result.is_error and not result.meta.get("cached"):
            cache.put(ctx.turn.session_id, ToolCache.key(ctx.tool.name, ctx.arguments), result)
        return None

    return tool_cache_lookup, tool_cache_store


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
def register_defaults(hooks: HookRegistry, *, tool_round_budget: int, result_cap_chars: int, cache: ToolCache) -> None:
    """The guardrails every tool gets, in the order they run."""
    lookup, store = make_tool_cache_hooks(cache)
    hooks.register(HookEvent.PRE_TOOL_USE, make_turn_budget(tool_round_budget))
    hooks.register(HookEvent.PRE_TOOL_USE, lookup)
    hooks.register(HookEvent.POST_TOOL_USE, make_result_cap(result_cap_chars))
    hooks.register(HookEvent.POST_TOOL_USE, store)
