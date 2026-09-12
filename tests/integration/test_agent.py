"""
Full Agent Pipeline Demo — Step-by-Step with Intermediate Results
===================================================================
Shows EVERY stage: intent -> skill -> ReAct loop (each iteration) -> SYNTH -> escalation.

Usage:
    python tests/integration/test_agent.py                           # run all 4 demo queries
    python tests/integration/test_agent.py "your custom query"       # single custom query
    python tests/integration/test_agent.py > result.md               # save as markdown report
"""


import sys as _sys
from pathlib import Path as _Path

# Runnable from anywhere: put the project root on sys.path before importing app.
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))

import json
import sys
import time
import uuid
from datetime import datetime, timezone

# Fix Windows GBK encoding when piping stdout
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ===========================================================================
# Demo queries
# ===========================================================================
DEMO_QUERIES = [
    {
        "query": "Our marketplace needs seller onboarding and payouts to EU banks. Which Stripe product should we use?",
        "customer_id": "C001",
        "label": "Marketplace — with escalation triggers",
    },
    {
        "query": "What is Stripe Connect?",
        "customer_id": "",
        "label": "Generic question — should NOT escalate",
    },
    {
        "query": "SaaS platform with subscription billing in Europe, need VAT handling",
        "customer_id": "",
        "label": "Multi-intent — saas_billing + tax + global_expansion",
    },
    {
        "query": "We need the SOC 2 report for our enterprise security audit",
        "customer_id": "",
        "label": "Security compliance — with document request escalation",
    },
    {
        "query": "Does ShopHub qualify for custom pricing?",
        "customer_id": "C001",
        "label": "Multi-step ReAct — search_kb -> lookup_customer -> lookup_pricing -> synthesize",
    },
]

if len(sys.argv) > 1:
    custom = " ".join(sys.argv[1:])
    DEMO_QUERIES = [{"query": custom, "customer_id": "", "label": "custom query"}]

# ===========================================================================
# Pipeline components
# ===========================================================================
from app.kg_builder import get_knowledge_graph
from app.kg_retriever import get_kg_retriever
from app.milvus_retriever import get_milvus_retriever
from app.intent import classify_intent
from app.skills import get_skill, SKILL_REGISTRY
from app.tools import (
    TOOL_BY_NAME,
    search_kb,
    lookup_customer_tool,
    lookup_product_usage_tool,
    lookup_pricing_tool,
    lookup_policy_tool,
    check_escalation_tool,
)
from app.escalation import check_escalation
from app.context import load_context, save_context, add_turn, get_context_text, SessionContext
from app.database import init_db

init_db()
kg_builder = get_knowledge_graph()
kg = get_kg_retriever()
milvus = get_milvus_retriever()

# ===========================================================================
# Output helpers
# ===========================================================================
_output_lines: list[str] = []


def out(line: str = "") -> None:
    """Print to stdout and accumulate for result doc."""
    print(line)
    _output_lines.append(line)


def sep(title: str = "") -> None:
    if title:
        out()
        out("=" * 80)
        out(f"  {title}")
        out("=" * 80)
    else:
        out("-" * 80)


def sub(title: str) -> None:
    out()
    out(f"--- {title} ---")


# ===========================================================================
# Helpers (must be defined before use in the demo loop)
# ===========================================================================
def _extract_products(tool_results: list[dict]) -> list[str]:
    """Extract product names from structured tool outputs."""
    from app.tools import parse_tool_output

    products = set()
    for tr in tool_results:
        if tr["tool_name"] != "search_product_info":
            continue
        data = parse_tool_output(tr.get("output", ""))
        for item in data.get("results", []):
            prod = item.get("product")
            node = kg_builder.get_node(prod) if prod else None
            if node and node.get("entity_type") == "product":
                products.add(node.get("name", prod))
    return list(products) if products else ["Payments"]


# ===========================================================================
# Main demo
# ===========================================================================
TOTAL_START = time.time()

