"""
End-to-End Multi-Turn Conversation Test
=========================================
Simulates realistic sales conversations across multiple scenarios.
Validates: intent accuracy, tool usage, context retention, escalation gating.

Usage: python tests/integration/test_e2e.py
"""


import sys as _sys
from pathlib import Path as _Path

# Runnable from anywhere: put the project root on sys.path before importing app.
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))

import json
import time
import uuid

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# =========================================================================
# Conversation scenarios
# =========================================================================
CONVERSATIONS = [
    {
        "name": "Marketplace Discovery -> Fraud -> Pricing -> Escalation",
        "customer_id": "C001",
        "turns": [
            {
                "q": "Hi, we're ShopHub, a marketplace platform. We've been growing fast and need to understand what Stripe products might help us scale.",
                "expect_intent": "marketplace",
                "expect_tools": True,
            },
            {
                "q": "We've been around for a while — can you pull up our account and tell me what we're already using?",
                "expect_intent": None,  # any
                "expect_no_escalate": True,  # account lookup should NOT escalate
            },
            {
                "q": "We're seeing more fraud lately, especially from international sellers. What options do we have?",
                "expect_intent": "fraud_prevention",
                "expect_tools": True,
            },
            {
                "q": "What's our current pricing look like? With our volume, is there anything better available?",
                "expect_intent": "pricing_negotiation",
                "expect_tools": True,
            },
            {
                "q": "Actually, can you just connect me with someone who handles enterprise compliance?",
                "expect_escalate": True,
            },
        ],
    },
    {
        "name": "SaaS Billing -> Follow-up -> Tax -> Security",
        "customer_id": "",
        "turns": [
            {
                "q": "I run a SaaS company. Does Stripe support recurring subscription billing?",
                "expect_intent": "saas_billing",
                "expect_tools": True,
            },
            {
                "q": "yes",  # ultra-short follow-up
                "expect_intent": "saas_billing",  # should inherit context
                "expect_no_out_of_scope": True,
            },
            {
                "q": "We sell to customers in Germany and France. Do we need to handle VAT ourselves?",
                "expect_intent": "tax_compliance",
                "expect_tools": True,
            },
            {
                "q": "Our compliance team wants to know about your encryption standards and SOC 2 certification.",
                "expect_intent": "security_compliance",
                "expect_tools": True,
                "expect_no_escalate": True,  # info question, should NOT escalate
            },
        ],
    },
    {
        "name": "Out-of-scope handling + Recovery",
        "customer_id": "",
        "turns": [
            {
                "q": "What's the weather like today?",
                "expect_intent": "out_of_scope",
            },
            {
                "q": "Sorry — I meant, how does Stripe Checkout work?",
                "expect_intent": None,
                "expect_no_out_of_scope": True,
                "expect_tools": True,
            },
        ],
    },
    {
        "name": "Multi-intent single query",
        "customer_id": "",
        "turns": [
            {
                "q": "I need recurring billing for my SaaS and also want to know about fraud protection for international customers.",
                "expect_intent": None,
                "expect_tools": True,
                "expect_multi_topic": ["billing", "fraud"],
            },
        ],
    },
]


# =========================================================================
# Test runner
# =========================================================================
def run_turn(session_id: str, customer_id: str, query: str) -> dict:
    """Execute one turn and parse the SSE response."""
    r = client.post("/sales-agent/stream", json={
        "sales_rep_id": "e2e_test",
        "customer_id": customer_id,
        "session_id": session_id,
        "message": query,
    })

    result = {
        "intent": "",
        "tools": [],
        "escalate": False,
        "escalate_team": "",
        "client_response": "",
        "internal_answer": "",
        "sources": [],
        "error": None,
    }

    for line in r.text.split("\n"):
        if not line.startswith("data:"):
            continue
        try:
            d = json.loads(line[6:])
        except json.JSONDecodeError:
            continue

        # Tool calls
        tn = d.get("tool_name", "")
        it = d.get("iteration", 0)
        if tn and it > 0:
            result["tools"].append(tn)

        # Errors
        if "stage" in d and "message" in d:
            result["error"] = d["message"]

        # Final done event
        if "intent" in d and "client_ready_response" in d:
            result["intent"] = d.get("intent", "")
            result["escalate"] = d.get("need_escalation", False)
            result["escalate_team"] = d.get("escalation_team", "") or ""
            result["client_response"] = d.get("client_ready_response", "")
            result["internal_answer"] = d.get("internal_answer", "")
            result["sources"] = d.get("sources", [])

    result["tools"] = list(dict.fromkeys(result["tools"]))
    return result


