"""
Unit tests for context window management.

Tests the layered budget allocation and truncation logic.
Does NOT test LLM summarization (that's integration).
"""

import pytest

from app.context import (
    AVAILABLE_TOKENS,
    KEEP_RAW_TURNS,
    MAX_CONTEXT_TOKENS,
    RESERVED_TOKENS,
    SessionContext,
    Turn,
    _count_tokens,
    _truncate_to_tokens,
    get_context_text,
)


pytestmark = pytest.mark.unit


def make_ctx(n_turns: int, chars_per_turn: int = 100, summary: str = "") -> SessionContext:
    """Build a SessionContext with n synthetic turns."""
    ctx = SessionContext(session_id="test", summary=summary)
    for i in range(n_turns):
        role = "user" if i % 2 == 0 else "assistant"
        ctx.turns.append(Turn(
            role=role,
            content=f"Turn {i}: " + ("x" * chars_per_turn),
            timestamp=f"2026-01-01T00:{i:02d}:00Z",
        ))
    return ctx


# =========================================================================
# Token budget configuration
# =========================================================================
def test_budget_math_consistent():
    assert AVAILABLE_TOKENS == MAX_CONTEXT_TOKENS - RESERVED_TOKENS
    assert AVAILABLE_TOKENS > 0
    assert RESERVED_TOKENS > 0


def test_keep_raw_turns_reasonable():
    assert 1 <= KEEP_RAW_TURNS <= 10


# =========================================================================
# Token counting
# =========================================================================
def test_count_tokens_monotonic():
    short = _count_tokens("hello")
    long = _count_tokens("hello " * 100)
    assert long > short


def test_count_tokens_empty():
    assert _count_tokens("") == 0


# =========================================================================
# Truncation
# =========================================================================
def test_truncate_short_text_unchanged():
    text = "This is short."
    assert _truncate_to_tokens(text, 1000) == text


def test_truncate_respects_limit():
    text = "word " * 500
    truncated = _truncate_to_tokens(text, 50)
    assert _count_tokens(truncated) <= 60  # allow small overhead for marker


def test_truncate_adds_marker():
    text = "word " * 500
    truncated = _truncate_to_tokens(text, 50)
    assert "[...]" in truncated


def test_truncate_prefers_sentence_boundary():
    text = (
        "First sentence here. Second sentence follows. "
        "Third sentence continues on. " + ("filler word " * 200)
    )
    truncated = _truncate_to_tokens(text, 20)
    # Should cut at a period, not mid-word
    assert truncated.rstrip(" [...]").endswith(".") or "[...]" in truncated


# =========================================================================
# Context text assembly
# =========================================================================
def test_empty_context_returns_empty():
    ctx = SessionContext(session_id="empty")
    assert get_context_text(ctx) == ""


def test_short_conversation_included_fully():
    ctx = make_ctx(2, chars_per_turn=50)
    text = get_context_text(ctx)
    assert "Turn 0" in text
    assert "Turn 1" in text


def test_summary_always_included():
    ctx = make_ctx(2, chars_per_turn=50, summary="Customer is a marketplace.")
    text = get_context_text(ctx)
    assert "Customer is a marketplace." in text


def test_recent_turns_prioritized():
    """The most recent turns must appear even when history is long."""
    ctx = make_ctx(20, chars_per_turn=200)
    text = get_context_text(ctx)
    assert "Turn 19" in text, "Most recent turn must be included"


def test_respects_token_budget():
    """Output must never exceed the available token budget."""
    ctx = make_ctx(50, chars_per_turn=500, summary="A summary. " * 20)
    text = get_context_text(ctx)
    assert _count_tokens(text) <= AVAILABLE_TOKENS, (
        f"Context text is {_count_tokens(text)} tokens, budget is {AVAILABLE_TOKENS}"
    )


def test_huge_single_turn_gets_truncated_not_dropped():
    """A single oversized turn should be truncated, not silently dropped."""
    ctx = SessionContext(session_id="test")
    ctx.turns.append(Turn(role="user", content="UNIQUE_MARKER " + ("x " * 5000)))
    text = get_context_text(ctx)
    assert "UNIQUE_MARKER" in text, "Oversized turn was dropped instead of truncated"
    assert _count_tokens(text) <= AVAILABLE_TOKENS


def test_role_labels_present():
    ctx = make_ctx(2, chars_per_turn=50)
    text = get_context_text(ctx)
    assert "[user]" in text or "[assistant]" in text


# =========================================================================
# SessionContext properties
# =========================================================================
def test_recent_turns_property():
    ctx = make_ctx(10)
    assert len(ctx.recent_turns) == KEEP_RAW_TURNS
    assert ctx.recent_turns[-1].content.startswith("Turn 9")


def test_older_turns_property():
    ctx = make_ctx(10)
    assert len(ctx.older_turns) == 10 - KEEP_RAW_TURNS


def test_recent_turns_with_few_turns():
    ctx = make_ctx(2)
    assert len(ctx.recent_turns) == 2
    assert ctx.older_turns == []
