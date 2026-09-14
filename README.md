# Stripe AI Sales Agent

A customer-facing AI sales agent for Stripe, built on a hand-written harness in the
style of Claude Code: the model decides what to do on every turn; deterministic code
only builds the request, moves bytes, and guards the edges.

This branch is a ground-up rebuild in progress. Today a customer signs in, asks a
question, and watches the agent load the relevant skill, search Stripe's public
documentation — or hand a hard question to a research sub-agent — look up the profile,
catalogue or pricing, and answer with sources; when a request is ambiguous it asks a
clarifying question with options; when the matter needs a person, it proposes a handoff and
waits for the customer's yes; and no reply reaches the customer with a placeholder or a line
from an internal document. Every step streamed, every turn metered. Prospects, memory, and
long-conversation handling land ticket by ticket
([issues #9–#13](https://github.com/JLLeo/Stripe_Copilot/issues/1)).

---

## How a turn works

```
customer message  ─►  /sales-agent/stream
                          │
                          ▼
             ┌─────────────────────────────┐
             │ Harness.run_turn            │
             │  1. SessionStart (first     │   customer block frozen from
             │     contact only)           │   the Customer Profile
             │  2. assemble request        │   static prompt · tools · customer · memory
             │  3. Provider.complete       │   DeepSeek, streamed
             │  4. tool calls?             │   PreToolUse → run → PostToolUse,
             │     └─ round again          │   Skill / search_knowledge / research / request_handoff / …
             │     └─ or pause             │   a handoff waits for the customer's answer
             │  5. Stop hooks on the reply │   anti_placeholder, internal_canary → rewrite
             │  6. append every message    │   working memory
             │  7. record TurnRecord       │   tokens, cache hit/miss, tools, skills, hooks
             └─────────────────────────────┘
                          │
                          ▼
   SSE: thinking? · (tool_call · [subagent_started · subagent_tool_call* · subagent_finished] · skill_loaded | tool_result | hook_blocked | handoff_pending | ask_customer)* · text_delta* · done | error
```

Every request is built in the same order — static system prompt, tool definitions
(none yet), customer block, working memory — and nothing before the newest message
is ever rewritten. DeepSeek's context cache is a prefix match, so on a real two-turn
session 1,024 of the second turn's 1,169 prompt tokens were served from cache.

The design decisions behind this are recorded in [`docs/adr/`](docs/adr/) and the
vocabulary in [`CONTEXT.md`](CONTEXT.md).

## Project structure

```
stripe-sales-copilot/
├── app/
│   ├── main.py               # FastAPI transport: chat, SSE stream, customers, metrics
│   ├── schemas.py            # ChatRequest / ChatResponse
│   ├── database.py           # One connection over seed.db (read-only) + runtime.db
│   ├── metrics.py            # TurnRecord + /api/metrics summary (cache hit rate)
│   ├── harness/
│   │   ├── provider.py       # The Provider seam: CompletionRequest → stream of events
│   │   ├── deepseek.py       # Production adapter: DeepSeek chat + OpenAI embeddings
│   │   ├── scripted.py       # Test adapter: plays a script, records every request
│   │   ├── prompt.py         # Static system prompt (incl. skill index), customer block, fixed order
│   │   ├── tools.py          # Tool = function + JSON schema; registry; argument checks
│   │   ├── skills.py         # SKILL.md loader + the Skill tool
│   │   ├── hooks.py          # Hook events; SessionStart / PreToolUse / PostToolUse dispatch
│   │   ├── guardrails.py     # turn_budget, result_cap, tool cache, anti_placeholder, internal_canary, leaks()
│   │   ├── subagent.py       # Bounded model loop with its own context → a Brief
│   │   └── core.py           # Harness.run_turn — the loop with tool rounds
│   ├── retrieval/
│   │   ├── graph.py          # Knowledge graph: entities, one-hop expansion
│   │   ├── linking.py        # Entity Linking vocabulary, expansion, filter; keyword fallback
│   │   ├── chunking.py       # Heading-aware markdown chunker (no framework)
│   │   ├── documents.py      # Public documents only, with graph metadata
│   │   ├── index.py          # Dense + BM25 collections, RRF fusion, search
│   │   └── ingest.py         # python -m app.retrieval.ingest (always a full rebuild)
│   ├── tools/
│   │   ├── profile.py        # get_my_profile() — no arguments, bound customer only
│   │   ├── catalog.py        # list_products(group?), get_pricing(product)
│   │   ├── knowledge.py      # search_knowledge(question, products[], topics[]) + source_extraction
│   │   ├── research.py       # research(question): the sub-agent over search_knowledge on deepseek-flash
│   │   ├── handoff.py        # request_handoff + its three guardrails, the seven Teams, confirm/decline
│   │   └── clarify.py        # ask_customer(question, options[]) + clean_question — ends the turn with clickable options
│   └── static/index.html     # Customer chat UI
├── data/
│   ├── seed.db               # Tracked, read-only: customers, products, usage, policies
│   └── runtime.db            # Gitignored, created on first start: sessions, messages, handoffs, metrics
├── scripts/build_seed_db.py  # Rebuild data/seed.db from data.xlsx
├── skills/<name>/SKILL.md    # 10 skills: 7 product, 3 policy (pricing, security, objections)
├── knowledge_base/           # Public + internal product docs, knowledge graph
├── milvus.db/                # Milvus Lite: 177 public chunks × 2 collections (dense, BM25)
├── tests/                    # 119 tests, no network, ~19s (builds a real Milvus Lite fixture)
├── docs/adr/                 # Architecture decision records
├── CONTEXT.md                # Domain glossary
└── ARCHITECTURE.md
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# .env
DEEPSEEK_API_KEY=sk-...      # deepseek-v4-pro for the conversation, deepseek-flash for sub-agents
OPENAI_API_KEY=sk-...        # embeddings only (text-embedding-3-small)

# Rebuild the seed database — only after editing data.xlsx; data/seed.db is tracked
python scripts/build_seed_db.py

# Rebuild the knowledge index — only after editing knowledge_base/; milvus.db/ is tracked
python -m app.retrieval.ingest

# Run
python -m uvicorn app.main:app --reload
# UI     http://127.0.0.1:8000/
# Docs   http://127.0.0.1:8000/docs
```

Optional environment: `HARNESS_MAIN_MODEL`, `HARNESS_SUB_MODEL` (deepseek-flash), `HARNESS_MAX_TOKENS`,
`HARNESS_THINKING=enabled|disabled`, `HARNESS_TOOL_ROUND_BUDGET` (8), `HARNESS_SUBAGENT_MAX_ROUNDS` (3),
`HARNESS_RESULT_CAP_CHARS` (6000), `HARNESS_TOOL_CACHE_TTL_SECONDS` (900), `HARNESS_SKILLS_DIR`,
`MILVUS_URI`, `SEED_DB_PATH`, `RUNTIME_DB_PATH`.

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Customer chat UI |
| `GET` | `/api/customers` | Customers for the sign-in selector |
| `POST` | `/sales-agent/chat` | One turn, JSON reply with `sources`. `404` unknown customer, `409` session already bound to another customer |
| `POST` | `/sales-agent/stream` | One turn as SSE: `thinking`?, then per tool call `tool_call` + (`skill_loaded` \| `tool_result` \| `hook_blocked` \| `handoff_pending` \| `ask_customer`), with `subagent_started` / `subagent_tool_call` / `subagent_finished` inside a `research` call, `text_delta`*, then `done` or `error`. `done.pending_handoff` is set when the turn stopped for a confirmation, `done.ask_customer` when it ended with a question and options. Text is streamed only after the Stop hooks approve it |
| `POST` | `/sales-agent/confirm-handoff` | `{session_id, accept, handoff_id?}` — the customer's answer to a pending handoff; the agent's follow-up streams back as SSE. `404` when nothing is pending, `409` for a stale proposal |
| `GET` | `/api/metrics?days=7` | Turns, errors, latency, tokens per turn, prompt-cache hit rate, tool rounds, tool-cache hits, sub-agent delegations and tokens, handoffs confirmed / declined, calls per tool |

Request body for both chat endpoints:

```json
{ "session_id": "uuid", "customer_id": "CUST-001", "message": "What does Checkout do?" }
```

`customer_id` may be omitted: the session is then a prospect with no profile. A session is bound to its
customer on first contact and refuses to switch.

## Testing

```bash
pytest            # 119 tests in ~19s; no model calls; temp runtime DB and a temp Milvus Lite index
```

All behavioural tests drive the HTTP API with a `ScriptedProvider` standing in for
DeepSeek. The fake records every request the harness built, which is how tests assert
things the response never shows — that the prefix is byte-identical between turns,
what the customer block contained, that no timestamp leaked into the cached prefix.

| Test file | Covers |
|---|---|
| `tests/test_harness_chat.py` | The turn end to end: fixed order, prefix stability, SessionStart block, prospect sessions, unknown/mismatched customer, SSE incl. `thinking`, friendly failure, disconnect metering, metrics |
| `tests/test_tools_and_skills.py` | Skill index vs body, Skill → tool → answer, parallel skill loads, profile scoping, catalogue and pricing tools, argument feedback, `turn_budget`, `result_cap`, tool cache, prefix stability with tools, tool metrics, SSE tool events |
| `tests/test_knowledge_search.py` | A fixture knowledge base indexed through the fake embedder: public-only in both collections, chunking, vocabulary from the graph, one-hop expansion, keyword fallback, filter expression, fused ranking, the `search_knowledge` tool, `sources` on `done` |
| `tests/test_research.py` | The research sub-agent: its own model and single tool, none of the main conversation in its requests, only the brief in working memory, the round cap and forced brief, cited-only sources, live progress events, separate metering (and none for a cached brief), tool descriptions that steer |
| `tests/test_handoff.py` | Handoff: the seven Teams and the policy register mapping, unknown team / untraceable evidence denied with feedback, the $10M rule, pause → confirm → `handoffs` row → follow-up, decline without a record, a new message resolving a dangling proposal, other calls in the paused round not run, the policy skills free of internal text |
| `tests/test_clarify_and_stop.py` | `ask_customer` ends the turn with options and the choice is the next message; 2–5 distinct options; a question that would leak or leave blanks is denied with feedback; Stop hook rewrites placeholders and internal leaks before anything streams, gives up after two rewrites with a safe reply, and checks the text beside a handoff proposal; citations, links and sign-offs handled; `leaks()` finds curated and document-derived markers and nothing a public document says |
| `tests/test_providers.py` | The Provider seam: scripted playback, deterministic embeddings, DeepSeek stream accumulation and request shape |
| `tests/test_database.py` | Seed / runtime split, read-only seed, append-only messages |
| `tests/test_api_customers.py` | Customer list served through the shared connection |

Running the suite leaves `git status` clean: the suite uses its own runtime database.

## Skills and tools

Skills are `skills/<name>/SKILL.md` files — YAML frontmatter (`name`, `description`) and a
markdown body. The static prompt carries only the descriptions; the body enters the
conversation when the model calls `Skill(name)`, so the model decides when a skill
applies. Several can be loaded in one round. Skills recommend tools; they never restrict
them. Adding a behaviour is adding a file.

| Tool | What the model gets |
|---|---|
| `Skill(name)` | the skill body; one of `payments`, `billing`, `connect`, `tax`, `fraud_protection`, `terminal`, `data` |
| `get_my_profile()` | the bound customer's profile and products in use — no arguments, so no way to ask about anyone else |
| `list_products(group?)` | the catalogue from the seed database |
| `get_pricing(product)` | public list prices for the product, read from the `Price` sections of knowledge-base documents marked `Access Level: public` (the seed database holds no prices); when nothing matches it says so instead of guessing |
| `search_knowledge(question, products[], topics[])` | passages from Stripe's public documentation with their sources. `products` and `topics` are enums from the knowledge graph — the model does the entity linking, the graph widens the search one hop, and dense + BM25 legs run with the same filter and are fused |
| `research(question)` | a **sub-agent**: a bounded loop on `deepseek-flash` with `search_knowledge` as its only tool, up to 3 rounds, in its own context. Only its cited brief comes back, and the customer watches each search as it happens. For questions that span products, need a comparison, or came back thin from one search |
| `request_handoff(team, reason, evidence)` | propose handing the conversation to one of seven human **Teams**. Guardrails check the team, that the evidence is the customer's own words or a profile fact, and that a customer above $10M a year goes to Enterprise Sales; then the turn **pauses** and the customer confirms or declines in the UI. Only a confirmation records a handoff |
| `ask_customer(question, options[])` | a clarifying question with 2–5 clickable options when a request could mean different things. The turn ends with the question; the option the customer clicks is simply their next message |

Every call passes through the hooks: `turn_budget` (8 tool rounds per turn; the ninth
is denied with feedback, the next request forces a text answer, and a model that still
asks for tools is stopped), `tool_cache_lookup` (identical calls within a session are
served from a TTL cache), `handoff_validity` and `enterprise_volume` (deny a handoff
with feedback), `handoff_confirmation` (pause for the customer), `result_cap` (results
over ~1.5K tokens are truncated at a boundary with a note), `tool_cache_store`,
`source_extraction` (sources a search cited are collected on the turn and returned on
`done`). Every final reply then passes the **Stop hooks** before a word of it is streamed:
`anti_placeholder` (unfilled `[Customer Name]`, `{{ }}`, `<your …>`, TBD) and
`internal_canary` (markers only Internal Knowledge contains — curated phrases plus the
headings and percentage ranges of the non-public documents, minus anything a public document
also says). A rejected draft goes back to the model with the feedback for a rewrite, up to
twice; after that a fixed safe reply is sent. The draft never enters working memory and the
customer never sees it. The same checks guard the two other things the customer reads: a
clarifying question and its options (`clean_question`, denied with feedback) and the text the
model writes beside a handoff proposal (the harness's own proposal stands in). An existing
`data/runtime.db` is upgraded in place on startup when the metrics table gains columns.

## Handoff

The customer-facing version of Claude Code's permission prompt. The model proposes with
`request_handoff(team, reason, evidence)`; guardrails validate; the turn stops with a
`handoff_pending` event and a reply that asks the customer; the UI shows a card with
*Yes, connect me* / *No, keep going*; `POST /sales-agent/confirm-handoff` records the
handoff (or its decline) as the paused tool call's result and the model continues from
there, telling the customer what happens next. Only a confirmation brings a team in; a
decline is kept as bookkeeping and contacts nobody. A customer who sends a new message
instead is treated as declining, so the transcript never carries a dangling tool call.
The policy register's team names are mapped onto the seven Teams and each policy line in
the prompt names the team behind it. Three policy skills — `pricing_conversation`,
`security_compliance`, `objection_handling` — turn the internal documents into behaviour
rules and approved wording, quoting no internal text ([ADR 0003](docs/adr/0003-internal-knowledge-never-enters-customer-context.md)).

## Knowledge search

Only documents whose header says `Access Level: public` are ever read — the three
internal documents are not indexed, not embedded, not opened past their header
([ADR 0003](docs/adr/0003-internal-knowledge-never-enters-customer-context.md)). Each
document is chunked by heading (no framework), tagged with its knowledge-graph product
and neighbours, and written to two Milvus Lite collections with identical rows: a dense
one (OpenAI `text-embedding-3-small`, through the Provider seam) and a BM25 one Milvus
computes from the text. A search runs both legs with the same scalar filter and fuses by
reciprocal rank ([ADR 0004](docs/adr/0004-hybrid-retrieval-via-sibling-collection.md)).
Rebuild with `python -m app.retrieval.ingest` — always a full rebuild, so the index never keeps
chunks of documents that changed or disappeared. When the model names no entities, a short list of
unambiguous product phrases links the question instead; everyday words that merely resemble a
product name ("link", "connect", "platform") are deliberately not on it, because the fallback
narrows the search and a false match would hide the right documents.

## Measured on the live model

`deepseek-v4-pro`, thinking enabled, one customer session:

| | Turn 1 | Turn 2 |
|---|---|---|
| What the model did | `Skill(fraud_protection)` + `get_pricing(Radar)` in one round, then answered | `Skill(billing)` + `get_pricing(Billing)`, answered using the profile's products in use |
| Prompt tokens (both rounds) | 4,982 | 8,322 |
| Cache hit / miss | 2,176 / 2,806 | **7,424 / 898** |
| Reasoning tokens | 584 | 1,049 |
| Latency | 14.5 s | 18.3 s |

Before tools (turn 2 of a plain two-turn chat): 1,024 of 1,169 prompt tokens from cache, ~3 s.

A prospect asked "How much would Stripe cost us?": the model loaded
`pricing_conversation`, fetched the public card rates, then asked — online, in person,
subscriptions, a platform, or not sure — with five clickable options; "Both" came back as
the next message and it answered with online and Terminal pricing side by side.

A $43M customer asked for "a better rate than 2.9%": the model loaded
`pricing_conversation`, checked the profile, proposed **Enterprise Sales** (not Deal Desk —
the $10M rule is also in the prompt) with the customer's own sentence as evidence; the
turn paused; on confirmation the handoff was recorded and the follow-up explained next
steps — 13 s to the pause, 2 s for the follow-up.

On "which local payment methods can Checkout show customers in Germany and the
Netherlands, and does that work with Billing?", before the research sub-agent existed the
model ran four rounds of `search_knowledge` in the main conversation — 36K prompt tokens,
43 s. With it, the model searched once, found the passages thin, and delegated: the
sub-agent ran six searches in its own context and returned a brief; the main model
checked one more thing and answered — 30.7K main-conversation prompt tokens (79% from
cache), and everything the sub-agent read stayed out of the main context.

## Documents

- [`CONTEXT.md`](CONTEXT.md) — the glossary: Harness, Turn, Guardrail, Hook, Skill, Handoff, Customer Memory, Compaction, …
- [`docs/adr/`](docs/adr/) — why the model decides and rules only guard (0001), why the harness is hand-built on DeepSeek (0002), why internal knowledge never enters a customer conversation (0003), hybrid retrieval via a sibling collection (0004), the append-only prompt prefix (0005), tiered context-pressure relief (0006)
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — how the current code implements them
