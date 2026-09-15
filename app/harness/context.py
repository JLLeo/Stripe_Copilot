"""
Context Budget — pressure relieved in tiers, compaction last (ADR 0006).

The prompt prefix is append-only and cached (ADR 0005), so rewriting working
memory is expensive in cache misses as well as in tokens. Relief therefore
runs rarely and in large steps, and only when the previous response reported
prompt tokens at or above the high-water mark:

1. Limits at the source live elsewhere — `result_cap`, `turn_result_budget`,
   the research sub-agent, and Attachments (`attachment_stub` here, the
   `read_attachment` tool).
2. Clearing: spent tool results from earlier turns are rendered as one-line
   stubs. Deterministic and free; often enough on its own.
3. Compaction: everything but a token-budgeted recent window is folded into
   one rolling summary written by the sub-agent model, capped in size, that
   records the active skills and the facts the agent recorded. The current
   customer message is never touched.

Triggers read the provider's reported `prompt_tokens`; the recent window and
the summary cap use a characters/4 estimate — there is no local tokenizer.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app import database
from app.harness.guardrails import INSTRUCTION_TOOLS, cut_at_boundary
from app.harness.provider import CompletionRequest, Provider, Usage, drain

log = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4  # the estimate used for sizing; decisions to act read the provider's numbers
CLEAR_MIN_CHARS = 200  # a stub is about this long, so smaller results are not worth clearing
ATTACHMENT_PREVIEW_CHARS = 400
COMPACTION_PREFACE = (
    "[Working memory was compacted. Below is a summary of the conversation so far; "
    "the most recent exchanges follow verbatim.]"
)
SUMMARY_CAP_NOTE = "\n[the summary was cut at its size cap]"
EXCHANGE_CHARS = 120_000  # what the summariser reads at most: the tail of a very long stretch

SUMMARY_SYSTEM_PROMPT = """You maintain the rolling summary of one conversation between Stripe's AI sales agent and a customer, so the agent can carry on after older messages leave its context. Write the new summary from the previous summary and the messages being compacted.

