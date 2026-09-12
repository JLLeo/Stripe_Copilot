# Stripe Sales Copilot — Agent Architecture

## Overview

KG + Milvus RAG pipeline wrapped in a hand-rolled ReAct agent loop.
Intent-first routing with LLM fallback. Scenario-specific Skill configs. Strict escalation gating.
Existing SQLite database (`data/stripe_sales_copilot.db`) reused for customer lookups.

**Scale as deployed:** 21 KB documents · 80 KG entities / 150 relationships · 278 Milvus chunks ·
6 tools · 14 skill configs (13 classifiable scenarios) · 7 SQLite tables · 198 unit tests

---

## System Diagram

```
                          User Query + session_id + customer_id
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SESSION LOAD + CUSTOMER PREFETCH              │
│  1. load_context(session_id) → turns + summary from SQLite      │
│  2. If customer_id present: invoke lookup_customer_tool and     │
│     lookup_product_usage_tool, inject as synthetic tool_results │
│     (cache-backed — see Tool Result Cache)                      │
│  3. Build context_hint: previous_scenario, previous_topic,      │
│     summary, has_customer_profile                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    INTENT CLASSIFIER (context-aware)             │
│  Step A: Keyword match against KG scenario patterns             │
│          (13 sales_scenario nodes, 95 question_patterns)        │
│          confidence = min(matched_patterns / 3, 1.0)            │
│                                                                  │
│  Step B: Context boost — ambiguous query + prior scenario in     │
│          candidates → confidence += 0.15                        │
│                                                                  │
│  Step C: confidence >= 0.6 → use keyword result, skip LLM       │
│                                                                  │
│  Step D: out-of-scope fast-track — 0 scenarios AND 0 Stripe     │
│          signal words AND no history AND no customer → block    │
│                                                                  │
│  Step E: ultra-short follow-up (<= 2 words) → inherit previous  │
│                                                                  │
│  Step F: otherwise → LLM re-classification with context block   │
│                                                                  │
│  Output: IntentResult(scenario_id, confidence, method,           │
│                       reason, context_used, all_matched)         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SKILL INJECTION                               │
│  skill = SKILL_REGISTRY[intent]                                  │
│  tools = get_tools_for_skill(required, optional)                 │
│                                                                  │
│  Supplies:                                                       │
│    - system_prompt        → THINK + SYNTH system message        │
│    - required/optional    → tool whitelist visible to the LLM   │
│    - max_iterations       → hard loop bound (0-3)               │
│    - escalation_triggers  → gate A of escalation                │
│    - response_hint        → SYNTH output shaping                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ReAct LOOP  (skipped when max_iterations=0)   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              THINK (LLM, function calling)               │    │
│  │  Messages rebuilt from scratch each iteration:           │    │
│  │    system(skill + tools + multi-intent hint)             │    │
│  │    user(query)                                           │    │
│  │    for tr in tool_results:                               │    │
│  │        assistant(tool_calls=[tr]) + tool(tr.output)      │    │
│  │  Output: tool_calls[0]  OR  no tool_calls → break        │    │
│  └──────────────────┬──────────────────────────────────────┘    │
│                     ▼                                            │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │               ACT (cache → tool → cache write)           │    │
│  │                                                          │    │
│  │  search_product_info(query, top_k=5)                     │    │
│  │    → KG expand → Milvus vector search (public only)      │    │
│  │  lookup_customer_tool(customer_id)                       │    │
│  │    → SQL customers                                       │    │
│  │  lookup_product_usage_tool(customer_id)                  │    │
│  │    → SQL customer_product_usage ⋈ stripe_products        │    │
│  │  lookup_pricing_tool(product_area)                       │    │
│  │    → reads knowledge_base/pricing/*.md directly          │    │
│  │  lookup_policy_tool(policy_area)                         │    │
│  │    → SQL sales_policy_updates, KB search as fallback     │    │
│  │  check_escalation_tool(scenario, customer_id, query)     │    │
│  │    → escalation gate rules → team or None                │    │
│  │                                                          │    │
│  │  All six return JSON. Exceptions become "ERROR: ..."     │    │
│  │  strings with is_error=True — the loop never dies.       │    │
│  └──────────────────┬──────────────────────────────────────┘    │
│                     ▼                                            │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │            OBSERVE                                        │    │
│  │  - Append result to tool_results                         │    │
│  │  - 2 consecutive is_error → force synthesize             │    │
│  │  - else → back to THINK (bounded by max_iterations)      │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SYNTHESIZER (2 LLM calls)                     │
│  internal_answer   temp=0.2, 800 tok — reasoning + findings      │
│                    + escalation recommendation, for the rep      │
│  client_ready      temp=0.4, 600 tok — customer-facing text,     │
│                    customer name injected, no signatures,        │
│                    no [Your Name] placeholders                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ESCALATION GATE                               │
│  Tier 1  check_escalation()      rules + volume thresholds       │
│  Tier 2  escalate_with_context() LLM, only if rules miss AND     │
│                                  history exists AND scenario     │
│                                  has triggers                    │
│  Tier 3  stay                                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PERSIST                                       │
│  - add_turn ×2 + save_context   → session_memory                │
│  - log_interaction              → sales_interactions            │
│  - metrics.save()               → turn_metrics                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                         done event / Response JSON
```

