"""
Intent Classifier — Keyword-first, LLM fallback, context-aware.

Confidence threshold: 0.6
  >= 0.6 → use keyword result (free, 0 latency)
  <  0.6 → call LLM for re-classification (~$0.001, ~500ms)

Multi-turn: context_hint from previous turns biases classification
  toward continuity when the current query is ambiguous.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from dotenv import load_dotenv
from openai import OpenAI

from app.kg_retriever import QueryExpansion, get_kg_retriever

load_dotenv()
from app.skills import list_scenarios

CONFIDENCE_THRESHOLD = 0.6
OUT_OF_SCOPE_THRESHOLD = 0.25   # Below this → treat as irrelevant
CONTEXT_BOOST = 0.15
AMBIGUITY_PRONOUNS = ("it", "that", "this", "they", "them", "those", "these")

# Keywords that suggest a Stripe-related question
STRIPE_SIGNAL_KEYWORDS = (
    "stripe", "payment", "checkout", "billing", "subscription", "invoice",
    "fraud", "connect", "radar", "terminal", "payout", "marketplace",
    "pci", "soc", "security", "compliance", "tax", "vat", "gst",
    "penetration test", "pen test",
    "api", "sdk", "card", "ach", "sepa", "wallet", "klarna",
    "pricing", "discount", "volume", "currency", "refund", "dispute",
    "onboarding", "kyc", "sandbox", "webhook", "sigma", "ledger",
)


def _is_ambiguous(query: str) -> bool:
    """Check if query is likely a follow-up referencing prior context."""
    q = query.lower().strip()
    # Short queries without product keywords
    words = q.split()
    if len(words) <= 5:
        return True
    # Contains reference pronouns
    for pronoun in AMBIGUITY_PRONOUNS:
        if f" {pronoun} " in f" {q} " or q.startswith(f"{pronoun} "):
            return True
    return False


@dataclass
class IntentResult:
    scenario_id: str
    display_name: str
    confidence: float
    method: str  # "keyword" | "llm" | "keyword+context"
    reason: str = ""
    context_used: bool = False
    all_matched: list[str] = None  # all scenarios that had keyword matches

    def __post_init__(self):
        if self.all_matched is None:
            self.all_matched = [self.scenario_id]


def classify_intent(
    query: str,
    context_hint: dict | None = None,
) -> IntentResult:
    """
    Classify user query into one of 12 scenarios.

    Args:
        query: The current user message.
        context_hint: Optional dict from prior turns:
            {"previous_scenario": "marketplace",
             "previous_topic": "Stripe Connect",
             "summary": "...",
             "turns": 2}

    1. Keyword match via KG scenario patterns
    2. Context boost: if ambiguous query, bias toward previous scenario
    3. If confidence < threshold, call LLM with context
    """
    previous_scenario = context_hint.get("previous_scenario") if context_hint else None

    # ------------------------------------------------------------------
    # Step A: Keyword match
    # ------------------------------------------------------------------
    kg = get_kg_retriever()
    expansion: QueryExpansion = kg.expand(query)

    # --- Fast-track: completely unrelated query? ---
    q_lower = query.lower()
    has_stripe_signal = any(kw in q_lower for kw in STRIPE_SIGNAL_KEYWORDS)

    all_matched_scenarios = list(expansion.matched_scenarios) if expansion.matched_scenarios else []

    if expansion.matched_scenarios:
        # Pick the most specific (most keyword matches)
        scenario_patterns = kg.kg.get_scenario_patterns()
        scenario_scores = {}
        for sid in expansion.matched_scenarios:
            patterns = scenario_patterns.get(sid, [])
            scenario_scores[sid] = sum(1 for p in patterns if p in q_lower)

        best_scenario = max(scenario_scores, key=scenario_scores.get)
        best_score = scenario_scores[best_scenario]

        # Normalize to 0-1 range (max observed is usually 3-5 matches)
        confidence = min(best_score / 3.0, 1.0)

        # --- Context boost for ambiguous follow-up queries ---
        if (
            previous_scenario
            and confidence < CONFIDENCE_THRESHOLD
            and _is_ambiguous(query)
            and previous_scenario in scenario_scores
        ):
            confidence = min(confidence + CONTEXT_BOOST, 1.0)
            best_scenario = previous_scenario

            if confidence >= CONFIDENCE_THRESHOLD:
                node = kg.kg.get_node(best_scenario)
                return IntentResult(
                    scenario_id=best_scenario,
                    display_name=node.get("name", best_scenario) if node else best_scenario,
                    confidence=confidence,
                    method="keyword+context",
                    reason=(
                        f"Ambiguous query boosted by context: previous='{previous_scenario}', "
                        f"boosted confidence={confidence:.2f}"
                    ),
                    context_used=True,
                    all_matched=all_matched_scenarios,
                )

        if confidence >= CONFIDENCE_THRESHOLD:
            node = kg.kg.get_node(best_scenario)
            return IntentResult(
                scenario_id=best_scenario,
                display_name=node.get("name", best_scenario) if node else best_scenario,
                confidence=confidence,
                method="keyword",
                reason=f"Keyword match: {best_score} patterns matched for '{best_scenario}'.",
                all_matched=all_matched_scenarios,
            )

        # Below threshold — fall through to LLM
        keyword_best = best_scenario
        keyword_confidence = confidence

        # Track all matched scenarios for context injection
        _all_matched = all_matched_scenarios
    else:
        keyword_best = None
        keyword_confidence = 0.0
        _all_matched = []

    # --- Fast-track out-of-scope: no keywords AND no Stripe signals AND no context ---
    has_context = bool(previous_scenario) or (context_hint and context_hint.get("turns", 0) > 0)
    has_customer = bool(context_hint and context_hint.get("has_customer_profile"))
    if keyword_best is None and not has_stripe_signal and not has_context and not has_customer:
        return IntentResult(
            scenario_id="out_of_scope",
            display_name="Out of Scope",
            confidence=0.05,
            method="keyword",
            reason="No Stripe-related keywords detected; query appears unrelated to Stripe products.",
        )

    # --- Ultra-short follow-up: skip LLM, return previous scenario directly ---
    if previous_scenario and len(query.strip().split()) <= 2:
        node = kg.kg.get_node(previous_scenario)
        return IntentResult(
            scenario_id=previous_scenario,
            display_name=node.get("name", previous_scenario) if node else previous_scenario,
            confidence=0.6,
            method="keyword+context",
            reason=f"Ultra-short follow-up; inheriting previous scenario '{previous_scenario}'.",
            context_used=True,
        )

    # --- Context: if zero keyword matches but we have history, bias toward previous ---
    if keyword_best is None and previous_scenario:
        keyword_best = previous_scenario
        keyword_confidence = 0.3

    # ------------------------------------------------------------------
    # Step C: LLM fallback
    # ------------------------------------------------------------------
    scenario_list = "\n".join(
        f"  - {sid}: {name}"
        for sid, name in _scenario_names().items()
    )

    # Build context-aware prompt
    context_block = ""
    if context_hint:
        parts = []
        if context_hint.get("previous_scenario"):
            parts.append(f"  Previous scenario: {context_hint['previous_scenario']}")
            parts.append(f"  Previous topic: {context_hint.get('previous_topic', 'unknown')}")
        if context_hint.get("has_customer_profile"):
            parts.append("  A customer profile is loaded and available for this query.")
            parts.append("  Questions like 'what products do they use' or 'what is their volume' refer to THIS customer.")
        if context_hint.get("summary"):
            parts.append(f"  Conversation summary: {context_hint['summary'][:300]}")
        if parts:
            context_block = "\nCONVERSATION CONTEXT:\n" + "\n".join(parts) + "\n"
        if context_hint.get("previous_scenario"):
            context_block += (
                "\nIMPORTANT: If the current query is a follow-up referencing the previous "
                "topic (e.g., 'how does it...', 'what about pricing for that?', 'tell me more'), "
                "classify it as the SAME scenario as the previous turn. "
                "Only switch scenarios if the user explicitly changes the topic.\n"
            )
        if context_hint.get("has_customer_profile"):
            context_block += (
                "\nIMPORTANT: A Stripe customer is currently selected. Even if the query "
                "does not explicitly mention Stripe products (e.g., 'what do they use?', "
                "'what is their volume?'), it IS in scope. Classify as general_inquiry "
                "or the most relevant scenario. Do NOT classify as out_of_scope.\n"
            )

    client = OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a Stripe sales intent classifier.\n"
                    "Classify the user's question into EXACTLY ONE of these scenarios:\n"
                    f"{scenario_list}\n"
                    "  - out_of_scope: ONLY for questions completely unrelated to Stripe, "
                    "payments, fintech, or business software.\n"
                    f"{context_block}\n"
                    "CRITICAL RULES:\n"
                    "- Questions about what a Stripe product IS or does (e.g. 'What is "
                    "Stripe Terminal?') should be classified based on the product's "
                    "primary use case, NOT as out_of_scope.\n"
                    "- Only classify as 'out_of_scope' for truly unrelated queries "
                    "(weather, jokes, sports, non-business topics) with confidence 0.0.\n"
                    "- If unsure between multiple scenarios, pick the most likely one "
                    "with moderate confidence, never out_of_scope.\n"
                    "Return ONLY valid JSON: "
                    '{"intent": "<scenario_id>", "confidence": <0.0-1.0>, "reason": "<brief>"}'
                ),
            },
            {"role": "user", "content": query},
        ],
        temperature=0.0,
        max_tokens=200,
    )

    raw = response.choices[0].message.content or "{}"
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        data = json.loads(raw)
        llm_intent = data.get("intent", keyword_best or "out_of_scope")
        llm_confidence = float(data.get("confidence", 0.0))
        llm_reason = data.get("reason", "LLM classification fallback.")
    except (json.JSONDecodeError, ValueError):
        llm_intent = keyword_best or "out_of_scope"
        llm_confidence = max(keyword_confidence, 0.0)
        llm_reason = "LLM returned unparseable output; using keyword fallback."

    # --- Out-of-scope gating ---
    has_customer = bool(context_hint and context_hint.get("has_customer_profile"))

    # Safety net: if query has Stripe signal words, it is NOT out_of_scope
    if has_stripe_signal and llm_intent == "out_of_scope":
        llm_intent = "general_inquiry"
        llm_confidence = 0.5
        llm_reason = "Query contains Stripe-related terms; overriding LLM out_of_scope classification."
    if has_customer and llm_intent == "out_of_scope":
        # Customer is selected — override LLM, force general_inquiry
        llm_intent = "general_inquiry"
        llm_confidence = 0.5
        llm_reason = "LLM classified as out_of_scope but customer profile is loaded; forced to general_inquiry."
    elif llm_intent == "out_of_scope" or llm_confidence < OUT_OF_SCOPE_THRESHOLD:
        return IntentResult(
            scenario_id="out_of_scope",
            display_name="Out of Scope",
            confidence=min(llm_confidence, 0.1),
            method="llm" if llm_intent == "out_of_scope" else "keyword",
            reason=llm_reason if llm_intent == "out_of_scope"
            else f"Confidence {llm_confidence:.2f} below out-of-scope threshold {OUT_OF_SCOPE_THRESHOLD}.",
            context_used=context_hint is not None,
        )

    # Validate intent is in registry
    valid_scenarios = list_scenarios()
    if llm_intent not in valid_scenarios:
        llm_intent = keyword_best or "out_of_scope"

    node = kg.kg.get_node(llm_intent)
    display = node.get("name", llm_intent) if node else llm_intent

    return IntentResult(
        scenario_id=llm_intent,
        display_name=display,
        confidence=llm_confidence,
        method="llm",
        reason=llm_reason,
        context_used=context_hint is not None,
    )


def _scenario_names() -> dict[str, str]:
    """Return {scenario_id: display_name} for all registered scenarios."""
    kg = get_kg_retriever()
    names = {}
    for sid in list_scenarios():
        # Look up from KG
        for eid in [
            "marketplace", "saas_billing", "b2b_invoicing", "ecommerce",
            "fraud_prevention", "global_expansion", "tax_compliance",
            "pricing_negotiation", "security_compliance", "financial_reporting",
            "no_code", "general_inquiry", "escalation_request",
        ]:
            node = kg.kg.get_node(eid)
            if node:
                names[eid] = node.get("name", eid)
        break  # Only need to iterate once since kg is shared
    return names if names else {s: s for s in list_scenarios()}
