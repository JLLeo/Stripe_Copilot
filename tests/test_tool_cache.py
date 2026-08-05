"""
Unit tests for the per-session tool result cache.
"""

import time

import pytest

from app import tool_cache


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_cache():
    tool_cache.clear_all()
    yield
    tool_cache.clear_all()


# =========================================================================
# Key building
# =========================================================================
def test_key_is_stable_for_same_args():
    k1 = tool_cache.make_key("search_product_info", {"query": "fraud", "top_k": 5})
    k2 = tool_cache.make_key("search_product_info", {"top_k": 5, "query": "fraud"})
    assert k1 == k2, "Key must not depend on dict ordering"


def test_key_differs_for_different_args():
    k1 = tool_cache.make_key("search_product_info", {"query": "fraud"})
    k2 = tool_cache.make_key("search_product_info", {"query": "billing"})
    assert k1 != k2


def test_key_differs_for_different_tools():
    args = {"customer_id": "C001"}
    assert (
        tool_cache.make_key("lookup_customer_tool", args)
        != tool_cache.make_key("lookup_product_usage_tool", args)
    )


# =========================================================================
# Cacheability
# =========================================================================
@pytest.mark.parametrize("tool", [
    "search_product_info",
    "lookup_customer_tool",
    "lookup_product_usage_tool",
    "lookup_pricing_tool",
    "lookup_policy_tool",
])
def test_data_tools_are_cacheable(tool):
    assert tool_cache.is_cacheable(tool)


def test_escalation_tool_is_not_cacheable():
    """Escalation depends on the current query — never cache it."""
    assert not tool_cache.is_cacheable("check_escalation_tool")


def test_unknown_tool_is_not_cacheable():
    assert not tool_cache.is_cacheable("some_new_tool")


# =========================================================================
# Get / put
# =========================================================================
def test_put_then_get_returns_value():
    tool_cache.put("s1", "lookup_customer_tool", {"customer_id": "C001"}, "profile data")
    assert tool_cache.get("s1", "lookup_customer_tool", {"customer_id": "C001"}) == "profile data"


def test_get_miss_returns_none():
    assert tool_cache.get("s1", "lookup_customer_tool", {"customer_id": "C999"}) is None


def test_sessions_are_isolated():
    tool_cache.put("s1", "lookup_customer_tool", {"customer_id": "C001"}, "session-1 data")
    assert tool_cache.get("s2", "lookup_customer_tool", {"customer_id": "C001"}) is None


def test_non_cacheable_tool_is_not_stored():
    tool_cache.put("s1", "check_escalation_tool", {"scenario": "x"}, "decision")
    assert tool_cache.get("s1", "check_escalation_tool", {"scenario": "x"}) is None


def test_error_output_is_never_cached():
    tool_cache.put("s1", "search_product_info", {"query": "x"}, "ERROR: boom")
    assert tool_cache.get("s1", "search_product_info", {"query": "x"}) is None


def test_empty_session_id_is_noop():
    tool_cache.put("", "lookup_customer_tool", {"customer_id": "C001"}, "data")
    assert tool_cache.get("", "lookup_customer_tool", {"customer_id": "C001"}) is None


# =========================================================================
# Expiry
# =========================================================================
def test_entry_expires_after_ttl(monkeypatch):
    monkeypatch.setattr(tool_cache, "CACHE_TTL_SECONDS", 0.05)
    tool_cache.put("s1", "lookup_customer_tool", {"customer_id": "C001"}, "data")
    assert tool_cache.get("s1", "lookup_customer_tool", {"customer_id": "C001"}) == "data"
    time.sleep(0.08)
    assert tool_cache.get("s1", "lookup_customer_tool", {"customer_id": "C001"}) is None


# =========================================================================
# Bounds
# =========================================================================
def test_per_session_entry_limit(monkeypatch):
    monkeypatch.setattr(tool_cache, "MAX_ENTRIES_PER_SESSION", 3)
    for i in range(6):
        tool_cache.put("s1", "search_product_info", {"query": f"q{i}"}, f"result {i}")
    stats = tool_cache.stats()
    assert stats["entries"] <= 3
    assert stats["evictions"] > 0


def test_invalidate_clears_one_session():
    tool_cache.put("s1", "lookup_customer_tool", {"customer_id": "C001"}, "a")
    tool_cache.put("s2", "lookup_customer_tool", {"customer_id": "C002"}, "b")
    tool_cache.invalidate("s1")
    assert tool_cache.get("s1", "lookup_customer_tool", {"customer_id": "C001"}) is None
    assert tool_cache.get("s2", "lookup_customer_tool", {"customer_id": "C002"}) == "b"


# =========================================================================
# Stats
# =========================================================================
def test_stats_track_hits_and_misses():
    tool_cache.put("s1", "lookup_customer_tool", {"customer_id": "C001"}, "data")
    tool_cache.get("s1", "lookup_customer_tool", {"customer_id": "C001"})   # hit
    tool_cache.get("s1", "lookup_customer_tool", {"customer_id": "C999"})   # miss

    stats = tool_cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 0.5


def test_stats_zero_state():
    stats = tool_cache.stats()
    assert stats["hits"] == 0
    assert stats["hit_rate"] == 0.0
    assert stats["sessions"] == 0