def check_turn(turn_spec: dict, result: dict) -> tuple[bool, list[str]]:
    """Validate a turn against expectations."""
    issues = []

    if result["error"]:
        issues.append(f"ERROR: {result['error']}")
        return False, issues

    # Intent check
    if turn_spec.get("expect_intent"):
        if result["intent"] != turn_spec["expect_intent"]:
            issues.append(f"intent={result['intent']} (expected {turn_spec['expect_intent']})")

    # Out-of-scope check
    if turn_spec.get("expect_no_out_of_scope"):
        if result["intent"] == "out_of_scope":
            issues.append("classified as out_of_scope (should not be)")

    # Tool usage check
    if turn_spec.get("expect_tools"):
        if not result["tools"]:
            issues.append("no tools called (expected at least one)")

    # Escalation checks
    if turn_spec.get("expect_escalate"):
        if not result["escalate"]:
            issues.append("did not escalate (expected escalation)")
    if turn_spec.get("expect_no_escalate"):
        if result["escalate"]:
            issues.append(f"escalated to {result['escalate_team']} (should not escalate)")

    # Multi-topic coverage
    if turn_spec.get("expect_multi_topic"):
        cr = result["client_response"].lower()
        missing = [t for t in turn_spec["expect_multi_topic"] if t not in cr]
        if missing:
            issues.append(f"response missing topics: {missing}")

    return len(issues) == 0, issues


# =========================================================================
# Main
# =========================================================================
print("=" * 78)
print("END-TO-END MULTI-TURN CONVERSATION TEST")
print("=" * 78)

total_turns = 0
passed_turns = 0
total_start = time.time()
all_issues = []

for conv in CONVERSATIONS:
    session_id = str(uuid.uuid4())
    print(f"\n{'─' * 78}")
    print(f"CONVERSATION: {conv['name']}")
    print(f"Customer: {conv['customer_id'] or '(none)'} | Session: {session_id[:8]}")
    print(f"{'─' * 78}")

    for i, turn in enumerate(conv["turns"]):
        total_turns += 1
        t0 = time.time()
        result = run_turn(session_id, conv["customer_id"], turn["q"])
        elapsed = (time.time() - t0) * 1000

        ok, issues = check_turn(turn, result)
        if ok:
            passed_turns += 1
        else:
            all_issues.append(f"[{conv['name']} T{i+1}] {'; '.join(issues)}")

        status = "PASS" if ok else "FAIL"
        print(f"\n  T{i+1} [{status}] {elapsed:.0f}ms")
        print(f"    Q: {turn['q'][:85]}")
        print(f"    Intent:   {result['intent']}")
        print(f"    Tools:    {result['tools'] or '(none)'}")
        print(f"    Escalate: {result['escalate']}" + (f" -> {result['escalate_team']}" if result['escalate'] else ""))
        if result["sources"]:
            print(f"    Sources:  {len(result['sources'])} doc(s)")
        print(f"    Response: {result['client_response'][:110]}...")
        if issues:
            for issue in issues:
                print(f"    ISSUE: {issue}")

total_elapsed = (time.time() - total_start) * 1000

print(f"\n{'=' * 78}")
print(f"RESULTS: {passed_turns}/{total_turns} turns passed")
print(f"Total: {total_elapsed:.0f}ms | Avg: {total_elapsed/total_turns:.0f}ms per turn")
if all_issues:
    print(f"\nISSUES FOUND ({len(all_issues)}):")
    for issue in all_issues:
        print(f"  - {issue}")
print("=" * 78)
