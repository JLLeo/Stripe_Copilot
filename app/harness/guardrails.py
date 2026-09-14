"""
Guardrails — deterministic checks that attach to hooks.

Each guardrail validates or constrains something the model already chose;
none selects an action for it (ADR 0001). This module holds the ones every
tool needs — a per-turn budget, a result size cap, a per-session result
cache — and the two checks every final reply passes before the customer sees
it: no unfilled placeholders, no Internal Knowledge.
"""

from __future__ import annotations

import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.harness.hooks import Deny, HookEvent, HookRegistry, Replace, StopContext, ToolUseContext
from app.harness.tools import ToolResult
from app.paths import KNOWLEDGE_BASE_DIR

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
    cut = cut_at_boundary(text, max_chars)
    note = TRUNCATION_NOTE.format(shown=cut, total=len(text))
    return ToolResult(content=text[:cut] + note, is_error=result.is_error, meta={**result.meta, "truncated": True})


def make_result_cap(max_chars: int):
    def result_cap(ctx: ToolUseContext, result: ToolResult) -> ToolResult | None:
        return cap_result(result, max_chars)

    return result_cap


# ---------------------------------------------------------------------------
# turn_result_budget — PostToolUse
# ---------------------------------------------------------------------------
TURN_BUDGET_NOTE = "\n[truncated: this turn's tool-result budget is spent — answer from what you have, or continue next turn]"
TURN_BUDGET_MIN_KEEP = 300  # every result keeps at least this much, so the model always learns what came back
# A skill body is instructions the model is still following, bounded by the number of skills — not spent
# data. Neither the turn budget nor clearing (context.py) touches it.
INSTRUCTION_TOOLS = ("Skill",)


def make_turn_result_budget(budget_chars: int):
    """Once a turn's tool results add up to the budget, further results are cut to what is left (ADR 0006)."""

    def turn_result_budget(ctx: ToolUseContext, result: ToolResult) -> ToolResult | None:
        if ctx.tool.name in INSTRUCTION_TOOLS:
            return None
        text = result.content
        allowance = budget_chars - ctx.turn.result_chars
        if len(text) <= allowance:
            ctx.turn.result_chars += len(text)
            return None
        keep = max(allowance, TURN_BUDGET_MIN_KEEP)
        cut = cut_at_boundary(text, keep) if len(text) > keep else len(text)
        ctx.turn.result_chars += cut
        return ToolResult(content=text[:cut] + TURN_BUDGET_NOTE, is_error=result.is_error, meta={**result.meta, "truncated": True})

    return turn_result_budget


def cut_at_boundary(text: str, limit: int) -> int:
    """Where to cut `text` so at most `limit` characters remain: the last line, sentence, or JSON boundary — never mid-word."""
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
# anti_placeholder — Stop
# ---------------------------------------------------------------------------
# A bracketed or angled token is a fill-in-the-blank when one of these words appears in it
# — [Customer Name], [Sales Rep], <insert date> — and a citation like [Stripe Checkout] or a
# markdown link like [pricing](url) otherwise. "Link" is left out: Stripe Link is a product.
_PLACEHOLDER_WORDS = (
    r"your|customer|client|company|merchant|organi[sz]ation|insert|name|date|amount|value|placeholder|"
    r"contact|email|phone|address|signature|title|team|rep|representative|executive|recipient|sender|"
    r"business|product|url|number|region|country|currency|volume|rate|percentage|price|fee|x{1,3}|tbd|todo"
)
_HAS_PLACEHOLDER_WORD = rf"(?=[^\]>\n]{{0,60}}\b(?:{_PLACEHOLDER_WORDS})\b)"
_PLACEHOLDER_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    rf"\[{_HAS_PLACEHOLDER_WORD}[^\]\n]{{1,60}}\](?!\()",  # [Customer Name] — but not [text](link)
    rf"<{_HAS_PLACEHOLDER_WORD}[^>\n]{{1,60}}>",  # <your company>
    r"\{\{[^}\n]{1,60}\}\}",  # {{ template }}
    r"\b(?:TBD|TODO|XXX)\b",
    r"\[\s*\]|_{3,}",  # an empty blank, or a line to fill in
))