Keep: what the customer's business is and what they want; every concrete fact they stated (numbers, dates, volumes, products, constraints, decisions, who decides); what the agent recommended, quoted or promised, with the sources it cited; open questions and anything the agent said it would do next; where the conversation stands.
Drop: greetings, repetition, and anything the customer later corrected (keep the correction).
Form: third person, plain prose or short bullets, at most {max_words} words. No headings, no preamble, no advice."""


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# Attachments — the stub that stands in for a long customer message
# ---------------------------------------------------------------------------
def attachment_stub(attachment_id: int, text: str) -> str:
    preview = " ".join(text[:ATTACHMENT_PREVIEW_CHARS].split())
    return (
        f"[The customer sent a long message of {len(text):,} characters; it is kept as attachment {attachment_id} "
        f'and begins: "{preview}…" '
        f"Read it with read_attachment(id={attachment_id}, offset=0, limit=4000) and further pieces by offset before answering.]"
    )


# ---------------------------------------------------------------------------
# Relief
# ---------------------------------------------------------------------------
@dataclass
class Relief:
    """What one turn's relief did, for the books and the customer's client."""

    cleared: int = 0
    cleared_chars: int = 0
    compacted: bool = False
    failed: str | None = None  # the summary could not be produced; nothing was thrown away
    usage: Usage = field(default_factory=Usage)
    provider_calls: int = 0

    @property
    def happened(self) -> bool:
        return bool(self.cleared or self.compacted or self.failed)


def relieve(session: dict[str, Any], provider: Provider, config: Any) -> Relief:
    """Run the tiers for a session whose last response reported pressure; a no-op below the high-water mark."""
    last = int(session.get("last_prompt_tokens") or 0)
    high = config.high_water * config.context_budget_tokens
    relief = Relief()
    if last < high:
        return relief
    session_id = session["session_id"]

    cleared = database.clear_tool_results(session_id, min_chars=CLEAR_MIN_CHARS, exempt=INSTRUCTION_TOOLS)
    relief.cleared = len(cleared)
    relief.cleared_chars = sum(r["chars"] for r in cleared)
    estimated = last - relief.cleared_chars // CHARS_PER_TOKEN
    if estimated < high:
        database.set_last_prompt_tokens(session_id, estimated)
        return relief

    try:
        estimated = compact(session_id, session.get("customer_id"), provider, config, prompt_tokens_before=last, relief=relief)
    except Exception as exc:  # noqa: BLE001 — a failed summary must not fail the turn; the context is merely still large
        relief.failed = f"{type(exc).__name__}: {exc}"[:500]
        log.warning("compaction failed for session %s", session_id, exc_info=True)
        return relief
    if estimated is not None:
        database.set_last_prompt_tokens(session_id, estimated)
    return relief


# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------
def _window_start(rows: list[dict[str, Any]], budget_chars: int) -> int:
    """Index of the first row kept verbatim: the largest recent window within budget that starts at a customer message."""
    start = len(rows)
    total = 0
    for i in range(len(rows) - 1, -1, -1):
        total += rows[i]["chars"]
        if total > budget_chars:
            break
        start = i
    while start < len(rows) and rows[start]["role"] != "user":
        start += 1
    if start >= len(rows):  # even the last exchange is over budget: the current customer turn stays verbatim regardless
        start = max((i for i, r in enumerate(rows) if r["role"] == "user"), default=0)
    return start


def _skills_loaded(rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for r in rows:
        for call in r["message"].get("tool_calls") or ():
            if call["function"]["name"] == "Skill":
                try:
                    name = json.loads(call["function"]["arguments"]).get("name")
                except (TypeError, ValueError):
                    name = None
                if name and name not in out:
                    out.append(name)
    return out


def _confirmed_facts(session_id: str, customer_id: str | None) -> list[str]:
    """What the session established for certain, from the database rather than from what was said:
    a customer's facts recorded this session that are still active; a prospect's lead so far."""
    if customer_id:
        return [f"{m['kind']}: {m['fact']}" for m in database.session_memories(session_id, customer_id)]
    lead = database.get_lead(session_id)
    if not lead:
        return []
    fields = [(k, lead.get(k)) for k in database.LEAD_FIELDS]
    out = [f"{k.replace('_', ' ')}: {v:,}" if isinstance(v, int) else f"{k.replace('_', ' ')}: {v}" for k, v in fields if v not in (None, "")]
    if lead.get("recommended_products"):
        out.append("recommended: " + ", ".join(lead["recommended_products"]))
    return out


def _exchange(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for r in rows:
        m = r["message"]
        content = (m.get("content") or "").strip()
        if m["role"] == "user" and content:
            lines.append("Customer: " + content)
        elif m["role"] == "assistant":
            if content:
                lines.append("Agent: " + content)
            for call in m.get("tool_calls") or ():
                args = call["function"].get("arguments") or ""
                lines.append(f"Agent used {call['function']['name']}({args[:200]})")
    text = "\n".join(lines)
    if len(text) > EXCHANGE_CHARS:
        text = "[earlier part omitted]\n" + text[-EXCHANGE_CHARS:]
    return text


def _previous_summary_text(compaction: dict[str, Any] | None) -> str:
    """The model-written part of the last summary; the deterministic lines are recomputed each time."""
    if not compaction:
        return "(none)"
    body = compaction["summary"]
    if body.startswith(COMPACTION_PREFACE):
        body = body[len(COMPACTION_PREFACE):].strip()
    return re.sub(r"\n\nActive skills:.*$", "", body, flags=re.DOTALL).strip() or "(none)"


MIN_BODY_CHARS = 200  # the model's prose always keeps at least this much of the cap


def _fit(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: cut_at_boundary(text, max_chars)].rstrip() + SUMMARY_CAP_NOTE


def render_summary(
    summary: str, skills: list[str], facts: list[str], attachments: list[dict[str, Any]], max_chars: int
) -> str:
    """The summary message — preface, the model's prose, then what the harness knows for certain —
    never longer than `max_chars` in all: the certain lines are fitted first, the prose gets the rest."""
    tail = ["Active skills: " + (", ".join(skills) if skills else "none")]
    if facts:
        tail.append("Facts established this session: " + "; ".join(facts))
    if attachments:
        tail.append(
            "Attachments the customer sent, readable with read_attachment(id, offset, limit): "
            + "; ".join(f"attachment {a['id']} ({a['chars']:,} characters)" for a in attachments)
        )
    fixed = len(COMPACTION_PREFACE) + 4 + len(SUMMARY_CAP_NOTE)  # separators, and room for the note
    tail_budget = max(0, max_chars - fixed - MIN_BODY_CHARS)
    tail_text = "\n".join(tail)
    if len(tail_text) > tail_budget:
        tail_text = _fit(tail_text, tail_budget)
    body = _fit(" ".join(summary.split()), max(MIN_BODY_CHARS, max_chars - fixed - len(tail_text)))
    return "\n".join([COMPACTION_PREFACE, "", body, "", tail_text])


def compact(
    session_id: str, customer_id: str | None, provider: Provider, config: Any, *, prompt_tokens_before: int, relief: Relief
) -> int | None:
    """Fold everything before the recent window into one summary. Returns the estimated prompt size after, or None if there was nothing to fold.

    The window is sized to land at the low-water mark — the smaller of `recent_window_tokens`
    and what the low mark leaves once the summary has its share. When pressure persists but the
    window already holds everything, the window shrinks to the last customer turn, so a
    compaction always folds something unless a single turn is all there is.
    """
    previous, rows = database.load_message_rows(session_id)
    window_tokens = min(config.recent_window_tokens, int(config.low_water * config.context_budget_tokens) - config.summary_max_tokens)
    start = _window_start(rows, window_tokens * CHARS_PER_TOKEN)
    if start == 0:
        start = _window_start(rows, 0)  # the minimal window: the last customer turn
    old = rows[:start]
    if not old:
        return None  # one turn is all there is; nothing to fold

    skills = list((previous or {}).get("skills") or [])
    skills += [s for s in _skills_loaded(old) if s not in skills]
    facts = _confirmed_facts(session_id, customer_id)
    max_chars = config.summary_max_tokens * CHARS_PER_TOKEN
    task = (
        "Previous summary:\n" + _previous_summary_text(previous)
        + "\n\nMessages being compacted:\n" + _exchange(old)
    )
    completion, _ = drain(provider.complete(CompletionRequest(
        model=config.sub_model,
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT.format(max_words=max(50, config.summary_max_tokens * 3 // 4))},
            {"role": "user", "content": task},
        ],
        max_tokens=max(256, config.summary_max_tokens * 2),
        thinking="disabled",
    )))
    relief.usage = relief.usage + completion.usage
    relief.provider_calls += 1
    summary = render_summary(
        completion.content.strip() or "(the summariser returned nothing)", skills, facts,
        database.list_attachments(session_id), max_chars,
    )
    database.record_compaction(
        session_id, through_message_id=old[-1]["id"], summary=summary, skills=skills,
        model=completion.model or config.sub_model, prompt_tokens_before=prompt_tokens_before,
    )
    relief.compacted = True
    folded_chars = sum(r["chars"] for r in old) + (len(previous["summary"]) if previous else 0)
    return max(0, prompt_tokens_before - folded_chars // CHARS_PER_TOKEN + estimate_tokens(summary))
