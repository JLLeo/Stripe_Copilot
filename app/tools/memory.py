"""
Customer Memory — `remember` during the conversation, Reflection when it ends.

A fact the customer states is worth keeping beyond the session: a need, an
objection, a preference, a commitment, or where they are in evaluating Stripe.
The model records it with `remember` as it happens (and corrects or drops it
when told it is wrong); at SessionEnd a Reflection sub-agent on the cheaper
model reads the whole conversation and writes what the agent did not record,
merging duplicates. Facts are never edited in place: a correction is a new row
that supersedes the old one, so what the model saw in an earlier session can
always be traced.

At SessionStart a bounded set of active facts is rendered into the customer
block; a fact remembered mid-session reaches the model as the tool's result,
appended to working memory, and is never re-rendered into the block (ADR 0005).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app import database
from app.database import MEMORY_KINDS
from app.harness.context import COMPACTION_PREFACE
from app.harness.hooks import Deny, HookEvent, HookRegistry, SessionEndContext, ToolUseContext
from app.harness.provider import Provider
from app.harness.subagent import SubagentSpec, run_subagent
from app.harness.tools import Tool, ToolContext, ToolRegistry, ToolResult
from app.metrics import TurnRecord, record_turn

log = logging.getLogger(__name__)

REMEMBER_CONFIDENCE = 0.9  # the customer said it, in this conversation
MAX_FACT_CHARS = 300
REFLECTION_TRANSCRIPT_CHARS = 60_000  # the tail of a very long session is what reflection reads


# ---------------------------------------------------------------------------
# Writing facts — shared by the tool and the reflection pass
# ---------------------------------------------------------------------------
def _clean_fact(value: Any) -> str:
    return " ".join(str(value or "").split())[:MAX_FACT_CHARS]


def _same_fact(a: str, b: str) -> bool:
    return a.casefold().rstrip(".!") == b.casefold().rstrip(".!")


def find_duplicate(customer_id: str, kind: str, fact: str) -> dict[str, Any] | None:
    """An active fact of the same kind that says the same thing — no two rows may."""
    return next((m for m in database.active_memories(customer_id) if m["kind"] == kind and _same_fact(m["fact"], fact)), None)


@dataclass(frozen=True)
class MemoryWrite:
    """What one attempt to write a fact came to."""

    memory: dict[str, Any] | None = None  # the row now holding the fact: new, or the existing one for a duplicate
    earlier: list[dict[str, Any]] = field(default_factory=list)  # rows this write superseded or retracted
    duplicate: bool = False  # an active fact of the same kind already said this; nothing was written
    error: str | None = None  # feedback for the model; nothing was written


def write_memory(
    customer_id: str, *, kind: str, fact: str, replaces: list[int], source_turn: str, source: str, confidence: float
) -> MemoryWrite:
    """Add a fact (or retract, when the fact is empty) and settle what it replaces.

    Every id in `replaces` must be one of this customer's active facts; nothing is written
    otherwise, so a wrong id never half-applies a correction. A fact identical to an active
    one of the same kind is not written again, so neither the model nor reflection can say
    the same thing twice.
    """
    if kind not in MEMORY_KINDS:
        return MemoryWrite(error=f"kind must be one of {', '.join(MEMORY_KINDS)} (got {kind!r}).")
    fact = _clean_fact(fact)
    if not fact and not replaces:
        return MemoryWrite(error="fact is required unless replaces names an earlier fact to drop.")
    earlier: list[dict[str, Any]] = []
    for memory_id in replaces:
        row = database.get_memory(memory_id)
        if row is None or row["customer_id"] != customer_id or row["status"] != database.MEMORY_ACTIVE:
            return MemoryWrite(error=f"replaces={memory_id} is not one of this customer's current facts; check the [m<id>] ids you were given.")
        earlier.append(row)
    if not fact:
        for row in earlier:
            database.retract_memory(row["id"], customer_id)
        return MemoryWrite(earlier=earlier)
    duplicate = find_duplicate(customer_id, kind, fact)
    if duplicate and duplicate["id"] not in {row["id"] for row in earlier}:
        return MemoryWrite(memory=duplicate, duplicate=True)
    new = database.add_memory(customer_id, kind=kind, fact=fact, source_turn=source_turn, source=source, confidence=confidence)
    for row in earlier:
        database.supersede_memory(row["id"], customer_id, by=new["id"])
    return MemoryWrite(memory=new, earlier=earlier)


def _brief(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "kind": row["kind"], "fact": row["fact"], "confidence": row["confidence"]}


# ---------------------------------------------------------------------------
# remember — the tool
# ---------------------------------------------------------------------------
def remember(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    replaces_arg = args.get("replaces")
    try:
        replaces = [int(replaces_arg)] if replaces_arg not in (None, "") else []
    except (TypeError, ValueError):
        return ToolResult.error("replaces must be the numeric id of an earlier fact, e.g. 12 for [m12].")
    write = write_memory(
        ctx.customer_id or "", kind=str(args.get("kind") or ""), fact=str(args.get("fact") or ""), replaces=replaces,
        source_turn=ctx.turn_id, source="remember", confidence=REMEMBER_CONFIDENCE,
    )
    if write.error:
        return ToolResult.error(write.error)
    if write.duplicate:
        return ToolResult.from_payload({"memory": _brief(write.memory), "note": "Already remembered; nothing new was written."})
    if write.memory is None:
        return ToolResult.from_payload({"retracted": _brief(write.earlier[0]), "note": "This fact will not be brought up again."})
    payload: dict[str, Any] = {"memory": _brief(write.memory)}
    if write.earlier:
        payload["replaced"] = _brief(write.earlier[0])
    return ToolResult.from_payload(payload)


def customer_only(ctx: ToolUseContext) -> Deny | None:
    """Customer Memory belongs to a customer; a prospect's facts go into the Lead."""
    if ctx.tool.name != "remember" or ctx.turn.customer_id:
        return None
    return Deny("this is a new prospect with no Stripe account, so there is no customer to remember this for. Record what they tell you with capture_lead instead.")


