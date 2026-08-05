"""
Context Manager — Session memory with token-aware summarization.

Stores conversation turns in SQLite (via database.py).
When context exceeds MAX_TOKENS, older turns are LLM-compressed
into a running summary while recent turns stay raw.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import tiktoken
from dotenv import load_dotenv
from openai import OpenAI

from app.database import load_session, save_session

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MAX_CONTEXT_TOKENS = 4000
RESERVED_TOKENS = 1500      # system prompt + tool schemas + response format
AVAILABLE_TOKENS = MAX_CONTEXT_TOKENS - RESERVED_TOKENS  # 2500
KEEP_RAW_TURNS = 3           # always keep last N turns unsummarized
ENCODING = tiktoken.get_encoding("cl100k_base")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Turn:
    role: str         # "user" | "assistant" | "tool"
    content: str
    tool_name: str = ""
    timestamp: str = ""


@dataclass
class SessionContext:
    session_id: str
    customer_id: str | None = None
    turns: list[Turn] = field(default_factory=list)
    summary: str = ""          # LLM-compressed summary of older turns

    @property
    def recent_turns(self) -> list[Turn]:
        """Last KEEP_RAW_TURNS turns (raw, not summarized)."""
        return self.turns[-KEEP_RAW_TURNS:]

    @property
    def older_turns(self) -> list[Turn]:
        """Turns older than KEEP_RAW_TURNS (already in summary)."""
        return self.turns[:-KEEP_RAW_TURNS]


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------
def load_context(session_id: str) -> SessionContext:
    """Load session from SQLite and deserialize into SessionContext."""
    data = load_session(session_id)
    ctx = SessionContext(
        session_id=session_id,
        customer_id=data.get("customer_id"),
        summary=data.get("summary", ""),
    )
    for t in data.get("turns", []):
        ctx.turns.append(Turn(**t))
    return ctx


def save_context(ctx: SessionContext) -> None:
    """Serialize SessionContext to SQLite."""
    turns_raw = [
        {"role": t.role, "content": t.content,
         "tool_name": t.tool_name, "timestamp": t.timestamp}
        for t in ctx.turns
    ]
    save_session(
        session_id=ctx.session_id,
        turns=turns_raw,
        summary=ctx.summary,
        customer_id=ctx.customer_id,
    )


# ---------------------------------------------------------------------------
# Token counting & summarization
# ---------------------------------------------------------------------------
def _count_tokens(text: str) -> int:
    return len(ENCODING.encode(text))


def get_context_text(ctx: SessionContext) -> str:
    """
    Build the text injected into the LLM prompt.

    Claude Code approach — prioritize by recency and relevance:
      Layer 1 (always): Conversation summary (LLM-compressed)
      Layer 2 (priority): Last N turns raw
      Layer 3 (fallback): Individual turns truncated rather than dropped

    Budget: AVAILABLE_TOKENS (2500) total for conversation context.
    """
    if not ctx.turns:
        return ""

    parts = []
    token_budget = AVAILABLE_TOKENS

    # --- Layer 1: Summary (most compressed, always include) ---
    if ctx.summary:
        parts.append(f"[Previous conversation summary]\n{ctx.summary}")
        token_budget -= _count_tokens(parts[-1])

    # --- Layer 2: Recent turns raw (prioritize recency) ---
    raw_parts = []
    for t in reversed(ctx.turns[-KEEP_RAW_TURNS:]):
        line = f"[{t.role}]: {t.content}"
        tok = _count_tokens(line)
        if token_budget - tok >= 200:  # Leave 200 token margin
            raw_parts.insert(0, line)
            token_budget -= tok
        else:
            # Truncate this turn rather than dropping it entirely
            truncated = _truncate_to_tokens(t.content, max(token_budget - 200, 100))
            raw_parts.insert(0, f"[{t.role}]: {truncated}")
            token_budget = 200
            break

    if raw_parts:
        parts.append("\n".join(raw_parts))
        token_budget -= _count_tokens(parts[-1])

    # --- Layer 3: Older turns (if budget remains) ---
    older = ctx.turns[:-KEEP_RAW_TURNS]
    if older and token_budget > 500:
        older_lines = []
        for t in reversed(older):
            line = f"[{t.role} (older)]: {t.content[:200]}"
            tok = _count_tokens(line)
            if token_budget - tok >= 200:
                older_lines.insert(0, line)
                token_budget -= tok
            else:
                break
        if older_lines:
            parts.append("[Older turns]\n" + "\n".join(older_lines))

    return "\n\n".join(parts)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to fit within max_tokens, breaking at sentence boundaries."""
    if _count_tokens(text) <= max_tokens:
        return text
    # Binary search for approximate character cutoff
    chars = list(text)
    lo, hi = 0, len(chars)
    while lo < hi:
        mid = (lo + hi) // 2
        if _count_tokens("".join(chars[:mid])) < max_tokens:
            lo = mid + 1
        else:
            hi = mid
    cutoff = max(lo - 1, 0)
    # Back up to last sentence boundary
    truncated = "".join(chars[:cutoff])
    last_period = max(truncated.rfind(". "), truncated.rfind("? "), truncated.rfind("! "))
    if last_period > cutoff // 2:
        return truncated[:last_period + 1] + " [...]"
    return truncated[:cutoff] + " [...]"


def add_turn(ctx: SessionContext, role: str, content: str, tool_name: str = "") -> None:
    """Append a turn and trigger summarization if needed."""
    from datetime import datetime, timezone

    ctx.turns.append(Turn(
        role=role,
        content=content,
        tool_name=tool_name,
        timestamp=datetime.now(timezone.utc).isoformat(),
    ))

    # Check if summarization needed
    all_text = "\n".join(f"[{t.role}]: {t.content}" for t in ctx.turns)
    if _count_tokens(all_text) > AVAILABLE_TOKENS and len(ctx.turns) > KEEP_RAW_TURNS:
        _summarize(ctx)


def _summarize(ctx: SessionContext) -> None:
    """Compress older turns into ctx.summary using LLM."""
    if not ctx.older_turns:
        return

    old_text = "\n".join(
        f"[{t.role}]: {t.content}" for t in ctx.older_turns
    )
    existing = f"Previous summary: {ctx.summary}\n" if ctx.summary else ""

    client = OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Summarize the following conversation. Keep key facts: "
                    "customer name, business model, products discussed, "
                    "pain points, pricing discussions, and any decisions made. "
                    "Write in English, 2-4 sentences max."
                ),
            },
            {"role": "user", "content": f"{existing}\nNew turns:\n{old_text}"},
        ],
        temperature=0.0,
        max_tokens=300,
    )
    ctx.summary = (response.choices[0].message.content or "").strip()