def find_placeholders(text: str) -> list[str]:
    return [m.group(0) for p in _PLACEHOLDER_PATTERNS for m in p.finditer(text)]


def anti_placeholder(ctx: StopContext) -> Deny | None:
    found = find_placeholders(ctx.reply)
    if not found:
        return None
    return Deny(
        "your reply contains placeholders that would reach the customer unfilled: "
        + ", ".join(dict.fromkeys(found))
        + ". Rewrite the whole reply with real values, or leave those parts out. Do not mention this note."
    )


# ---------------------------------------------------------------------------
# internal_canary — Stop
# ---------------------------------------------------------------------------
# Markers that only Internal Knowledge contains. Curated phrases plus, derived at first use
# from the non-public documents, their section headings (three words or more) and their
# percentage ranges — minus anything a public document also says, since public and internal
# documents share their section structure and an honest answer must never be sent back.
# This is the one place outside ingestion that opens those files, and nothing read here is
# ever sent to a model: it is a blocklist (ADR 0003).
_CURATED_MARKERS = (
    "INTERNAL ONLY", "DO NOT SHARE WITH CUSTOMERS", "internal_mock", "mock_policy", "Mock Internal",
    "Internal Guidelines", "Internal Reference", "Internal Use", "Discount Ranges", "Approval Workflow",
    "VP of Sales", "CRO approval", "CRO-level", "deal desk tool", "BANT", "price matching",
)
_PERCENT_RANGE = re.compile(r"\b\d+(?:\.\d+)?%?\s?-\s?\d+(?:\.\d+)?%\+?|\b\d+(?:\.\d+)?%\+")


def _present(marker: str, lowered: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(marker.lower())}(?![a-z0-9])", lowered) is not None


@lru_cache(maxsize=1)
def internal_markers(knowledge_base: Path = KNOWLEDGE_BASE_DIR) -> tuple[str, ...]:
    """The markers exclusive to Internal Knowledge: a phrase any public document uses is not a canary."""
    candidates: dict[str, None] = dict.fromkeys(_CURATED_MARKERS)
    public: list[str] = []
    for path in sorted(knowledge_base.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        level = re.search(r"^Access Level:\s*(.+)$", text, re.MULTILINE)
        if level and level.group(1).strip().lower() == "public":
            public.append(text.lower())
            continue
        for heading in re.findall(r"^###\s+(.+)$", text, re.MULTILINE):
            heading = re.sub(r"\s*\([^)]*\)\s*$", "", heading).strip()  # "(Mock)", "(Internal Reference)"
            if len(heading.split()) >= 3:
                candidates.setdefault(heading, None)
        for pct in _PERCENT_RANGE.findall(text):
            candidates.setdefault(pct.strip(), None)
    return tuple(m for m in candidates if not any(_present(m, doc) for doc in public))


def leaks(text: str) -> list[str]:
    """Every internal marker present in `text` — the zero-leak check tests and evaluation reuse."""
    lowered = text.lower()
    return [m for m in internal_markers() if _present(m, lowered)]


def internal_canary(ctx: StopContext) -> Deny | None:
    found = leaks(ctx.reply)
    if not found:
        return None
    return Deny(
        "your reply contains material the customer must not see (" + ", ".join(found) + "). "
        "Rewrite it without those figures, headings or phrases; offer to bring in the right team instead. "
        "Do not mention this note."
    )


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
def register_defaults(
    hooks: HookRegistry, *, tool_round_budget: int, result_cap_chars: int, turn_result_budget_chars: int, cache: ToolCache
) -> None:
    """The guardrails every tool gets, in the order they run, and the checks every reply gets."""
    lookup, store = make_tool_cache_hooks(cache)
    hooks.register(HookEvent.PRE_TOOL_USE, make_turn_budget(tool_round_budget))
    hooks.register(HookEvent.PRE_TOOL_USE, lookup)
    hooks.register(HookEvent.POST_TOOL_USE, make_result_cap(result_cap_chars))
    hooks.register(HookEvent.POST_TOOL_USE, store)  # the cache keeps the capped result, not this turn's budget cut
    hooks.register(HookEvent.POST_TOOL_USE, make_turn_result_budget(turn_result_budget_chars))
    hooks.register(HookEvent.STOP, anti_placeholder)
    hooks.register(HookEvent.STOP, internal_canary)