def register_guardrails(hooks: HookRegistry) -> None:
    hooks.register(HookEvent.PRE_TOOL_USE, customer_only)


def register(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="remember",
        description=(
            "Keep a fact about this customer for future conversations: a need, an objection, a preference, a "
            "commitment or decision, or where they are in evaluating Stripe. Use it when the customer states "
            "something durable ('we go live in Q4', 'our CFO won't accept per-seat pricing'); not for what the "
            "profile already says, not for your own advice. To correct an earlier fact pass replaces=<id> with the "
            "new fact; to drop one that is wrong or no longer true pass replaces=<id> with an empty fact."
        ),
        parameters={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(MEMORY_KINDS)},
                "fact": {"type": "string", "description": "One sentence, in the third person, specific enough to act on. Empty to drop the fact named by replaces."},
                "replaces": {"type": "integer", "description": "The id of the earlier fact this corrects or drops, from its [m<id>] tag."},
            },
            "required": ["kind", "fact"],
            "additionalProperties": False,
        },
        run=remember,
        cacheable=False,
    ))


# ---------------------------------------------------------------------------
# Reflection — the SessionEnd pass
# ---------------------------------------------------------------------------
REFLECTION_SYSTEM_PROMPT = """You maintain the memory Stripe's AI sales agent keeps about a customer between conversations. You receive one finished conversation and the facts already remembered about the customer, and you decide what else is worth keeping.

What to keep — only what the customer stated or clearly decided, never the agent's advice:
- need: what they want to do or fix
- objection: what holds them back, and who raised it
- preference: how they like to work, be contacted, buy
- commitment: what they said they will do, and when
- stage: where they are in evaluating Stripe (comparing, piloting, decided, blocked)

Rules:
- Do not repeat a fact that is already remembered. If the conversation refines or contradicts one, save the better version with replaces set to its id.
- If two remembered facts say the same thing, save one merged fact with replaces listing both ids.
- One sentence per fact, third person, specific. Confidence 0.9 when the customer said it plainly, lower when you inferred it.
- Save everything in one save_memories call, then reply "done". If there is nothing new to keep, reply "nothing new" without calling the tool."""

REFLECTION_CAP_NOTE = "Reply with one word now; nothing more will be saved."


def make_save_memories(customer_id: str, pass_id: str, written: dict[str, int]) -> Tool:
    """The reflection sub-agent's only tool; counts land in `written` for the SessionEnd summary."""

    def save_memories(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        items = args.get("memories")
        if not isinstance(items, list) or not items:
            return ToolResult.error("memories must be a non-empty list of {kind, fact, confidence, replaces?}.")
        saved, rejected, duplicates = [], [], []
        for item in items:
            if not isinstance(item, dict):
                rejected.append({"item": item, "error": "each memory is an object"})
                continue
            raw = item.get("replaces")
            raw_list = raw if isinstance(raw, list) else ([] if raw in (None, "") else [raw])
            try:
                replaces = [int(r) for r in raw_list]
                confidence = min(1.0, max(0.0, float(item.get("confidence", 0.7))))
            except (TypeError, ValueError):
                rejected.append({"item": item, "error": "replaces must be ids and confidence a number"})
                continue
            write = write_memory(
                customer_id, kind=str(item.get("kind") or ""), fact=str(item.get("fact") or ""), replaces=replaces,
                source_turn=pass_id, source="reflection", confidence=confidence,
            )
            if write.duplicate:
                duplicates.append(_brief(write.memory))
                continue
            if write.error or write.memory is None:
                rejected.append({"item": item, "error": write.error or "an empty fact only retracts; give the merged fact"})
                continue
            written["remembered"] += 1
            written["merged"] += len(write.earlier)
            saved.append(_brief(write.memory))
        return ToolResult.from_payload({"saved": saved, "already_remembered": duplicates, "rejected": rejected})

    return Tool(
        name="save_memories",
        description="Save the facts worth remembering about this customer, all in one call.",
        parameters={
            "type": "object",
            "properties": {
                "memories": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": list(MEMORY_KINDS)},
                            "fact": {"type": "string"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "replaces": {"type": "array", "items": {"type": "integer"}, "description": "ids of remembered facts this one refines, contradicts or merges"},
                        },
                        "required": ["kind", "fact", "confidence"],
                    },
                }
            },
            "required": ["memories"],
            "additionalProperties": False,
        },
        run=save_memories,
        cacheable=False,
    )


