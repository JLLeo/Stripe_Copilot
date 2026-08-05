"""
Unit tests for turn metrics collection.

Tests the collector logic. DB persistence is exercised but assertions
focus on in-memory state so tests stay fast and isolated.
"""

import time

import pytest

from app.metrics import TurnMetrics, init_metrics


pytestmark = pytest.mark.unit


@pytest.fixture(scope="module", autouse=True)
def ensure_table():
    init_metrics()


class _FakeUsage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeResponse:
    def __init__(self, prompt_tokens=100, completion_tokens=50):
        self.usage = _FakeUsage(prompt_tokens, completion_tokens)


# =========================================================================
# Construction
# =========================================================================
def test_turn_id_is_unique():
    a = TurnMetrics(session_id="s1")
    b = TurnMetrics(session_id="s1")
    assert a.turn_id != b.turn_id


def test_defaults_are_zero():
    m = TurnMetrics(session_id="s1")
    assert m.llm_calls == 0
    assert m.tokens_in == 0
    assert m.tokens_out == 0
    assert m.cache_hits == 0
    assert m.iterations == 0
    assert m.tools_called == []
    assert not m.escalated
    assert m.error == ""


# =========================================================================
# Tool recording
# =========================================================================
def test_record_tool_appends():
    m = TurnMetrics(session_id="s1")
    m.record_tool("search_product_info")
    m.record_tool("lookup_pricing_tool")
    assert m.tools_called == ["search_product_info", "lookup_pricing_tool"]


def test_record_tool_counts_cache_hits():
    m = TurnMetrics(session_id="s1")
    m.record_tool("search_product_info", cache_hit=True)
    m.record_tool("search_product_info", cache_hit=False)
    assert m.cache_hits == 1
    assert len(m.tools_called) == 2


def test_unique_tools_deduplicates():
    m = TurnMetrics(session_id="s1")
    m.record_tool("search_product_info")
    m.record_tool("search_product_info")
    m.record_tool("lookup_policy_tool")
    assert m.unique_tools == ["search_product_info", "lookup_policy_tool"]


# =========================================================================
# LLM recording
# =========================================================================
def test_record_llm_increments_count():
    m = TurnMetrics(session_id="s1")
    m.record_llm()
    m.record_llm()
    assert m.llm_calls == 2


def test_record_llm_accumulates_tokens():
    m = TurnMetrics(session_id="s1")
    m.record_llm(_FakeResponse(100, 50))
    m.record_llm(_FakeResponse(200, 80))
    assert m.tokens_in == 300
    assert m.tokens_out == 130


def test_record_llm_without_response_still_counts():
    m = TurnMetrics(session_id="s1")
    m.record_llm(None)
    assert m.llm_calls == 1
    assert m.tokens_in == 0


def test_record_llm_tolerates_missing_usage():
    class NoUsage:
        pass

    m = TurnMetrics(session_id="s1")
    m.record_llm(NoUsage())
    assert m.llm_calls == 1
    assert m.tokens_in == 0


# =========================================================================
# Latency
# =========================================================================
def test_mark_stage_records_elapsed():
    m = TurnMetrics(session_id="s1")
    time.sleep(0.01)
    m.mark_stage("intent")
    assert "intent" in m.latency_stages
    assert m.latency_stages["intent"] >= 5  # at least ~10ms, allow scheduler jitter


def test_stages_are_sequential_not_cumulative():
    m = TurnMetrics(session_id="s1")
    time.sleep(0.02)
    m.mark_stage("first")
    time.sleep(0.01)
    m.mark_stage("second")
    # second stage measures only its own window, so it must be shorter
    assert m.latency_stages["second"] < m.latency_stages["first"]


def test_total_latency_grows():
    m = TurnMetrics(session_id="s1")
    first = m.latency_total_ms
    time.sleep(0.01)
    assert m.latency_total_ms > first


# =========================================================================
# Serialization
# =========================================================================
def test_to_dict_excludes_private_fields():
    m = TurnMetrics(session_id="s1")
    d = m.to_dict()
    assert not any(k.startswith("_") for k in d)
    assert d["session_id"] == "s1"
    assert "latency_total_ms" in d
    assert "tool_calls" in d


def test_to_dict_computes_tool_calls():
    m = TurnMetrics(session_id="s1")
    m.record_tool("a")
    m.record_tool("b")
    assert m.to_dict()["tool_calls"] == 2


# =========================================================================
# Persistence
# =========================================================================
def test_save_does_not_raise():
    m = TurnMetrics(
        session_id="test_save_session",
        customer_id="C001",
        sales_rep_id="rep1",
        query="test query",
    )
    m.intent = "marketplace"
    m.intent_method = "keyword"
    m.intent_confidence = 0.9
    m.record_tool("search_product_info")
    m.record_llm(_FakeResponse())
    m.mark_stage("intent")
    m.save()  # must not raise


def test_save_survives_bad_data():
    """Metrics must never break the request, even with odd values."""
    m = TurnMetrics(session_id="s1", query="x" * 5000)
    m.latency_stages = {"weird": float("inf")}
    m.save()  # must not raise