---

## Single-Pipeline Architecture

`_run_pipeline()` [graph.py:206](app/graph.py#L206) is the **only** implementation of the
agent loop. It is a generator yielding `(event_name, payload)` tuples. Both
entry points consume it, so they can never drift apart:

```
                      _run_pipeline()
                   (generator, single impl)
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
      stream_agent()                 run_agent()
   yields _sse(event, data)    collects "done" -> dict
              │                           │
              ▼                           ▼
   POST /sales-agent/stream      POST /sales-agent/chat
        (web UI, SSE)            (sync API, local scripts)
```

Before this refactor the two entry points had **separate implementations**
(one via LangGraph `StateGraph`, one inline) and had already diverged —
multi-intent hints and several prompt fixes existed only in the streaming
path, and `run_agent()`'s source extraction was silently returning `[]`.
Unifying them removed 467 lines and the LangGraph dependency.

---

## Skill Layer — Configuration, Not Runtime

Skills are **immutable config objects** that shape LLM behavior in THINK and
SYNTH. There is no skill execution layer. One skill = one scenario.

```python
# app/skills.py:13
@dataclass(frozen=True)
class SkillConfig:
    scenario_id: str
    display_name: str
    system_prompt: str                       # → THINK + SYNTH system message
    required_tools: tuple[str, ...] = ()     # → tool whitelist
    optional_tools: tuple[str, ...] = ()     # → tool whitelist
    max_iterations: int = 3                  # → loop bound
    escalation_triggers: tuple[str, ...] = ()# → escalation gate A
    response_hint: str = ""                  # → SYNTH output shaping
```

`SKILL_REGISTRY` [skills.py:44](app/skills.py#L44) holds **14 entries**:
12 product scenarios + `escalation_request` + `out_of_scope`.
The last is a terminal state — the pipeline short-circuits before the loop.

### Why config and not a runtime layer

| Approach | Problem |
|---|---|
| Skill as separate runtime layer | Two routing mechanisms (Tool Router + Skill Router). The LLM already does tool selection inside ReAct. |
| Skill as prompt text only | LLM can still reach for an unrelated tool. |
| **Skill as config + tool whitelist (chosen)** | LLM keeps autonomy inside scenario boundaries. Unavailable tools are not even in the function schema, so they cannot be hallucinated. |

Adding a scenario = adding one `SkillConfig` entry. No new code.

---

## Scenario → Skill → Tool Mapping

The LLM sees exactly `required_tools ∪ optional_tools` for the active scenario
[tools.py:341](app/tools.py#L341). **No tool call is forced** — `required_tools`
only widens the whitelist and adds a one-line grounding nudge on iteration 1
[graph.py:349](app/graph.py#L349). The LLM decides what to actually call.

| Scenario | Required | Optional | Max iter | Escalation triggers |
|---|---|---|---|---|
| **marketplace** | `search_product_info` | `lookup_customer_tool`, `lookup_product_usage_tool`, `lookup_policy_tool`, `lookup_pricing_tool` | 3 | "custom onboarding", "cross-border payout", "KYC verification", "multi-party payment flow" |
| **saas_billing** | `search_product_info`, `lookup_pricing_tool` | `lookup_customer_tool`, `lookup_policy_tool` | 3 | — |
| **b2b_invoicing** | `search_product_info` | `lookup_customer_tool`, `lookup_policy_tool`, `lookup_pricing_tool` | 2 | — |
| **ecommerce** | `search_product_info` | `lookup_customer_tool`, `lookup_policy_tool`, `lookup_pricing_tool` | 2 | — |
| **fraud_prevention** | `search_product_info` | `lookup_customer_tool`, `lookup_policy_tool`, `lookup_pricing_tool` | 3 | — |
| **global_expansion** | `search_product_info` | `lookup_pricing_tool` | 3 | — |
| **tax_compliance** | `search_product_info` | `lookup_policy_tool` | 2 | "filing", "registration", "tax return", "VAT return" |
| **pricing_negotiation** | `search_product_info` | `lookup_pricing_tool` | 3 | "custom pricing", "volume discount", "enterprise pricing", "IC+ pricing", "interchange plus" · **+ volume > $1M** |
| **security_compliance** | `search_product_info` | `lookup_policy_tool` | 2 | — |
| **financial_reporting** | `search_product_info` | `lookup_policy_tool`, `lookup_pricing_tool` | 2 | — |
| **no_code** | `search_product_info` | `lookup_policy_tool`, `lookup_pricing_tool` | 2 | — |
| **general_inquiry** | `search_product_info` | `lookup_policy_tool`, `lookup_pricing_tool` | 2 | — |
| **escalation_request** | — | — | **0** | 13 explicit phrases → Sales Ops / Human Agent |
| **out_of_scope** | — | — | **0** | — |

`escalation_request` and `out_of_scope` run **zero** LLM iterations — they skip
the loop entirely and go straight to SYNTH (or, for out_of_scope, to a fixed reply).

Note `fraud_prevention` and `security_compliance` have **no** triggers. This was
deliberate: both were escalating on nearly every query. Only 4 of 14 scenarios
can auto-escalate.

---

## Intent Classification Detail

```
Priority: Keyword > Context Boost > Out-of-Scope Fast-Track
          > Ultra-Short Inheritance > LLM > Out-of-Scope Gate

    Query + context_hint(previous_scenario, previous_topic, summary,
                         turns, has_customer_profile)
      │
      ▼
    A. KG keyword match  [intent.py:95-116]
       confidence = min(matched_patterns / 3, 1.0)
       all_matched recorded for multi-intent handling
      │
      ├── confidence >= 0.6  → USE, method="keyword", 0 tokens
      │
      ├── ambiguous (<=5 words or pronoun) + previous_scenario in candidates
      │   → confidence += 0.15  [intent.py:118-141]
      │   → if >= 0.6: USE, method="keyword+context"
      │
      ▼
    B. Out-of-scope fast-track  [intent.py:165-175]
       0 scenarios AND 0 of 40 Stripe signal words
       AND no history AND no customer profile
       → out_of_scope, confidence 0.05, 0 tokens, 0 latency
      │
      ▼
    C. Ultra-short follow-up  [intent.py:177-187]
       previous_scenario exists AND query <= 2 words ("yes", "tell me more")
       → inherit previous scenario, skip the LLM entirely
      │
      ▼
    D. LLM fallback  [intent.py:194-260]
       gpt-4o-mini, temp=0, 200 tok, JSON out
       Prompt carries the context block + explicit rules:
         - "What is Stripe Terminal?" → classify by product use case,
           NEVER out_of_scope
         - out_of_scope only for weather/jokes/sports
         - when unsure, pick the likeliest scenario, never out_of_scope
      │
      ▼
    E. Post-LLM safety nets  [intent.py:275-297]
       has_stripe_signal AND llm says out_of_scope → force general_inquiry
       has_customer_profile AND llm says out_of_scope → force general_inquiry
       else out_of_scope OR confidence < 0.25 → block
       intent not in SKILL_REGISTRY → fall back to keyword result
```

Two safety nets exist because the LLM over-interpreted "sales intent classifier"
and rejected pure product-knowledge questions ("What is Stripe Terminal?" → out_of_scope).

**Multi-intent:** `IntentResult.all_matched` keeps every matched scenario. The
primary drives the skill; secondaries are injected into the THINK system prompt
as the first line of each secondary skill's `system_prompt`
[graph.py:159](app/graph.py#L159). No skill switching — all tools stay available.

---

## Escalation Gating

```
Tier 1 — check_escalation()  [escalation.py:81]
  Gate A: skill.escalation_triggers non-empty?   → else never escalate
  Gate B: explicit multi-word phrase in query?
          "talk to a human" not "human"
          "SOC report" not "audit"
          "custom onboarding" not "onboarding"
  Volume: pricing_negotiation AND volume > $1M   → Deal Desk
          volume > $10M AND scenario in (pricing_negotiation, saas_billing)
                                                 → Enterprise Sales (overrides)
  Routing: matched triggers → TEAM_ROUTING → 7 teams

Tier 2 — escalate_with_context()  [escalation.py:166]
  Fires only when: rules missed AND ctx.turns non-empty
                   AND skill.escalation_triggers non-empty
  Prompt is deliberately harsh: "Be EXTREMELY strict. ONLY escalate if the
  user EXPLICITLY demands a human." Explicit do-not-escalate list covers
  account lookups, product questions, pricing inquiries.

Tier 3 — stay.  9 of 13 classifiable scenarios never auto-escalate.
```

**Escalation-eligible (4 of 14):** `marketplace`, `tax_compliance`,
`pricing_negotiation`, `escalation_request`.

**Teams (7):** Connect Specialist · Deal Desk / Pricing Team · Enterprise Sales ·
Fraud / Risk Team · Sales Ops / Human Agent · Security & Compliance · Tax Team.

`TEAM_ROUTING` [escalation.py:30](app/escalation.py#L30) holds 40 phrase→team
entries. It is a superset of the active triggers — phrases like "dispute rate too
high" and "SOC report" are routable but currently unreachable, because
`fraud_prevention` and `security_compliance` have empty trigger tuples. Re-enabling
those scenarios is a one-line change with routing already in place.

**Confirmation flow:** escalation never routes silently. The `done` event carries
`escalation_pending: true`, the UI shows a confirm dialog, and only an explicit
click hits `POST /sales-agent/confirm-escalation`.

---

## Context Management

### Session memory

Stored per `session_id` in `session_memory`:

```
turns:      JSON [{role, content, tool_name, timestamp}]
summary:    LLM-compressed older turns (2-4 sentences)
customer_id: nullable
```

### Three-layer context window [context.py:98](app/context.py#L98)

```
Budget: MAX_CONTEXT_TOKENS 4000
      − RESERVED_TOKENS   1500  (system prompt + tool schemas + response room)
      = AVAILABLE_TOKENS  2500  for conversation

Layer 1  summary            always included, ~100-200 tokens
Layer 2  last 3 turns raw   per-turn budget check; a turn that does not fit is
                            TRUNCATED, not dropped — _truncate_to_tokens() binary-
                            searches the char cutoff then backs up to the last
                            sentence boundary
Layer 3  older turns        200-char excerpts, only if >500 tokens remain

200-token margin reserved throughout so the LLM always has room to answer.
```

Summarization fires inside `add_turn()` when total turn tokens > 2500 **and**
turns > 3 [context.py:191](app/context.py#L191). It is incremental: previous
summary + newly-aged turns → new summary.

Token counting uses `tiktoken` `cl100k_base` — the same encoding gpt-4o-mini uses.

### Customer auto-preload [graph.py:114](app/graph.py#L114)

When `customer_id` is present, before the loop starts:

```
1. lookup_customer_tool(customer_id)      → injected as a synthetic tool_result
2. lookup_product_usage_tool(customer_id) → injected as a synthetic tool_result
3. Both appear in every THINK message as prior assistant/tool pairs
4. Empty results are skipped, so unknown customers add nothing
```

These invoke the **real tools**, not separate formatters, so the bytes match what
the LLM sees when it calls them itself — which is also why both paths share one
cache key.

Preload also sets `context_hint["has_customer_profile"] = True`, which stops the
out-of-scope fast-track from blocking customer-specific queries that contain no
Stripe keywords ("what do they use?").

---

## Tool Contract

Every tool returns **JSON**, not prose [tools.py:38](app/tools.py#L38).

```json
{
  "tool": "search_product_info",
  "ok": true,
  "query": "Stripe Radar fraud detection",
  "matched_products": ["radar", "checkout", "connect"],
  "results": [
    {
      "rank": 1,
      "product": "radar",
      "source": "knowledge_base/payment/radar.md",
      "relevance": 0.851,
      "text": "Stripe Radar is an AI-powered fraud protection system..."
    }
  ],
  "note": "Covers product features only. For pricing rates, call lookup_pricing_tool."
}
```

Three shapes:
- `_ok(tool, **payload)` — success
- `_empty(tool, message, **payload)` — success with `results: []` and an explanation
  (an unknown customer is not an error)
- `"ERROR: {type}: {msg}"` — raised by the pipeline's exception handler, not by
  the tools themselves

`parse_tool_output()` [tools.py:51](app/tools.py#L51) recovers the dict; non-JSON
input returns `{"ok": False, "raw": ...}`. Source extraction, product extraction,
and customer-name lookup all read structured fields instead of splitting strings.

---

## Tool Result Cache

[tool_cache.py](app/tool_cache.py) — per-session, TTL-bounded, in-process.

```
Key:     f"{tool_name}:{sha256(json.dumps(args, sort_keys=True))[:16]}"
         sort_keys makes argument order irrelevant — the LLM does not emit
         a stable key order.
TTL:     900s, absolute from write (a cache hit does NOT extend it)
Bounds:  50 entries/session (oldest-first eviction)
         200 sessions (LRU by last_access, swept on every put)
Storage: {session_id: {key: _Entry}} — isolation is structural, not prefix-based,
         because lookup_customer_tool returns customer PII

Cacheable:     search_product_info, lookup_customer_tool,
               lookup_product_usage_tool, lookup_pricing_tool, lookup_policy_tool
Not cacheable: check_escalation_tool — a decision, not a data read
Never cached:  output starting with "ERROR:" — otherwise one transient Milvus
               blip poisons the whole 15-minute session
```

Measured on customer preload, which fires every turn:

```
Turn 1 preload: 24.4ms   (2 SQL queries)
Turn 2 preload:  0.8ms   (cache hit)
```

That 24ms is ~0.1% of a 20s turn — the number matters as a **correctness signal**
(cross-turn keys really do hit) rather than as a latency win. The real value is
`search_product_info` hits, which skip an embedding API call plus an ANN search,
and the reduced SQL load under concurrency.

Known limits: in-process (multi-worker deploys get one cache per worker); no
active invalidation (a mid-session external write goes unseen for up to 15 min);
`_evict_stale_sessions()` computes-then-deletes without a lock.

---

## Observability

[metrics.py](app/metrics.py) writes one `turn_metrics` row per turn.

| Field group | Captured |
|---|---|
| Intent | scenario, method (keyword / keyword+context / llm), confidence |
| Tools | names called, total calls, cache hits |
| Loop | ReAct iterations |
| LLM | call count, prompt tokens, completion tokens |
| Latency | total + per stage: preload, intent, react_loop, synth, escalation |
| Outcome | escalated, escalation_team, error |

`save()` is wrapped in a bare `except` — observability must never break a request.
The `done` SSE event also carries a compact `metrics` object for the UI.

`GET /api/metrics?days=7` [main.py:130](app/main.py#L130) exposes:

```
summary()          latency, token totals, cache hit rate, escalation rate, error rate
intent_breakdown() per-intent turns, latency, keyword-vs-LLM split
tool_usage()       call counts per tool
tool_cache.stats() live hits/misses/evictions/hit_rate
```

Measured over 20 recorded turns:

```
avg_latency_ms  9865.3      avg_iterations  1.30
avg_tool_calls  1.65        cache_hit_rate  0.424
llm_calls       65          tokens_in 64708 / tokens_out 9873
escalation_rate 0.10        error_rate      0.00

tool_usage: search_product_info 15 · lookup_customer_tool 7 ·
            lookup_product_usage_tool 7 · lookup_pricing_tool 3 ·
            lookup_policy_tool 1
```

Representative single turns:

```
saas_billing        keyword  llm=5 iter=3 tools=3  16212ms
  {preload: 0.1, intent: 0.9, react_loop: 4476.9, synth: 11729.1, escalation: 0.7}
ecommerce           llm      llm=5 iter=2 tools=1  13732ms
  {preload: 0.1, intent: 1674.4, react_loop: 5754.5, synth: 6298.8, escalation: 0.8}
out_of_scope        keyword  llm=0 iter=0 tools=0      3ms
  {preload: 0.1, intent: 0.1}
```

The keyword-vs-LLM intent gap is visible directly: 0.9ms vs 1674ms.
The out-of-scope fast-track answers in 3ms with zero tokens.

---

## Error Handling & Resilience

All LLM calls go through `_call_llm_with_retry()` [graph.py:55](app/graph.py#L55):

```
RateLimitError (429)      → retry, backoff 1.5^n seconds
APIConnectionError        → retry
APIStatusError  5xx       → retry
APIStatusError  4xx       → NO retry (malformed request; retrying cannot help)
Other Exception           → retry

3 attempts, then {"ok": False, "error": "..."}
```

Stage-level fallbacks:

| Stage | All retries exhausted |
|---|---|
| THINK | Emit `error` event, break the loop, proceed to SYNTH with whatever tool results exist |
| SYNTH internal | Template fallback listing raw tool outputs via `_summarize_tool_results()` |
| SYNTH client | Fixed reply: "Thank you for your question. I'd be happy to connect you with a specialist." |

Tool-level:

| Failure | Handling |
|---|---|
| Unknown tool name | `"ERROR: Unknown tool '{name}'"`, `is_error=True` |
| Tool raises | `"ERROR: {type}: {msg}"`, `is_error=True`, loop continues |
| JSON arg parse failure | Falls back to `{}` |
| 2 consecutive tool errors | OBSERVE forces synthesize |
| Whole-pipeline exception | Caught at [graph.py:593](app/graph.py#L593), metrics saved with the error, `error` event emitted |
| `log_interaction` failure | Swallowed — logging is best-effort |

`required_tools` is **not** enforced. An earlier version injected forced tool calls
and refused to exit the loop until they ran; that produced redundant iterations and
latency without improving answers. Customer data now arrives via preload, and the
LLM decides the rest.

---

## Data Layer

### SQLite — `data/stripe_sales_copilot.db`

| Table | Rows | Origin | Used by |
|---|---|---|---|
| `customers` | 30 | pre-existing | `lookup_customer_tool`, escalation volume checks, `/api/customers` |
| `stripe_products` | 26 | pre-existing | joined into product usage lookups |
| `customer_product_usage` | 81 | pre-existing | `lookup_product_usage_tool` |
| `sales_policy_updates` | 20 | pre-existing | `lookup_policy_tool` |
| `sales_interactions` | 97 | pre-existing | written per turn by `log_interaction()` |
| `session_memory` | 119 | added | conversation persistence |
| `turn_metrics` | 20 | added | observability |

```sql
CREATE TABLE IF NOT EXISTS session_memory (
    session_id   TEXT PRIMARY KEY,
    customer_id  TEXT,          -- no FK: sessions may exist before a customer is chosen
    turns_json   TEXT DEFAULT '[]',
    summary      TEXT DEFAULT '',
    updated_at   TEXT
);
```

The FK to `customers` was removed after it rejected sessions with no customer
selected; `save_session()` normalizes `""` → `NULL` instead.

Connection [database.py:27](app/database.py#L27): one cached connection,
`check_same_thread=False`, `journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON`.

### Knowledge graph — `knowledge_base/knowledge_graph.yaml`

80 nodes, 150 edges, loaded into a `networkx.DiGraph` at first use.

| Entity type | Count |  | Predicate | Count |
|---|---|---|---|---|
| payment_method | 24 |  | `integrates_with` | 33 |
| product | 16 |  | `supports_method` | 30 |
| sales_scenario | 13 |  | `suitable_for` | 24 |
| compliance | 8 |  | `used_for` | 20 |
| geography | 7 |  | `belongs_to` | 16 |
| customer_type | 5 |  | `complies_with` | 9 |
| escalation_team | 5 |  | `cross_sell` | 8 |
| product_line | 2 |  | `available_in` | 6 |
| | |  | `requires_escalation` | 4 |

The 13 `sales_scenario` nodes carry 95 `question_patterns` total — these are the
keyword source for intent classification.

### Milvus — `milvus.db` (Milvus Lite)

Collection `stripe_sales_knowledge`, 278 chunks, 1536-dim, COSINE, AUTOINDEX.
Chunking: `RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=80)`
with separators `\n## ` → `\n### ` → `\n- ` → `\n` → `. ` → ` ` → char.

Ingestion enriches each chunk's metadata by KG traversal from its product node:
`related_products`, `supports_methods`, `complies_with`.

Retrieval composes two scalar filters [milvus_retriever.py:136](app/milvus_retriever.py#L136):

```python
'product in ["billing","tax","invoicing","checkout"] and access_level == "public"'
```

The first comes from KG expansion; the second excludes the 3 `internal_mock`
documents from public search.

---

## Streaming & Frontend

### SSE (`POST /sales-agent/stream`)

`stream_agent()` [graph.py:605](app/graph.py#L605) wraps the pipeline generator
in SSE frames. `StreamingResponse` sets `Cache-Control: no-cache` and
`X-Accel-Buffering: no` so nothing buffers the stream.

| Event | Payload | When |
|---|---|---|
| `act` | tool_name, arguments, output_preview, is_error, cache_hit | Preload (iteration 0) and each tool execution |
| `intent` | scenario, display_name, confidence, method, reason, context_used, all_matched | After classification |
| `skill` | name, max_iterations, required_tools, optional_tools | After skill selection |
| `think` | iteration, status / decision, tool_name, reasoning | Each THINK round |
| `observe` | iteration, decision, called, reason | Each OBSERVE |
| `synth` | status, internal_length, client_length | Response generation |
| `escalation` | should_escalate, escalation_team, reason, evidence | After gating |
| `done` | intent, products, internal_answer, client_ready_response, sources, escalation fields, confidence, iterations, metrics | Pipeline complete |
| `error` | stage, message | Any failure |

### Frontend (`app/static/index.html`)

Single-page vanilla HTML/JS, no framework, no build step.

- Fetch API + `ReadableStream` rather than native `EventSource` — the latter is GET-only
- `session_id` in `localStorage`, survives refresh
- Customer dropdown from `/api/customers`
- Pipeline stages stay visible after completion; client response in a green card;
  internal answer collapsed in `<details>`
- Escalation confirmation dialog: "Connect to [Team]" / "No, thanks"
- Copy-to-clipboard for client responses

### Concurrency

Each request builds a fresh generator; there is no shared mutable state between
streams. Session isolation is by `session_id`, cache isolation is per-session.

| Tier | Users | Milvus | DB | Session store |
|---|---|---|---|---|
| Dev (current) | 1-5 | Milvus Lite (file lock, serialized search) | SQLite WAL | SQLite |
| Test | 5-50 | Milvus Docker | SQLite WAL | SQLite |
| Prod | 50-500+ | Zilliz Cloud | PostgreSQL | Redis |

Milvus Lite's file lock is the binding constraint today; moving to Docker is a
URI change at [milvus_retriever.py:34](app/milvus_retriever.py#L34). The tool
cache would also need to move to Redis for multi-worker deploys.

Never a bottleneck: the KG (in-memory DiGraph, read-only after init, ~10µs/lookup),
the embedding API (OpenAI handles concurrency), and the KB markdown files
(read at ingestion, not at query time — except `lookup_pricing_tool`, which reads
two files per call).

---

## Testing

Two tiers, split by **how they run**, not just by what they touch:

```
tests/*.py                  pytest modules — 198 unit + 5 integration-marked
tests/integration/*.py      standalone scripts — top-level code, run directly
```

The scripts execute on import and hit the LLM and Milvus, so collecting them
would fire real API calls during a plain `pytest`. `tests/conftest.py` excludes
the directory (`collect_ignore_glob = ["integration/*"]`) and puts the project
root on `sys.path` so both tiers import `app` regardless of working directory.

```
pytest -m "not integration"            198 tests, ~5s, no LLM / no Milvus
pytest                                 203 tests (5 integration-marked)
python tests/integration/test_e2e.py   4 conversations, 12 turns, end-to-end
```

| File | Unit | Integration | Covers |
|---|---|---|---|
| `tests/test_escalation.py` | 46 | — | Gate A/B, trigger matching, volume thresholds, team routing |
| `tests/test_kg_retriever.py` | 39 | — | Keyword matching, graph traversal, filter building |
| `tests/test_intent.py` | 23 | 4 | Classification, out-of-scope, context inheritance |
| `tests/test_tool_cache.py` | 21 | — | Key stability, TTL expiry, session isolation, bounds |
| `tests/test_skills.py` | 19 | — | Registry integrity, tool-name validity, KG node coverage |
| `tests/test_context.py` | 18 | — | Token budget, truncation, layered assembly |
| `tests/test_tools.py` | 16 | 1 | Structured JSON output, registry consistency |
| `tests/test_metrics.py` | 16 | — | Collection, token accounting, stage latency |

`test_skills.py` found three real bugs on its first run — most importantly, five
skills listed `"lookup_customer"` / `"lookup_product_usage"` in `optional_tools`
instead of the real `_tool`-suffixed names. `get_tools_for_skill()` silently drops
unknown names, so those two tools were **invisible to the LLM** in five scenarios.
Dozens of integration runs never caught it, because the LLM produced plausible
answers from `search_product_info` alone.

---

## File Map

```
app/
├── main.py               FastAPI: lifespan(init_db, init_metrics), 6 endpoints
├── schemas.py            SalesAgentRequest / SalesAgentResponse
├── agent.py              run_sales_agent() → graph.run_agent()
│
├── graph.py              _run_pipeline() + stream_agent() + run_agent()
│                         + _call_llm_with_retry, _prefetch_customer,
│                           _build_multi_intent_hint, _build_context_hint
├── skills.py             SkillConfig + SKILL_REGISTRY (14 entries)
├── tools.py              6 @tool functions, JSON output, get_tools_for_skill()
├── tool_cache.py         Per-session TTL cache
├── metrics.py            TurnMetrics + turn_metrics table + 3 aggregates
├── intent.py             Keyword → context boost → fast-track → LLM fallback
├── context.py            Session memory + 3-layer window + LLM summarization
├── escalation.py         check_escalation() + escalate_with_context()
│
├── kg_builder.py         YAML → networkx.DiGraph + traversal helpers
├── kg_retriever.py       expand() + build_filter_expr()
├── milvus_retriever.py   KG filter + embed + search
├── milvus_loader.py      chunk → KG enrich → embed → insert
│
├── database.py           WAL connection, session_memory, customer/policy reads
├── sql_tools.py          Parameterized query functions
└── static/index.html     SSE chat UI

tests/
├── conftest.py           sys.path bootstrap + excludes integration/ from pytest
├── test_*.py             pytest suite (8 modules, 198 unit + 5 marked)
└── integration/          standalone runnable scripts (see its README)
```

---

## Cost per query

Measured, not estimated (from `turn_metrics`, gpt-4o-mini at $0.15/1M in,
$0.60/1M out):

```
Average over 20 turns: 3236 tokens in / 494 tokens out  ≈ $0.0008/turn
Heaviest observed:     9205 tokens in /  702 tokens out ≈ $0.0018/turn
out_of_scope:          0 tokens                          = $0
```

Input tokens dominate because THINK rebuilds the full message list — including
every prior tool result — on each iteration. That is the price of the
rebuild-from-scratch strategy that keeps `tool_call_id` pairing correct; the
alternative (incremental accumulation) is cheaper but was the source of repeated
OpenAI 400 errors.