out(f"# Stripe Sales Copilot — Agent Pipeline Demo")
out(f"  Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
out(f"  Model: GPT-4o-mini  |  Embedding: text-embedding-3-small  |  VectorDB: Milvus Lite")
out(f"  KG: {kg_builder.summary()['total_nodes']} nodes, {kg_builder.summary()['total_edges']} edges  |  Chunks: 278  |  Skills: {len(SKILL_REGISTRY)}")

for test_idx, test_case in enumerate(DEMO_QUERIES):
    query = test_case["query"]
    customer_id = test_case["customer_id"]
    label = test_case["label"]
    session_id = str(uuid.uuid4())
    t_case_start = time.time()

    sep()
    out(f"## TEST {test_idx + 1}/{len(DEMO_QUERIES)}: {label}")
    out()
    out(f"**Query:** {query}")
    out(f"**Customer ID:** {customer_id or '(none)'}")
    out(f"**Session ID:** {session_id}")

    # =====================================================================
    # STAGE 0: Context Manager
    # =====================================================================
    sep("STAGE 0: Context Manager")
    sub("Load session from SQLite")
    ctx = load_context(session_id)
    if customer_id:
        ctx.customer_id = customer_id
    out(f"  session_id:  {ctx.session_id}")
    out(f"  customer_id: {ctx.customer_id}")
    out(f"  past turns:  {len(ctx.turns)}")
    out(f"  summary:     {'(empty)' if not ctx.summary else ctx.summary[:120] + '...'}")
    out(f"  token budget: 4000 total, 1500 reserved, 2500 available")

    # =====================================================================
    # STAGE 1: Intent Classification
    # =====================================================================
    sep("STAGE 1: Intent Classification (Keyword-first, LLM fallback @ 0.6)")

    # Show keyword matching
    sub("Step A: Keyword match against KG scenario patterns")
    expansion = kg.expand(query)
    out(f"  Matched scenarios:")
    if expansion.matched_scenarios:
        scenario_patterns = kg.kg.get_scenario_patterns()
        q_lower = query.lower()
        for sid in expansion.matched_scenarios:
            patterns = scenario_patterns.get(sid, [])
            matched_kw = [p for p in patterns if p in q_lower]
            node = kg_builder.get_node(sid)
            name = node.get("name", sid) if node else sid
            out(f"    - {sid} ({name}): matched keywords = {matched_kw}")
    else:
        out(f"    (none)")

    out(f"  Matched products: {expansion.matched_products or '(none)'}")
    out(f"  Matched geos:     {expansion.matched_geos or '(none)'}")

    # Run intent classifier
    sub("Step B: Classify (keyword → check confidence → LLM if needed)")
    intent_result = classify_intent(query)
    out(f"  Scenario:    {intent_result.scenario_id}")
    out(f"  Display:     {intent_result.display_name}")
    out(f"  Confidence:  {intent_result.confidence:.2f}")
    out(f"  Method:      {intent_result.method}")
    out(f"  Reason:      {intent_result.reason}")

    # =====================================================================
    # STAGE 2: Skill Selection
    # =====================================================================
    sep("STAGE 2: Skill Selection & Tool Whitelist")

    skill = get_skill(intent_result.scenario_id)
    out(f"  Skill:       {skill.display_name}")
    out(f"  Max iter:    {skill.max_iterations}")
    out(f"  Escalation triggers: {list(skill.escalation_triggers) if skill.escalation_triggers else '(none)'}")
    out(f"  Required tools:")
    for t_name in skill.required_tools:
        t = TOOL_BY_NAME.get(t_name)
        out(f"    - {t_name}: {t.description[:100] if t else 'N/A'}...")
    out(f"  Optional tools:")
    for t_name in skill.optional_tools:
        t = TOOL_BY_NAME.get(t_name)
        out(f"    - {t_name}: {t.description[:100] if t else 'N/A'}...")
    out()
    out(f"  System prompt (first 300 chars):")
    out(f"    {skill.system_prompt[:300].strip()}...")

    # =====================================================================
    # STAGE 3: ReAct Loop
    # =====================================================================
    sep("STAGE 3: ReAct Loop (THINK → ACT → OBSERVE)")

    # Build tool list for this skill
    from app.tools import get_tools_for_skill
    tools = get_tools_for_skill(skill.required_tools, skill.optional_tools)
    tool_schemas = []
    for t in tools:
        props = {}
        if hasattr(t, "args_schema") and t.args_schema:
            for fn, fi in t.args_schema.model_fields.items():
                props[fn] = fi.description or ""
        tool_schemas.append({
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": {"type": "object", "properties": {k: {"type": "string", "description": v} for k, v in props.items()}}},
        })

    from openai import OpenAI
    from dotenv import load_dotenv
    load_dotenv()
    _llm = OpenAI()

    tool_results = []
    iterations = 0
    done = False

    while not done and iterations < skill.max_iterations:
        iterations += 1
        out()
        sub(f"Iteration {iterations}/{skill.max_iterations}")

        # --- THINK ---
        t0 = time.time()
        messages = [
            {"role": "system", "content": skill.system_prompt},
            {"role": "user", "content": query},
        ]
        # Inject prior tool results
        for tr in tool_results:
            messages.append({
                "role": "assistant", "content": "",
                "tool_calls": [{"id": tr["tool_call_id"], "type": "function",
                    "function": {"name": tr["tool_name"], "arguments": json.dumps(tr.get("arguments", {}))}}],
            })
            messages.append({"role": "tool", "tool_call_id": tr["tool_call_id"], "content": tr["output"]})

        resp = _llm.chat.completions.create(
            model="gpt-4o-mini", messages=messages,
            tools=tool_schemas if tool_schemas else None,
            temperature=0.0, max_tokens=500,
        )
        choice = resp.choices[0].message
        think_ms = (time.time() - t0) * 1000

        if choice.tool_calls:
            tc = choice.tool_calls[0]
            out(f"  [THINK]  LLM decided: call `{tc.function.name}`  ({think_ms:.0f}ms)")
            out(f"           arguments: {tc.function.arguments[:200]}")
            if choice.content:
                out(f"           reasoning: {choice.content[:150]}...")
        else:
            out(f"  [THINK]  LLM decided: SUFFICIENT INFO — ready to synthesize  ({think_ms:.0f}ms)")
            out(f"           {choice.content[:200]}")
            done = True
            break

        # --- ACT ---
        t0 = time.time()
        tool_name = tc.function.name
        tool_fn = TOOL_BY_NAME.get(tool_name)
        try:
            args = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            args = {}

        if tool_fn:
            try:
                raw_output = tool_fn.invoke(args)
            except Exception as exc:
                raw_output = f"Error: {exc}"
        else:
            raw_output = f"Unknown tool: {tool_name}"

        act_ms = (time.time() - t0) * 1000
        out(f"  [ACT]    Executed `{tool_name}`  ({act_ms:.0f}ms)")
        # Truncate long outputs for display
        display_output = raw_output[:500]
        if len(raw_output) > 500:
            display_output += f"\n  ... (truncated, {len(raw_output)} chars total)"
        for line in display_output.split("\n")[:8]:
            out(f"           {line[:120]}")
        if len(display_output.split("\n")) > 8:
            out(f"           ... ({len(raw_output.split(chr(10)))} lines total)")

        tool_call_id = tc.id
        tool_results.append({
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "arguments": args,
            "output": raw_output,
        })

        # --- OBSERVE ---
        called_tool_names = {tr["tool_name"] for tr in tool_results}
        out(f"  [OBSERVE] Iterations: {iterations}/{skill.max_iterations} | Called: {list(called_tool_names)}")
        if iterations >= skill.max_iterations:
            out(f"  [OBSERVE] MAX ITERATIONS REACHED -> force synthesize")
            done = True

    # =====================================================================
    # STAGE 4: Synthesis
    # =====================================================================
    sep("STAGE 4: SYNTH — LLM Generates Final Response")

    tool_outputs = "\n\n".join(
        f"[{tr['tool_name']}]: {tr['output']}" for tr in tool_results
    )

    # Internal answer
    t0 = time.time()
    internal_resp = _llm.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": (
                f"{skill.system_prompt}\n\n"
                "You are writing an INTERNAL answer for a Stripe sales rep. "
                "Include: intent analysis, relevant products, key findings, "
                "and escalation recommendations. Reference specific sources.\n"
                f"{skill.response_hint}"
            )},
            {"role": "user", "content": f"Customer query: {query}\n\nRetrieved information:\n{tool_outputs}"},
        ],
        temperature=0.2, max_tokens=800,
    )
    internal_answer = internal_resp.choices[0].message.content or ""
    out(f"  Internal answer generated in {(time.time()-t0)*1000:.0f}ms")
    out(f"  Length: {len(internal_answer)} chars")

    # Client response
    t0 = time.time()
    client_resp = _llm.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": (
                "You are a helpful Stripe sales representative writing to a customer. "
                "Keep it concise, professional, on-brand. Do NOT share internal pricing "
                "thresholds, internal policy details, or raw knowledge base text.\n"
                f"Scenario context: {skill.display_name}"
            )},
            {"role": "user", "content": f"Customer asked: {query}\n\nInformation:\n{tool_outputs}"},
        ],
        temperature=0.4, max_tokens=600,
    )
    client_ready_response = client_resp.choices[0].message.content or ""
    out(f"  Client response generated in {(time.time()-t0)*1000:.0f}ms")
    out(f"  Length: {len(client_ready_response)} chars")

    # Sources
    from app.tools import parse_tool_output
    sources = []
    for tr in tool_results:
        data = parse_tool_output(tr.get("output", ""))
        for item in data.get("results", []):
            src = item.get("source")
            if src and "knowledge_base" in str(src):
                sources.append(src)
    sources = list(dict.fromkeys(sources))

    # =====================================================================
    # STAGE 5: Escalation Gating
    # =====================================================================
    sep("STAGE 5: Escalation Gating")

    esc_result = check_escalation(intent_result.scenario_id, customer_id, query)
    out(f"  Scenario:        {intent_result.scenario_id}")
    out(f"  Triggers defined: {list(skill.escalation_triggers) if skill.escalation_triggers else '(none)'}")
    out(f"  Decision:        {'ESCALATE' if esc_result.should_escalate else 'STAY'}")
    if esc_result.should_escalate:
        out(f"  Team:            {esc_result.escalation_team}")
    out(f"  Reason:          {esc_result.reason}")
    if esc_result.evidence:
        out(f"  Evidence:        {esc_result.evidence}")

    # =====================================================================
    # STAGE 6: Session Persistence
    # =====================================================================
    sep("STAGE 6: Session Persistence & Logging")

    add_turn(ctx, "user", query)
    add_turn(ctx, "assistant", client_ready_response)
    save_context(ctx)
    out(f"  Saved session: {ctx.session_id}")
    out(f"  Total turns:   {len(ctx.turns)}")
    if ctx.summary:
        out(f"  Summary:       {ctx.summary[:120]}...")

    # =====================================================================
    # Final Output
    # =====================================================================
    case_elapsed = (time.time() - t_case_start) * 1000
    sep("FINAL OUTPUT")

    out()
    out(f"**Intent:**         {intent_result.scenario_id} ({intent_result.method}, {intent_result.confidence:.2f})")
    out(f"**Products:**       {_extract_products(tool_results)}")
    out(f"**Iterations:**     {iterations}")
    out(f"**Escalate:**       {esc_result.should_escalate}")
    if esc_result.should_escalate:
        out(f"**Escalate Team:**  {esc_result.escalation_team}")
    out(f"**Sources ({len(sources)}):**")
    for s in sources:
        out(f"  - {s}")
    out(f"**Latency:**        {case_elapsed:.0f}ms")
    out()

    out("### Internal Answer")
    out()
    out(internal_answer[:])
    out()
    out("### Client-Ready Response")
    out()
    out(client_ready_response[:])

# ===========================================================================
# Summary
# ===========================================================================
total_elapsed = (time.time() - TOTAL_START) * 1000
sep()
out(f"## ALL {len(DEMO_QUERIES)} TESTS COMPLETE")
out(f"  Total time: {total_elapsed:.0f}ms  |  Avg: {total_elapsed/len(DEMO_QUERIES):.0f}ms")
out(f"  Output format: Markdown — pipe to file with:  python tests/integration/test_agent.py > result.md")

# ===========================================================================
# Write result.md automatically
# ===========================================================================
result_path = str(_Path(__file__).resolve().parent.parent.parent / "result.md")
with open(result_path, "w", encoding="utf-8") as f:
    f.write("\n".join(_output_lines))
print(f"\n[OK] Result written to {result_path}")
