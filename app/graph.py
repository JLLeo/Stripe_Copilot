"""
ReAct Agent Loop
=================
Pipeline: INTENT -> SKILL -> [THINK -> ACT -> OBSERVE]* -> SYNTH -> ESCALATION

  THINK    — LLM decides: call a tool, or synthesize?
  ACT      — Execute the chosen tool
  OBSERVE  — Ingest tool output; check if more tools needed
  SYNTH    — LLM generates final internal + client responses

The loop is bounded by skill.max_iterations (hard limit); the LLM can also
stop early by not requesting a tool.

`_run_pipeline()` is the single implementation. Both entry points consume it:
  - stream_agent()  -> SSE events for the web UI
  - run_agent()     -> plain dict for the sync API and local scripts
"""

from __future__ import annotations

import json
import time as _time
import uuid
from typing import Iterator

import openai as _openai
from dotenv import load_dotenv
from openai import OpenAI

from app.context import (
    SessionContext,
    add_turn,
    load_context,
    save_context,
)

load_dotenv()
from app import tool_cache
from app.database import log_interaction
from app.escalation import check_escalation as gate_escalation
from app.intent import classify_intent
from app.metrics import TurnMetrics
from app.skills import SkillConfig, get_skill
from app.tools import TOOL_BY_NAME, get_tools_for_skill, parse_tool_output

# ======================================================================
# LLM call with retry
# ======================================================================
_llm = OpenAI()

_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.5  # seconds, multiplied exponentially


