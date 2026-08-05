"""
Comprehensive multi-turn test — covers ALL 6 tools across varied scenarios.

Usage: python test_all_tools.py
"""

import json
import time
import uuid

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
session_id = str(uuid.uuid4())

# Each turn targets specific tools and scenarios
turns = [
    # === search_product_info ===
    {
        "query": "What is Stripe Terminal and how does it work?",
        "customer_id": "",
        "label": "search_product_info — product feature lookup",
        "expect_tool": "search_product_info",
    },
    # === search_product_info (different product) ===
    {
        "query": "How does Stripe Radar detect fraud?",
        "customer_id": "",
        "label": "search_product_info — Radar fraud detection",
        "expect_tool": "search_product_info",
    },
    # === lookup_customer + lookup_product_usage (preloaded via customer_id) ===
    {
        "query": "What products is this customer using and what's their profile?",
        "customer_id": "C003",
        "label": "lookup_customer + lookup_product_usage — auto-preload",
        "expect_tool": "lookup_customer",
    },
    # === lookup_policy ===
    {
        "query": "What are the active sales policies for pricing and compliance? Check the policy database.",
        "customer_id": "",
        "label": "lookup_policy — sales policies lookup",
        "expect_tool": "lookup_policy_tool",
    },
    # === lookup_pricing ===
    {
        "query": "What are the standard payment processing rates and Billing costs? Use the pricing tool specifically.",
        "customer_id": "",
        "label": "lookup_pricing — pricing rates lookup",
        "expect_tool": "lookup_pricing_tool",
    },
    # === escalation via security_compliance ===
    {
        "query": "We need the SOC 2 report and penetration test results for our compliance audit.",
        "customer_id": "",
        "label": "escalation — security_compliance triggers",
        "expect_escalate": True,
    },
    # === escalation via pricing_negotiation with volume ===
    {
        "query": "Our company processes over $8M annually. Do we qualify for custom pricing?",
        "customer_id": "",
        "label": "escalation — pricing_negotiation with volume mention",
        "expect_escalate": True,
    },
]

print(f"=== All-Tool Coverage Test — {len(turns)} turns ===\n")

results = []
total_start = time.time()

for i, turn in enumerate(turns):
    t0 = time.time()
    r = client.post("/sales-agent/stream", json={
        "sales_rep_id": "test_rep",
        "customer_id": turn["customer_id"],
        "session_id": session_id,
        "message": turn["query"],
    })

    tools_called = []
    intent = ""
    escalate = False
    escalate_team = ""
    client_text = ""

    for line in r.text.split("\n"):
        if line.startswith("data:"):
            try:
                d = json.loads(line[6:])
                # Tool calls
                tn = d.get("tool_name", "")
                it = d.get("iteration", 0)
                if tn and it > 0:
                    tools_called.append(tn)
                # Done event
                if "intent" in d and "client_ready_response" in d:
                    intent = d.get("intent", "")
                    escalate = d.get("need_escalation", False)
                    escalate_team = d.get("escalation_team", "")
                    client_text = d.get("client_ready_response", "")[:150]
            except (json.JSONDecodeError, KeyError):
                pass

    elapsed = (time.time() - t0) * 1000

    # Check expectations
    tool_ok = True
    if "expect_tool" in turn:
        tool_ok = turn["expect_tool"] in tools_called

    esc_ok = True
    if "expect_escalate" in turn:
        esc_ok = escalate == turn["expect_escalate"]

    passed = tool_ok and esc_ok

    unique_tools = list(dict.fromkeys(tools_called))

    print(f"T{i+1}: {turn['label']}")
    print(f"  Query:      {turn['query'][:80]}")
    print(f"  Intent:     {intent}")
    print(f"  Tools ({len(tools_called)} calls, {len(unique_tools)} unique): {unique_tools}")
    if "expect_tool" in turn:
        print(f"  Expected:   {turn['expect_tool']} — {'OK' if tool_ok else 'MISSING'}")
    if "expect_escalate" in turn:
        print(f"  Escalate:   {escalate} -> {escalate_team} — {'OK' if esc_ok else 'WRONG'}")
    print(f"  Client:     {client_text[:120]}...")
    print(f"  Latency:    {elapsed:.0f}ms")
    print(f"  [{'PASS' if passed else 'FAIL'}]")
    print()

    results.append(passed)

total_elapsed = (time.time() - total_start) * 1000
passed = sum(results)
print(f"{'='*60}")
print(f"RESULTS: {passed}/{len(turns)} passed | {total_elapsed:.0f}ms total | {total_elapsed/len(turns):.0f}ms avg")

# Tool coverage summary
all_tools_seen = set()
for i, turn in enumerate(turns):
    # Re-parse for tool coverage (simplified)
    pass

print(f"\nTool coverage targets:")
for tool_name in ["search_product_info", "lookup_customer", "lookup_product_usage",
                   "lookup_policy_tool", "lookup_pricing_tool"]:
    print(f"  {tool_name}: targeted in test")
