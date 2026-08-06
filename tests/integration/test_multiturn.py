"""
Multi-turn Agent Test — Varied tool calls + escalation finale.

Usage:
    python test_multiturn.py
"""

import json
import time
import uuid

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
session_id = str(uuid.uuid4())

turns = [
    # Turn 1: Broad product question → should call search_kb
    {
        "query": "We run a marketplace platform. What Stripe products should we look at?",
        "customer_id": "",
        "expect_tools": ["search_product_info"],
        "expect_intent": "marketplace",
        "label": "Broad marketplace discovery",
    },
    # Turn 2: Customer-specific → should use preloaded customer data (lookup_customer + lookup_product_usage auto-loaded)
    {
        "query": "I'm with ShopHub, customer ID C001. What are we already using?",
        "customer_id": "C001",
        "expect_tools": ["lookup_customer", "lookup_product_usage"],
        "expect_intent": "general_inquiry",
        "label": "Customer-specific product usage lookup",
    },
    # Turn 3: Pricing with volume context → should call search_kb + lookup_pricing
    {
        "query": "What does Stripe Billing cost for a business our size?",
        "customer_id": "C001",
        "expect_tools": ["search_product_info", "lookup_pricing"],
        "expect_intent": "saas_billing",
        "label": "Billing pricing inquiry with customer context",
    },
    # Turn 4: Custom pricing negotiation → should escalate to Deal Desk (volume $12.5M > $1M)
    {
        "query": "Our annual volume is $12.5M. Do we qualify for custom pricing or volume discounts?",
        "customer_id": "C001",
        "expect_tools": ["search_product_info", "lookup_pricing"],
        "expect_intent": "pricing_negotiation",
        "expect_escalate": True,
        "label": "Custom pricing with enterprise volume — should escalate",
    },
    # Turn 5: Security compliance docs → should escalate to Security & Compliance
    {
        "query": "We need a penetration test report and SOC 2 attestation for our enterprise compliance audit.",
        "customer_id": "C001",
        "expect_tools": ["search_product_info"],
        "expect_intent": "security_compliance",
        "expect_escalate": True,
        "label": "Security compliance docs — should escalate to Security & Compliance",
    },
]

print(f"Multi-Turn Agent Test — {len(turns)} turns, session: {session_id[:8]}...")
print("=" * 80)

total_start = time.time()
passed = 0

for i, turn in enumerate(turns):
    t0 = time.time()
    r = client.post("/sales-agent/stream", json={
        "sales_rep_id": "test_rep",
        "customer_id": turn["customer_id"],
        "session_id": session_id,
        "message": turn["query"],
    })

    # Parse SSE events
    events = []
    tool_calls = []
    intent = ""
    escalate = False
    escalate_team = ""
    escalate_pending = False
    client_response = ""

    for line in r.text.split("\n"):
        if line.startswith("event:"):
            events.append(line[7:].strip())
        elif line.startswith("data:"):
            try:
                data = json.loads(line[6:])
                if "tool_name" in data and data.get("iteration", 0) > 0:
                    tool_calls.append(data["tool_name"])
                if "intent" in data and "client_ready_response" in data:
                    intent = data.get("intent", "")
                    escalate = data.get("need_escalation", False)
                    escalate_team = data.get("escalation_team", "")
                    escalate_pending = data.get("escalation_pending", False)
                    client_response = data.get("client_ready_response", "")
                if "decision" in data and data["decision"] == "call_tool":
                    tool_calls.append(data.get("tool_name", ""))
            except (json.JSONDecodeError, KeyError):
                pass

    elapsed = (time.time() - t0) * 1000

    # Verification
    intent_ok = turn["expect_intent"] in intent if intent else False
    tools_ok = any(et in tool_calls for et in turn["expect_tools"])
    esc_ok = (not turn.get("expect_escalate")) or escalate

    all_ok = intent_ok and tools_ok and esc_ok
    if all_ok:
        passed += 1

    status = "PASS" if all_ok else "FAIL"

    print(f"\n-- Turn {i+1}: {turn['label']} --")
    print(f"  Query:    {turn['query'][:80]}")
    print(f"  Intent:   {intent} (expected: {turn['expect_intent']}) {'OK' if intent_ok else 'MISMATCH'}")
    print(f"  Tools:    {tool_calls} (expected: {turn['expect_tools']}) {'OK' if tools_ok else 'MISSING'}")
    print(f"  Escalate: {escalate} -> {escalate_team} {'OK' if esc_ok else 'SHOULD_ESCALATE'}")
    print(f"  Pending:  {escalate_pending}")
    print(f"  Events:   {' -> '.join(events[:8])}")
    print(f"  Latency:  {elapsed:.0f}ms")
    print(f"  Client:   {client_response[:150]}...")
    print(f"  [{status}]")

total_elapsed = (time.time() - total_start) * 1000
print(f"\n{'='*80}")
print(f"RESULTS: {passed}/{len(turns)} passed | Total: {total_elapsed:.0f}ms | Avg: {total_elapsed/len(turns):.0f}ms")
