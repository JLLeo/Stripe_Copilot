"""
Priming — the Skills a turn calls for, in the conversation before the model's first call (#14).

Before the first model call of a turn, the Decider is asked one yes/no question
per Skill whose body is not already in the conversation, all in one request,
about a small bounded state: the customer's message, the key profile fields,
the latest Customer Memory, the opening of the previous reply, and the skills
already loaded. What it names with enough confidence goes in as one
harness-authored `system` message just before the customer's new message
(`skills.primed_message`), persisted with the turn so the next turn's prefix is
the same bytes (ADR 0005).

The harness does no intent analysis of its own: the Decider reads the message
and names skills; this module only applies a fixed rule to the probabilities.

Two lines bound it:
- It only adds context. The model keeps every tool, `tool_choice` is never
  forced, and it can still load any other skill itself.
- Every failure is today's behaviour. If Priming is off, the Decider is slow or
  refuses, or nothing is named with confidence, the turn runs exactly as it
  would without Priming, and the reason is kept in the turn's metrics.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from app import database
from app.harness.decider import SKIP_PRIMING_OFF, Decider, YesNo
from app.harness.skills import Skill, primed_message

log = logging.getLogger(__name__)

MAX_PRIMED = 2  # one or two skills cover a turn; more above the threshold reads as an unsure answer
DECIDER_MESSAGE_CHARS = 4_000  # the opening of a long message states what it is about; the model still gets all of it
PREVIOUS_REPLY_CHARS = 500
MEMORY_ENTRIES = 3

# Why nothing was primed, beyond the Decider's own reasons (decider.py).
SKIP_ALL_LOADED = "all_loaded"  # every skill is already in the conversation; nothing to ask
SKIP_BELOW_THRESHOLD = "below_threshold"
SKIP_FLAT = "flat"  # three or more above the threshold with no clear leader
SKIP_ERROR = "error"  # something in Priming itself broke; the turn still runs

# The profile fields that say which area a business is in; the rest describe its size and maturity.
# Keys of database.CUSTOMER_PROFILE_FIELDS, so the Decider reads the profile the model reads.
PROFILE_KEYS = ("industry", "business_model", "use_case", "country", "annual_payment_volume", "primary_pain_point")


@dataclass(frozen=True)
class Priming:
    """What Priming did for one turn: the skills it put in and the message carrying them, or why it put in none."""

    skills: tuple[str, ...] = ()  # most probable first
    message: dict[str, Any] | None = None
    skipped: str | None = None
    decider_ms: int = 0


def prime(
    decider: Decider, config: Any, skills: dict[str, Skill], *,
    customer_id: str | None, message: str, working_memory: list[dict[str, Any]], in_context: set[str],
) -> Priming:
    """Ask the Decider about every skill not in context and apply the selection rule. Never raises."""
    if not config.priming:
        return Priming(skipped=SKIP_PRIMING_OFF)
    asked = {
        name: YesNo(f"Does the customer's latest message call for the {name} skill? {skill.description}")
        for name, skill in skills.items() if name not in in_context
    }
    if not asked:
        return Priming(skipped=SKIP_ALL_LOADED)
    started = time.perf_counter()
    try:
        state = _state(customer_id, message, working_memory, in_context)
        answers = decider.ask(state, asked)
        elapsed = int((time.perf_counter() - started) * 1000)
        if not answers.answered:
            return Priming(skipped=answers.skipped, decider_ms=elapsed)
        chosen, skipped = choose(
            {n: p for n, p in answers.probabilities.items() if n in asked}, config.priming_threshold, config.priming_margin,
        )
        if not chosen:
            return Priming(skipped=skipped, decider_ms=elapsed)
        return Priming(skills=tuple(chosen), message=primed_message(chosen, skills), decider_ms=elapsed)
    except Exception:  # noqa: BLE001 — the Decider's contract says it never raises; this is for when it, or this module, is wrong
        log.warning("priming failed; the turn goes on without it", exc_info=True)
        return Priming(skipped=SKIP_ERROR, decider_ms=int((time.perf_counter() - started) * 1000))


def choose(probabilities: dict[str, float], threshold: float, margin: float) -> tuple[list[str], str | None]:
    """The selection rule: (the skills to prime, most probable first) or ([], why none).

    None at or above the threshold → none. One or two → those. Three or more → the top one
    only if it leads the third by the margin; otherwise none, because a flat answer is an
    unsure one and the model fetching its own skill costs a round, not the customer.
    """
    ranked = sorted(probabilities.items(), key=lambda kv: (-kv[1], kv[0]))
    above = [name for name, p in ranked if p >= threshold]
    if not above:
        return [], SKIP_BELOW_THRESHOLD
    if len(above) <= MAX_PRIMED:
        return above, None
    if ranked[0][1] - ranked[2][1] >= margin:
        return [ranked[0][0]], None
    return [], SKIP_FLAT


def _state(customer_id: str | None, message: str, working_memory: list[dict[str, Any]], in_context: set[str]) -> dict[str, Any]:
    """What the Decider reads: bounded, and the same keys every turn."""
    profile = database.get_customer(customer_id) if customer_id else None
    customer = None
    remembered: list[str] = []
    if profile is not None:
        customer = {key: profile.get(key) for key in PROFILE_KEYS}
        customer["products_in_use"] = sorted(
            row["product_name"] for row in database.get_customer_product_usage(customer_id) if row.get("product_name")
        )
        remembered = [f"{m['kind']}: {m['fact']}" for m in database.active_memories(customer_id, limit=MEMORY_ENTRIES)]
    previous = next(
        (m["content"] for m in reversed(working_memory) if m["role"] == "assistant" and (m.get("content") or "").strip()), "",
    )
    return {
        "customer_message": message[:DECIDER_MESSAGE_CHARS],
        "customer": customer,
        "remembered": remembered,
        "previous_agent_reply": previous.strip()[:PREVIOUS_REPLY_CHARS],
        "skills_in_context": sorted(in_context),
    }