def _call_llm_with_retry(
    model: str = "gpt-4o-mini",
    messages: list[dict] | None = None,
    tools: list[dict] | None = None,
    temperature: float = 0.0,
    max_tokens: int = 500,
) -> dict:
    """
    Call OpenAI with retry on transient failures.

    Returns:
        {"ok": True, "response": ChatCompletion} on success.
        {"ok": False, "error": str} after all retries exhausted.
    """
    last_error = ""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = _llm.chat.completions.create(
                model=model,
                messages=messages or [],
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return {"ok": True, "response": resp}
        except _openai.RateLimitError as e:
            last_error = f"Rate limit: {e}"
            if attempt < _MAX_RETRIES:
                _time.sleep(_RETRY_BACKOFF ** attempt)
        except _openai.APIConnectionError as e:
            last_error = f"Connection error: {e}"
            if attempt < _MAX_RETRIES:
                _time.sleep(_RETRY_BACKOFF ** attempt)
        except _openai.APIStatusError as e:
            # 5xx = retryable, 4xx (except 429) = not retryable
            if e.status_code >= 500:
                last_error = f"Server error {e.status_code}: {e}"
                if attempt < _MAX_RETRIES:
                    _time.sleep(_RETRY_BACKOFF ** attempt)
            else:
                return {"ok": False, "error": f"Client error {e.status_code}: {e}"}
        except Exception as e:
            last_error = f"Unexpected error: {e}"
            if attempt < _MAX_RETRIES:
                _time.sleep(_RETRY_BACKOFF ** attempt)
    return {"ok": False, "error": f"All {_MAX_RETRIES} retries exhausted. Last: {last_error}"}


# ======================================================================
# SSE helper
# ======================================================================
def _sse(event: str, data: dict) -> str:
    """Format a Server-Sent Event line."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ======================================================================
# Pipeline helpers
# ======================================================================
def _prefetch_customer(customer_id: str, session_id: str = "") -> list[dict]:
    """
    Load customer profile + product usage as synthetic tool results.

    Invokes the real tools so the output format matches what the LLM sees
    when it calls them itself. Cached per session — customer data does not
    change mid-conversation.
    """
    if not customer_id:
        return []

    args = {"customer_id": customer_id}
    preloaded: list[dict] = []

    for tool_name, call_id in (
        ("lookup_customer_tool", "preload_customer"),
        ("lookup_product_usage_tool", "preload_usage"),
    ):
        output = tool_cache.get(session_id, tool_name, args)
        if output is None:
            tool_fn = TOOL_BY_NAME.get(tool_name)
            if tool_fn is None:
                continue
            try:
                output = tool_fn.invoke(args)
            except Exception:
                continue  # pre-fetch is best-effort
            tool_cache.put(session_id, tool_name, args, output)

        # Skip empty results (unknown customer, no products on record)
        data = parse_tool_output(output)
        if not data.get("profile") and not data.get("results"):
            continue

        preloaded.append({
            "tool_name": tool_name,
            "tool_call_id": call_id,
            "arguments": args,
            "output": output,
            "is_error": False,
        })

    return preloaded


def _build_multi_intent_hint(intent, primary_scenario: str) -> str:
    """Inject secondary scenario guidance when a query matches multiple intents."""
    secondary = [s for s in intent.all_matched if s != primary_scenario]
    if not secondary:
        return ""

    from app.kg_retriever import get_kg_retriever

    kg = get_kg_retriever()
    parts = ["\nMULTI-INTENT: This query also matched these topics:"]
    for sid in secondary[:3]:
        node = kg.kg.get_node(sid)
        name = node.get("name", sid) if node else sid
        prompt_first_line = get_skill(sid).system_prompt.split("\n")[0]
        parts.append(f"  - {name}: {prompt_first_line}")
    parts.append(
        "Address ALL of these topics in your response. "
        "Use the appropriate tools for each topic."
    )
    return "\n".join(parts)


def _extract_sources(tool_results: list[dict]) -> list[str]:
    """Collect source document paths from structured tool output."""
    sources: list[str] = []
    for tr in tool_results:
        data = parse_tool_output(tr.get("output", ""))
        if not data.get("ok"):
            continue
        for item in data.get("results", []):
            src = item.get("source")
            if src and "knowledge_base" in str(src):
                sources.append(src)
    return list(dict.fromkeys(sources))


OUT_OF_SCOPE_MESSAGE = (
    "I'm a Stripe sales assistant — I can help with questions about "
    "Stripe products, pricing, payment processing, security, compliance, "
    "and related topics. It looks like your question falls outside that scope. "
    "Could you rephrase it in terms of Stripe's products or services?"
)


# ======================================================================
# Core pipeline — single source of truth for both entry points
# ======================================================================
def _run_pipeline(
    query: str,
    sales_rep_id: str,
    customer_id: str,
    session_id: str,
) -> Iterator[tuple[str, dict]]:
    """
    Run the full agent pipeline, yielding (event_name, payload) at each stage.

    Both stream_agent() (SSE) and run_agent() (sync dict) consume this
    generator, so the two entry points can never drift apart.

    Events: act(preload) -> intent -> skill -> [think -> act -> observe]*
            -> synth -> escalation -> done   (or error at any point)
    """
    metrics = TurnMetrics(
        session_id=session_id,
        customer_id=customer_id,
        sales_rep_id=sales_rep_id,
        query=query,
    )
    try:
        # --- Session ---
        ctx = load_context(session_id)
        if customer_id and not ctx.customer_id:
            ctx.customer_id = customer_id

        # --- Pre-fetch customer profile ---
        preloaded_tool_results = _prefetch_customer(customer_id, session_id)
        for tr in preloaded_tool_results:
            metrics.record_tool(tr["tool_name"], cache_hit=True)
        if preloaded_tool_results:
            yield ("act", {
                "iteration": 0,
                "tool_name": "lookup_customer",
                "arguments": {"customer_id": customer_id},
                "output_preview": f"Auto-loaded profile for {customer_id}",
                "is_error": False,
            })
        metrics.mark_stage("preload")

        # --- Context hint ---
        context_hint = _build_context_hint(ctx)
        if preloaded_tool_results:
            context_hint = context_hint or {}
            context_hint["has_customer_profile"] = True

        # --- Stage 1: Intent ---
        intent = classify_intent(query, context_hint=context_hint)
        metrics.intent = intent.scenario_id
        metrics.intent_method = intent.method
        metrics.intent_confidence = intent.confidence
        if intent.method == "llm":
            metrics.record_llm()
        metrics.mark_stage("intent")

        yield ("intent", {
            "scenario": intent.scenario_id,
            "display_name": intent.display_name,
            "confidence": intent.confidence,
            "method": intent.method,
            "reason": intent.reason,
            "context_used": intent.context_used,
            "all_matched": intent.all_matched,
        })

        # --- Out-of-scope short-circuit ---
        if intent.scenario_id == "out_of_scope":
            yield ("skill", {
                "name": "Out of Scope",
                "max_iterations": 0,
                "required_tools": [],
                "optional_tools": [],
            })
            yield ("synth", {"status": "done", "internal_length": 0, "client_length": 0})
            yield ("escalation", {
                "should_escalate": False,
                "escalation_team": None,
                "reason": "Query is out of scope.",
                "evidence": "",
            })
            add_turn(ctx, "user", query)
            add_turn(ctx, "assistant", OUT_OF_SCOPE_MESSAGE)
            save_context(ctx)
            metrics.save()
            yield ("done", {
                "intent": "out_of_scope",
                "products": [],
                "internal_answer": f"Out of scope: {intent.reason}",
                "client_ready_response": OUT_OF_SCOPE_MESSAGE,
                "sources": [],
                "need_escalation": False,
                "escalation_team": None,
                "escalation_pending": False,
                "confidence": intent.confidence,
                "iterations": 0,
            })
            return

        # --- Stage 2: Skill ---
        skill = get_skill(intent.scenario_id)
        tools = get_tools_for_skill(skill.required_tools, skill.optional_tools)
        multi_intent_hint = _build_multi_intent_hint(intent, intent.scenario_id)

        yield ("skill", {
            "name": skill.display_name,
            "max_iterations": skill.max_iterations,
            "required_tools": list(skill.required_tools),
            "optional_tools": list(skill.optional_tools),
        })

        # --- Stage 3: ReAct Loop ---
        tool_results = list(preloaded_tool_results)
        iterations = 0
        # max_iterations=0 means skip the loop entirely (e.g. escalation_request)
        done = skill.max_iterations == 0

        while not done and iterations < skill.max_iterations:
            iterations += 1

            # THINK — rebuild messages from scratch each turn so tool_call_id
            # pairs always stay in the order the OpenAI API requires.
            tool_schemas = _build_tool_schemas(tools)
            messages = [
                {"role": "system", "content": _build_system_prompt(skill, tools) + multi_intent_hint},
                {"role": "user", "content": query},
            ]
            for tr in tool_results:
                messages.append({
                    "role": "assistant", "content": "",
                    "tool_calls": [{
                        "id": tr["tool_call_id"], "type": "function",
                        "function": {
                            "name": tr["tool_name"],
                            "arguments": json.dumps(tr.get("arguments", {})),
                        },
                    }],
                })
                messages.append({
                    "role": "tool", "tool_call_id": tr["tool_call_id"], "content": tr["output"],
                })

            called = {tr["tool_name"] for tr in tool_results}
            if iterations == 1 and "search_product_info" not in called and skill.required_tools:
                messages.append({
                    "role": "system",
                    "content": (
                        "Ground your answer in the knowledge base. Call "
                        "search_product_info first — every factual claim needs a source."
                    ),
                })

            yield ("think", {"iteration": iterations, "status": "thinking"})

            llm_result = _call_llm_with_retry(
                model="gpt-4o-mini", messages=messages,
                tools=tool_schemas if tool_schemas else None,
                temperature=0.0, max_tokens=500,
            )
            if not llm_result["ok"]:
                metrics.error = f"think: {llm_result['error']}"
                yield ("error", {"stage": "think", "message": llm_result["error"]})
                break
            metrics.record_llm(llm_result["response"])

            choice = llm_result["response"].choices[0].message
            if not choice.tool_calls:
                yield ("think", {
                    "iteration": iterations,
                    "decision": "synthesize",
                    "reasoning": (choice.content or "")[:300],
                })
                break

            tc = choice.tool_calls[0]
            yield ("think", {
                "iteration": iterations,
                "decision": "call_tool",
                "tool_name": tc.function.name,
                "reasoning": (choice.content or "")[:300],
            })

            # ACT
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            is_error = False
            cached = tool_cache.get(session_id, tool_name, args)
            if cached is not None:
                output = cached
                cache_hit = True
            else:
                cache_hit = False
                tool_fn = TOOL_BY_NAME.get(tool_name)
                if tool_fn is None:
                    output = f"ERROR: Unknown tool '{tool_name}'"
                    is_error = True
                else:
                    try:
                        output = tool_fn.invoke(args)
                    except Exception as exc:
                        output = f"ERROR: {type(exc).__name__}: {exc}"
                        is_error = True
                if not is_error:
                    tool_cache.put(session_id, tool_name, args, output)

            metrics.record_tool(tool_name, cache_hit=cache_hit)
            yield ("act", {
                "iteration": iterations,
                "tool_name": tool_name,
                "arguments": args,
                "output_preview": output[:300],
                "is_error": is_error,
                "cache_hit": cache_hit,
            })

            tool_results.append({
                "tool_name": tool_name,
                "tool_call_id": tc.id,
                "arguments": args,
                "output": output,
                "is_error": is_error,
            })

            # OBSERVE
            called_tool_names = {tr["tool_name"] for tr in tool_results}
            if is_error:
                consecutive = sum(1 for tr in reversed(tool_results) if tr.get("is_error"))
                if consecutive >= 2:
                    yield ("observe", {
                        "iteration": iterations,
                        "decision": "force_synthesize",
                        "reason": "2 consecutive tool errors",
                        "called": list(called_tool_names),
                    })
                    break

            yield ("observe", {
                "iteration": iterations,
                "decision": "continue",
                "called": list(called_tool_names),
            })

        # --- Stage 4: SYNTH ---
        metrics.iterations = iterations
        metrics.mark_stage("react_loop")
        yield ("synth", {"status": "generating"})

        customer_name = _get_customer_name_from_results(tool_results)
        tool_outputs_str = "\n\n".join(
            f"[{tr['tool_name']}]: {tr['output']}" for tr in tool_results
        )

        internal_resp = _call_llm_with_retry(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    f"{skill.system_prompt}\n\n"
                    "You are writing an INTERNAL answer for a Stripe sales rep. "
                    "Include: intent analysis, relevant products, key findings, "
                    "and escalation recommendations.\n" + skill.response_hint
                )},
                {"role": "user", "content": f"Query: {query}\n\nRetrieved:\n{tool_outputs_str}"},
            ],
            temperature=0.2, max_tokens=800,
        )
        if internal_resp["ok"]:
            metrics.record_llm(internal_resp["response"])
            internal_answer = internal_resp["response"].choices[0].message.content or ""
        else:
            metrics.error = f"synth_internal: {internal_resp['error']}"
            internal_answer = (
                f"LLM synth failed: {internal_resp['error']}\n\n"
                f"Raw:\n{_summarize_tool_results(tool_results)}"
            )

        client_resp = _call_llm_with_retry(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "You are a helpful Stripe sales rep writing to a customer. "
                    "Keep it concise, professional, on-brand. Do NOT share internal "
                    "pricing thresholds or policy details.\n"
                    f"Scenario: {skill.display_name}\n"
                    f"{'Customer name: ' + customer_name if customer_name else ''}\n"
                    "FORMAT: No email signatures. No placeholders like [Your Name]. "
                    "Write as a chat message the sales rep can copy and send directly."
                )},
                {"role": "user", "content": (
                    f"Customer{' ' + customer_name if customer_name else ''} asked: {query}\n\n"
                    f"Info:\n{tool_outputs_str}\n\n"
                    "IMPORTANT: Use the customer's actual name if provided. "
                    "Do NOT add signatures. Do NOT use placeholders."
                )},
            ],
            temperature=0.4, max_tokens=600,
        )
        if client_resp["ok"]:
            metrics.record_llm(client_resp["response"])
            client_ready = client_resp["response"].choices[0].message.content or ""
        else:
            metrics.error = f"synth_client: {client_resp['error']}"
            client_ready = (
                "Thank you for your question. I'd be happy to connect you with a specialist."
            )

        metrics.mark_stage("synth")
        yield ("synth", {
            "status": "done",
            "internal_length": len(internal_answer),
            "client_length": len(client_ready),
        })

        # --- Stage 5: Escalation ---
        esc_result = gate_escalation(intent.scenario_id, customer_id, query)

        # Context-aware LLM escalation: only when rules miss but history exists
        if not esc_result.should_escalate and ctx.turns and skill.escalation_triggers:
            from app.escalation import escalate_with_context
            context_summary = ctx.summary or " ".join(
                t.content[:100] for t in ctx.turns[-3:]
            )
            esc_result = escalate_with_context(
                intent.scenario_id, query, context_summary
            )
            metrics.record_llm()

        metrics.escalated = esc_result.should_escalate
        metrics.escalation_team = esc_result.escalation_team or ""
        metrics.mark_stage("escalation")

        yield ("escalation", {
            "should_escalate": esc_result.should_escalate,
            "escalation_team": esc_result.escalation_team,
            "reason": esc_result.reason,
            "evidence": esc_result.evidence,
        })

        # --- Persist + log ---
        add_turn(ctx, "user", query)
        add_turn(ctx, "assistant", client_ready)
        save_context(ctx)

        products = _extract_mentioned_products(tool_results)
        try:
            log_interaction(
                interaction_id=str(uuid.uuid4()),
                customer_id=customer_id,
                sales_rep_id=sales_rep_id,
                channel="api",
                customer_question=query,
                detected_intent=intent.scenario_id,
                mentioned_products=", ".join(products),
                customer_pain_points="",
                follow_up_action=(
                    esc_result.escalation_team or "" if esc_result.should_escalate else ""
                ),
            )
        except Exception:
            pass  # logging is best-effort

        metrics.save()

        yield ("done", {
            "intent": intent.scenario_id,
            "products": products,
            "internal_answer": internal_answer,
            "client_ready_response": client_ready,
            "sources": _extract_sources(tool_results),
            "need_escalation": esc_result.should_escalate,
            "escalation_team": esc_result.escalation_team,
            "escalation_pending": esc_result.should_escalate,
            "confidence": intent.confidence,
            "iterations": iterations,
            "metrics": {
                "latency_ms": metrics.latency_total_ms,
                "llm_calls": metrics.llm_calls,
                "tokens_in": metrics.tokens_in,
                "tokens_out": metrics.tokens_out,
                "cache_hits": metrics.cache_hits,
                "stages": metrics.latency_stages,
            },
        })

    except Exception as exc:
        metrics.error = f"{type(exc).__name__}: {exc}"
        metrics.save()
        yield ("error", {
            "stage": "pipeline",
            "message": f"{type(exc).__name__}: {exc}",
        })


# ======================================================================
# Entry point 1 — SSE stream (used by /sales-agent/stream + web UI)
# ======================================================================
def stream_agent(
    query: str,
    sales_rep_id: str,
    customer_id: str,
    session_id: str,
):
    """Yield the pipeline as Server-Sent Events."""
    for event, payload in _run_pipeline(query, sales_rep_id, customer_id, session_id):
        yield _sse(event, payload)


# ======================================================================
# Entry point 2 — sync dict (used by /sales-agent/chat + local scripts)
# ======================================================================
def run_agent(
    query: str,
    sales_rep_id: str,
    customer_id: str,
    session_id: str,
) -> dict:
    """
    Run the pipeline to completion and return a dict matching SalesAgentResponse.
    """
    done_payload: dict = {}
    error_payload: dict | None = None

    for event, payload in _run_pipeline(query, sales_rep_id, customer_id, session_id):
        if event == "done":
            done_payload = payload
        elif event == "error":
            error_payload = payload

    if not done_payload:
        # Pipeline failed before producing a result
        message = (error_payload or {}).get("message", "unknown error")
        return {
            "intent": "error",
            "recommended_stripe_products": [],
            "internal_answer": f"Pipeline error: {message}",
            "client_ready_response": (
                "I ran into a problem processing that request. Please try again."
            ),
            "sources": [],
            "need_escalation": False,
            "escalation_team": None,
            "confidence": 0.0,
        }

    return {
        "intent": done_payload["intent"],
        "recommended_stripe_products": done_payload["products"],
        "internal_answer": done_payload["internal_answer"],
        "client_ready_response": done_payload["client_ready_response"],
        "sources": done_payload["sources"],
        "need_escalation": done_payload["need_escalation"],
        "escalation_team": done_payload["escalation_team"] or None,
        "confidence": done_payload["confidence"],
    }


# ======================================================================
# Helpers
# ======================================================================
def _build_system_prompt(skill: SkillConfig, tools: list) -> str:
    tool_descriptions = "\n".join(
        f"  - {t.name}: {t.description}" for t in tools
    )
    return (
        f"{skill.system_prompt}\n\n"
        f"Available tools:\n{tool_descriptions}\n\n"
        "Prefer tools over memory for specific facts, rates, and policies. "
        "Call each tool you need ONCE — do not repeat the same call.\n"
        "Check the conversation context. Focus tools and response on "
        "previously discussed products or topics.\n"
        "If customer data is already loaded (AUTO-LOADED), use it directly."
    )


def _build_tool_schemas(tools: list) -> list[dict]:
    """Convert LangChain tools to OpenAI function-calling format."""
    schemas = []
    for t in tools:
        # Build parameters from tool's input schema
        props = {}
        required = []
        if hasattr(t, "args_schema") and t.args_schema:
            for field_name, field_info in t.args_schema.model_fields.items():
                props[field_name] = {
                    "type": "string",
                    "description": field_info.description or "",
                }
                if field_info.is_required():
                    required.append(field_name)

        schemas.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        })
    return schemas


def _build_context_hint(ctx: SessionContext) -> dict | None:
    """Extract minimal context from prior turns for intent classification."""
    if not ctx.turns:
        return None

    hint: dict = {}
    # Find the last user message to guess what was being discussed
    last_user_msg = ""
    for t in reversed(ctx.turns):
        if t.role == "user":
            last_user_msg = t.content
            break

    # Find the last assistant response (contains the product/topic)
    last_assistant_msg = ""
    for t in reversed(ctx.turns):
        if t.role == "assistant":
            last_assistant_msg = t.content
            break

    # Extract previous scenario: look for explicit mention in assistant response
    # or infer from knowledge base references
    previous_scenario = _infer_scenario_from_text(last_assistant_msg)

    hint["previous_scenario"] = previous_scenario or "general_inquiry"
    hint["previous_topic"] = last_user_msg[:200] if last_user_msg else "unknown"
    hint["turns"] = len(ctx.turns)

    if ctx.summary:
        hint["summary"] = ctx.summary

    return hint if hint.get("previous_scenario") else None


def _infer_scenario_from_text(text: str) -> str | None:
    """Quick heuristic: check which scenario keywords appear in the text."""
    if not text:
        return None
    from app.kg_retriever import get_kg_retriever
    kg = get_kg_retriever()
    patterns = kg.kg.get_scenario_patterns()
    text_lower = text.lower()
    scores = {}
    for sid, kws in patterns.items():
        score = sum(1 for kw in kws if kw in text_lower)
        if score > 0:
            scores[sid] = score
    if scores:
        return max(scores, key=scores.get)
    return None


def _get_customer_name_from_results(tool_results: list[dict]) -> str:
    """Read the customer name out of structured lookup_customer_tool output."""
    for tr in tool_results:
        if tr.get("tool_name") != "lookup_customer_tool":
            continue
        data = parse_tool_output(tr.get("output", ""))
        name = (data.get("profile") or {}).get("name")
        if name:
            return str(name)
    return ""


def _summarize_tool_results(tool_results: list[dict]) -> str:
    """Build a concise summary of tool results for fallback responses."""
    if not tool_results:
        return "(No tool results available)"
    lines = []
    for tr in tool_results:
        status = "[ERROR]" if tr.get("is_error") else "[OK]"
        lines.append(f"  {status} {tr['tool_name']}: {tr['output'][:200]}")
    return "\n".join(lines)


def _extract_mentioned_products(tool_results: list[dict]) -> list[str]:
    """Collect product names the customer already uses, from structured output."""
    products: list[str] = []
    for tr in tool_results:
        if tr.get("tool_name") != "lookup_product_usage_tool":
            continue
        data = parse_tool_output(tr.get("output", ""))
        for item in data.get("results", []):
            name = item.get("product")
            if name:
                products.append(str(name))
    return list(dict.fromkeys(products)) or ["Payments"]