def reflection_task(customer_name: str, working_memory: list[dict[str, Any]], memories: list[dict[str, Any]]) -> str:
    """What the reflection sub-agent reads: the facts on file, then the conversation as the customer and agent had it."""
    lines = [f"Customer: {customer_name}", "", "Already remembered:"]
    lines += [f"- [m{m['id']}] {m['kind']} — {m['fact']}" for m in memories] or ["(nothing yet)"]
    lines += ["", "Conversation:"]
    turns = []
    for m in working_memory:
        content = (m.get("content") or "").strip()
        if not content or m["role"] not in ("user", "assistant"):
            continue
        if m["role"] == "user" and content.startswith(COMPACTION_PREFACE):
            turns.append("Summary of the earlier conversation:\n" + content[len(COMPACTION_PREFACE):].strip())
            continue
        turns.append(("Customer: " if m["role"] == "user" else "Agent: ") + content)
    transcript = "\n".join(turns)
    if len(transcript) > REFLECTION_TRANSCRIPT_CHARS:
        transcript = "[earlier part of the conversation omitted]\n" + transcript[-REFLECTION_TRANSCRIPT_CHARS:]
    return "\n".join(lines) + "\n" + transcript


def make_reflection(provider: Provider, *, model: str, thinking: str) -> Callable[[SessionEndContext], dict[str, Any]]:
    """The SessionEnd hook: run the reflection sub-agent over the finished session and book the pass."""

    def reflection(ctx: SessionEndContext) -> dict[str, Any]:
        if not ctx.customer_id:
            return {"reflected": False, "remembered": 0, "merged": 0}  # a prospect's facts are the Lead
        started = time.perf_counter()
        written = {"remembered": 0, "merged": 0}
        tools = ToolRegistry()
        tools.register(make_save_memories(ctx.customer_id, ctx.pass_id, written))
        spec = SubagentSpec(
            name="reflection", model=model, system_prompt=REFLECTION_SYSTEM_PROMPT, tools=tools,
            max_rounds=1, thinking=thinking, cap_note=REFLECTION_CAP_NOTE, gave_up_brief="done",
        )
        profile = database.get_customer(ctx.customer_id) or {}
        task = reflection_task(profile.get("customer_name") or ctx.customer_id, ctx.working_memory, ctx.memories)
        error: str | None = None
        result = None
        try:
            result = run_subagent(spec, provider, task, ToolContext(ctx.session_id, ctx.customer_id, turn_id=ctx.pass_id))
        except Exception as exc:  # noqa: BLE001 — a failed reflection must not stop the session from ending
            error = f"{type(exc).__name__}: {exc}"[:500]
            log.warning("reflection failed for session %s", ctx.session_id, exc_info=True)
        record_turn(TurnRecord(
            turn_id=ctx.pass_id, session_id=ctx.session_id, customer_id=ctx.customer_id, model=model, kind="session_end",
            provider_calls=result.provider_calls if result else 0, tool_rounds=result.rounds if result else 0,
            tools_called=result.tool_calls if result else [],
            hook_outcomes={"reflected": written["remembered"], "merged": written["merged"]},
            subagent_calls=1, subagent_prompt_tokens=result.usage.prompt_tokens if result else 0,
            subagent_completion_tokens=result.usage.completion_tokens if result else 0,
            latency_ms=int((time.perf_counter() - started) * 1000), error=error,
        ))
        return {"reflected": error is None, **written}

    return reflection


def register_reflection(hooks: HookRegistry, provider: Provider, *, model: str, thinking: str) -> None:
    hooks.register(HookEvent.SESSION_END, make_reflection(provider, model=model, thinking=thinking))
