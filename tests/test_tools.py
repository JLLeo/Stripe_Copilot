"""
Unit tests for structured tool output.

Verifies every tool returns parseable JSON with a consistent shape.
SQL-backed tools run against the real (read-only) database; Milvus-backed
tools are marked integration.
"""

import json

import pytest

from app.tools import (
    ALL_TOOLS,
    TOOL_BY_NAME,
    check_escalation_tool,
    lookup_customer_tool,
    lookup_policy_tool,
    lookup_pricing_tool,
    lookup_product_usage_tool,
    parse_tool_output,
)


pytestmark = pytest.mark.unit


# =========================================================================
# parse_tool_output
# =========================================================================
def test_parse_valid_json():
    data = parse_tool_output('{"tool": "x", "ok": true, "results": []}')
    assert data["ok"] is True
    assert data["tool"] == "x"


def test_parse_invalid_json_returns_raw():
    data = parse_tool_output("ERROR: Unknown tool 'foo'")
    assert data["ok"] is False
    assert "ERROR" in data["raw"]


def test_parse_non_dict_json_returns_raw():
    data = parse_tool_output("[1, 2, 3]")
    assert data["ok"] is False


def test_parse_empty_string():
    data = parse_tool_output("")
    assert data["ok"] is False


# =========================================================================
# Every tool returns valid JSON
# =========================================================================
def test_customer_tool_returns_structured_profile():
    out = lookup_customer_tool.invoke({"customer_id": "C001"})
    data = parse_tool_output(out)
    assert data["ok"] is True
    assert data["tool"] == "lookup_customer_tool"
    profile = data["profile"]
    assert profile["name"]
    assert isinstance(profile["annual_payment_volume"], (int, float))


def test_customer_tool_unknown_id_returns_empty_not_error():
    out = lookup_customer_tool.invoke({"customer_id": "NOPE999"})
    data = parse_tool_output(out)
    assert data["ok"] is True          # graceful, not an exception
    assert data["results"] == []
    assert "message" in data


def test_product_usage_returns_list():
    out = lookup_product_usage_tool.invoke({"customer_id": "C001"})
    data = parse_tool_output(out)
    assert data["ok"] is True
    assert isinstance(data["results"], list)
    if data["results"]:
        item = data["results"][0]
        assert "product" in item
        assert "monthly_revenue" in item


def test_product_usage_unknown_customer():
    out = lookup_product_usage_tool.invoke({"customer_id": "NOPE999"})
    data = parse_tool_output(out)
    assert data["ok"] is True
    assert data["results"] == []


def test_pricing_tool_returns_documents():
    out = lookup_pricing_tool.invoke({"product_area": ""})
    data = parse_tool_output(out)
    assert data["ok"] is True
    assert data["tool"] == "lookup_pricing_tool"
    assert len(data["results"]) > 0
    assert "text" in data["results"][0]


def test_policy_tool_returns_structured_policies():
    out = lookup_policy_tool.invoke({"policy_area": "Security"})
    data = parse_tool_output(out)
    assert data["ok"] is True
    assert data["source"] in ("sql", "knowledge_base")
    if data["source"] == "sql" and data["results"]:
        item = data["results"][0]
        assert "title" in item
        assert "escalate_to" in item


def test_policy_tool_case_insensitive_area():
    lower = parse_tool_output(lookup_policy_tool.invoke({"policy_area": "security"}))
    upper = parse_tool_output(lookup_policy_tool.invoke({"policy_area": "Security"}))
    assert lower["source"] == upper["source"]


def test_escalation_tool_returns_decision():
    out = check_escalation_tool.invoke({
        "scenario": "escalation_request",
        "customer_id": "",
        "query": "connect me with someone",
    })
    data = parse_tool_output(out)
    assert data["ok"] is True
    assert data["should_escalate"] is True
    assert data["escalation_team"]


def test_escalation_tool_no_escalation_case():
    out = check_escalation_tool.invoke({
        "scenario": "ecommerce",
        "customer_id": "",
        "query": "how does checkout work",
    })
    data = parse_tool_output(out)
    assert data["ok"] is True
    assert data["should_escalate"] is False


# =========================================================================
# Registry consistency
# =========================================================================
def test_all_tools_registered_by_name():
    assert len(TOOL_BY_NAME) == len(ALL_TOOLS)
    for t in ALL_TOOLS:
        assert TOOL_BY_NAME[t.name] is t


def test_all_tools_have_descriptions():
    for t in ALL_TOOLS:
        assert t.description, f"{t.name} has no description"
        assert len(t.description) > 30, f"{t.name} description too terse"


def test_tool_names_are_distinct():
    names = [t.name for t in ALL_TOOLS]
    assert len(names) == len(set(names))


# =========================================================================
# Milvus-backed (integration)
# =========================================================================
@pytest.mark.integration
def test_search_product_info_returns_ranked_results():
    from app.tools import search_product_info

    out = search_product_info.invoke({"query": "Stripe Radar fraud detection", "top_k": 3})
    data = parse_tool_output(out)
    assert data["ok"] is True
    assert data["tool"] == "search_product_info"
    assert len(data["results"]) > 0

    first = data["results"][0]
    assert first["rank"] == 1
    assert "source" in first
    assert "relevance" in first
    assert "knowledge_base" in first["source"]
