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
from an internal document. Someone with no Stripe account is a **prospect**: the agent runs
discovery, recommends a starting set of products and captures what it learned as a **lead**.
An existing customer who comes back is remembered: what they said last time is in the
prompt from the first turn, corrected when they say it changed, and completed by a reflection
pass when they end the conversation. A pasted document becomes an attachment the agent
reads in pieces, and a very long conversation stays coherent: spent tool results are
cleared and, rarely, working memory is compacted into one rolling summary. Every step
streamed, every turn metered — and measured: `pytest -m eval` runs nineteen
customer-viewpoint sessions against the real model and reports first-action accuracy, a
judge's score and a zero-leak check. The final documentation pass lands with
[issue #13](https://github.com/JLLeo/Stripe_Copilot/issues/1).

---

## How a turn works

```
customer message  ─►  /sales-agent/stream
                          │
                          ▼
             ┌─────────────────────────────┐
             │ Harness.run_turn            │
             │  1. SessionStart (first     │   customer block frozen from the
             │     contact only)           │   Customer Profile + Customer Memory
             │  2. relieve pressure        │   clear spent results, compact — only past the high-water mark
             │  3. assemble request        │   static prompt · tools · customer · memory; a long message → Attachment
             │  4. Provider.complete       │   DeepSeek, streamed
             │  5. tool calls?             │   PreToolUse → run → PostToolUse,
             │     └─ round again          │   Skill / search_knowledge / research / request_handoff / …
             │     └─ or pause             │   a handoff waits for the customer's answer
             │  6. Stop hooks on the reply │   anti_placeholder, internal_canary → rewrite
             │  7. append every message    │   working memory
             │  8. record TurnRecord       │   tokens, cache hit/miss, tools, skills, hooks
             └─────────────────────────────┘
   POST /sales-agent/end ──► SessionEnd: a reflection sub-agent keeps what the agent did not record
                          │
                          ▼
   SSE: context_relieved? · thinking? · (tool_call · [subagent_started · subagent_tool_call* · subagent_finished] · skill_loaded | tool_result | hook_blocked | handoff_pending | ask_customer)* · text_delta* · done | error
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
│   │   ├── guardrails.py     # turn_budget, result_cap, turn_result_budget, tool cache, anti_placeholder, internal_canary, leaks()
│   │   ├── context.py        # Context Budget: attachment stubs, clearing, compaction with a rolling summary (ADR 0006)
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
│   │   ├── clarify.py        # ask_customer(question, options[]) + clean_question — ends the turn with clickable options
│   │   ├── lead.py           # capture_lead(...) + prospect_only — one Lead per prospect session, refined as they talk
│   │   ├── memory.py         # remember(kind, fact, replaces?) + customer_only, and the SessionEnd reflection sub-agent
│   │   └── attachment.py     # read_attachment(id, offset, limit) — a long customer message, read in pieces
│   └── static/index.html     # Customer chat UI
├── data/
│   ├── seed.db               # Tracked, read-only: customers, products, usage, policies
│   └── runtime.db            # Gitignored, created on first start: sessions, messages, attachments, compactions, handoffs, leads, customer_memory, metrics
├── scripts/build_seed_db.py  # Rebuild data/seed.db from data.xlsx
├── skills/<name>/SKILL.md    # 11 skills: 7 product, 4 conversation (discovery, pricing, security, objections)
├── knowledge_base/           # Public + internal product docs, knowledge graph
├── milvus.db/                # Milvus Lite: 177 public chunks × 2 collections (dense, BM25)
├── tests/                    # 169 tests, no network, ~24s (builds a real Milvus Lite fixture); + 19 eval cases on demand
├── evals/
│   ├── cases/*.yaml          # 19 customer-viewpoint sessions: expected first action, expectations, rubric
│   ├── runner.py             # Recorder over the provider, first-action reading, deepseek-flash judge, zero-leak, report
│   └── reports/latest.md     # the last `pytest -m eval` run (and latest.json)
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
`HARNESS_RESULT_CAP_CHARS` (6000), `HARNESS_TOOL_CACHE_TTL_SECONDS` (900), `HARNESS_MEMORY_LIMIT` (12), `HARNESS_SKILLS_DIR`,
`MILVUS_URI`, `SEED_DB_PATH`, `RUNTIME_DB_PATH`; and the context thresholds `HARNESS_TURN_RESULT_BUDGET_CHARS` (24000),
`HARNESS_ATTACHMENT_THRESHOLD_CHARS` (8000), `HARNESS_CONTEXT_BUDGET_TOKENS` (96000), `HARNESS_HIGH_WATER` (0.75),
`HARNESS_LOW_WATER` (0.40), `HARNESS_SUMMARY_MAX_TOKENS` (800), `HARNESS_RECENT_WINDOW_TOKENS` (24000) — see
"Context management".

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Customer chat UI |
| `GET` | `/api/customers` | The sign-in selector: a **New prospect** entry first (`customer_id: null, prospect: true`), then every customer |
| `GET` | `/api/leads?limit=50` | Leads captured from prospects, most recently updated first — the follow-up queue |
| `POST` | `/sales-agent/chat` | One turn, JSON reply with `sources`. `404` unknown customer, `409` session already bound to another customer |
| `POST` | `/sales-agent/stream` | One turn as SSE: `context_relieved`? (spent results cleared / working memory compacted before this turn), `thinking`?, then per tool call `tool_call` + (`skill_loaded` \| `tool_result` \| `hook_blocked` \| `handoff_pending` \| `ask_customer`), with `subagent_started` / `subagent_tool_call` / `subagent_finished` inside a `research` call, `text_delta`*, then `done` or `error`. `done.pending_handoff` is set when the turn stopped for a confirmation, `done.ask_customer` when it ended with a question and options. Text is streamed only after the Stop hooks approve it |
| `POST` | `/sales-agent/confirm-handoff` | `{session_id, accept, handoff_id?}` — the customer's answer to a pending handoff; the agent's follow-up streams back as SSE. `404` when nothing is pending, `409` for a stale proposal |
| `POST` | `/sales-agent/end` | `{session_id}` — the customer ends the conversation. `SessionEnd` runs the reflection sub-agent for a customer (never for a prospect) and returns `{reflected, remembered, merged}`; the session takes no more turns (`409`). `404` unknown session, `409` already ended |
| `GET` | `/api/metrics?days=7` | Turns, errors, latency, tokens per turn, prompt-cache hit rate, tool rounds, tool-cache hits, sub-agent delegations and tokens, handoffs confirmed / declined, leads captured, reflection passes, calls per tool |

Request body for both chat endpoints:

```json
{ "session_id": "uuid", "customer_id": "CUST-001", "message": "What does Checkout do?" }
```

`customer_id` may be omitted: the session is then a **prospect session** — the customer block says
nothing is known yet, `get_my_profile` reports no profile, and the model runs discovery and
captures a lead. A session is bound to its customer on first contact and refuses to switch.

## Testing

```bash
pytest            # 169 tests in ~24s; no model calls; temp runtime DB and a temp Milvus Lite index
pytest -m eval    # the evaluation suite: 19 sessions against DeepSeek, ~5 min, needs .env
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
| `tests/test_context.py` | Context pressure: every threshold in `HarnessConfig` (validated: low < high, summary + window under the low mark); a long message becomes an attachment with a stub and is read by offset in plain-text pieces that always fit the result cap, scoped to its session; evidence in an attached message still counts; a turn's tool results are capped in total (skill bodies exempt); spent results become stubs when the last response was over the high-water mark, content kept in the row; compaction runs at the high mark on `deepseek-flash` in its own context, keeps the static prefix and the current message, a token-budgeted window starting at a customer message, records active skills, folds the previous summary, caps the summary, does not run again until pressure returns, and a failed summary throws nothing away; reflection reads a summary as context |
| `tests/test_memory.py` | Customer Memory: `remember` → row with source turn and confidence; the next session's first request carries the fact with its `[m<id>]`; a correction supersedes, a retraction drops it from the block; the same fact is never written twice (by `remember` or by reflection); kinds and ids validated; denied for a prospect; the injected set is bounded to 12, most recent first; `/sales-agent/end` runs reflection on `deepseek-flash` in its own context, writes merged rows, is metered as a `session_end` pass, refuses further turns and a second end, skips prospects, and ends the session even when the sub-agent fails. The prefix test in `test_harness_chat.py` now includes a turn that remembers a fact |
| `tests/test_prospect.py` | Prospect sessions: the block knows nothing yet and points at discovery, `get_my_profile` reports no profile, the customers list leads with **New prospect**; the `discovery` skill teaches behaviour and quotes no internal text (every skill body passes `leaks()`); `capture_lead` writes one row per session, later calls refine it and return the whole lead, an empty call gets feedback, a signed-in customer is denied (`prospect_only`), a prospect who states $50M is routed to Enterprise Sales; `/api/leads` newest first and `leads_captured` in metrics |
| `tests/test_clarify_and_stop.py` | `ask_customer` ends the turn with options and the choice is the next message; 2–5 distinct options; a question that would leak or leave blanks is denied with feedback; Stop hook rewrites placeholders and internal leaks before anything streams, gives up after two rewrites with a safe reply, and checks the text beside a handoff proposal; citations, links and sign-offs handled; `leaks()` finds curated and document-derived markers and nothing a public document says |
| `tests/test_providers.py` | The Provider seam: scripted playback, deterministic embeddings, DeepSeek stream accumulation and request shape, the request timeout |
| `tests/test_eval_runner.py` | The evaluation runner on the scripted provider: the case set covers every skill, clarifying questions, both handoff triggers and the enterprise override, prospect discovery and refusal; actions are read off recorded completions and only the main model's count; a case checks first action, within-turn and within-session expectations, the handoff team, a refusal where one is expected, and leaks, and judges every reply; the judge's JSON is found among prose; the summary and the report, incomplete runs and table cells included |
| `tests/test_eval.py` | `pytest -m eval` — see Evaluation |
| `tests/test_database.py` | Seed / runtime split, read-only seed, append-only messages |
| `tests/test_api_customers.py` | Customer list served through the shared connection |

Running the suite leaves `git status` clean: the suite uses its own runtime database.

## Evaluation

```bash
pytest -m eval                       # all 19 cases; writes evals/reports/latest.md and latest.json
pytest -m eval -k handoff            # a subset
EVAL_MIN_JUDGE_SCORE=3 pytest -m eval   # also fail a case the judge scores under 3
```

The unit suite proves the plumbing; the evaluation suite measures behaviour, on the real
model, from the customer's side. Each case in `evals/cases/` is a short session with a
customer (a seed customer by id, or a prospect), the **first action** the agent is expected
to take — a skill loaded, a tool called, a clarifying question, a handoff proposed, or a
plain answer such as a refusal — optional actions that must happen somewhere in the first
turn or the session, the team a proposed handoff must name, whether a refusal is expected,
and a rubric for the judge. The nineteen cases cover every skill, a clarifying
question, a handoff the customer asks for and one a policy requires, the enterprise
override, prospect discovery with lead capture, customer memory, and two refusals
(out of scope; internal material).

The runner wraps the provider in a `Recorder`, so the agent's actions are read off the
actual model traffic (parallel calls in the first response all count as first; a
sub-agent's calls never do), drives the case through `/sales-agent/chat` exactly as the
browser would, runs the zero-leak check on every reply, and asks a judge on
`deepseek-flash` to score each reply 1–5 against the rubric, seeing the sources the reply
cited and the handoff card the customer was shown, and — where a refusal is expected — to
say whether the agent declined. A case **passes** when the first action matched, the other
expectations held, the handoff named the right team, the agent declined where it should,
and nothing leaked; the judge's score is reported (flagged in the table under 3) and
asserted only when `EVAL_MIN_JUDGE_SCORE` is set — a model grading a model is a signal, not
a gate.

The report (`evals/reports/latest.md`, with a JSON twin) opens with the headline numbers
— first-action accuracy, leak-free cases, mean judge score, cases passed — then one row
per case (expected vs actual first actions, within-turn and handoff checks, judge score,
leaks, latency) and every reply with the judge's reason, so a failed case can be read,
not just counted; a run of a subset says how many of the defined cases it covered. The same
numbers are printed at the end of the pytest run. The report in the repository is the
latest full run; re-running overwrites it, and a changed report belongs in the same commit
as the behaviour change that caused it.

The run in [`evals/reports/latest.md`](evals/reports/latest.md): first-action accuracy
19/19, leak-free 19/19, both refusals confirmed by the judge, mean judge score 4.5 / 5, in
under seven minutes. The one flagged case is instructive: the judge marked Billing's public
0.7% rate as "invented" because the reply did not cite it inline — a judge's reading, not a
leak, and exactly the kind of thing the report exists to show.

## Skills and tools

Skills are `skills/<name>/SKILL.md` files — YAML frontmatter (`name`, `description`) and a
markdown body. The static prompt carries only the descriptions; the body enters the
conversation when the model calls `Skill(name)`, so the model decides when a skill
applies. Several can be loaded in one round. Skills recommend tools; they never restrict
them. Adding a behaviour is adding a file.

| Tool | What the model gets |
|---|---|
| `Skill(name)` | the skill body; one of the seven product skills or `discovery`, `pricing_conversation`, `security_compliance`, `objection_handling` |
| `get_my_profile()` | the bound customer's profile and products in use — no arguments, so no way to ask about anyone else. In a prospect session: no profile, and a note to ask |
| `list_products(group?)` | the catalogue from the seed database |
| `get_pricing(product)` | public list prices for the product, read from the `Price` sections of knowledge-base documents marked `Access Level: public` (the seed database holds no prices); when nothing matches it says so instead of guessing. The documents a price came from are carried as sources, so a quoted price is a cited price |
| `search_knowledge(question, products[], topics[])` | passages from Stripe's public documentation with their sources. `products` and `topics` are enums from the knowledge graph — the model does the entity linking, the graph widens the search one hop, and dense + BM25 legs run with the same filter and are fused |
| `research(question)` | a **sub-agent**: a bounded loop on `deepseek-flash` with `search_knowledge` as its only tool, up to 3 rounds, in its own context. Only its cited brief comes back, and the customer watches each search as it happens. For questions that span products, need a comparison, or came back thin from one search |
| `request_handoff(team, reason, evidence)` | propose handing the conversation to one of seven human **Teams**. Guardrails check the team, that the evidence is the customer's own words or a profile fact, and that a customer above $10M a year goes to Enterprise Sales; then the turn **pauses** and the customer confirms or declines in the UI. Only a confirmation records a handoff |
| `ask_customer(question, options[])` | a clarifying question with 2–5 clickable options when a request could mean different things. The turn ends with the question; the option the customer clicks is simply their next message |
| `capture_lead(company?, business_model?, annual_volume_usd?, timeline?, needs?, qualification_notes?, recommended_products?)` | what a prospect has said, written as the session's **Lead** — one row per session; each call adds what it names, keeps the rest, and returns the whole lead with what is still unknown. Denied with feedback for a signed-in customer (`prospect_only`); the volume a prospect gives feeds the $10M rule |
| `read_attachment(id, offset?, limit?)` | a piece of a long customer message that was kept as an **attachment** (over 8,000 characters by default) — plain text under a one-line header with the next offset; a piece always fits the result cap, and only this session's attachments can be named |
| `remember(kind, fact, replaces?)` | keep a durable fact about the customer for future conversations — `need`, `objection`, `preference`, `commitment` or `stage`. `replaces=<id>` with a new fact corrects an earlier one; with an empty fact it drops it. Facts are never edited in place. Denied with feedback in a prospect session (`customer_only`) |

Every call passes through the hooks: `turn_budget` (8 tool rounds per turn; the ninth
is denied with feedback, the next request forces a text answer, and a model that still
asks for tools is stopped), `tool_cache_lookup` (identical calls within a session are
served from a TTL cache), `handoff_validity` and `enterprise_volume` (deny a handoff
with feedback — the volume comes from the profile or, for a prospect, from the lead),
`handoff_confirmation` (pause for the customer), `prospect_only` (leads are for
prospects), `customer_only` (memory is for customers), `result_cap` (results
over ~1.5K tokens are truncated at a boundary with a note), `tool_cache_store`,
`turn_result_budget` (once a turn's tool results reach ~6K tokens, further results are cut
to what is left, at least a few hundred characters each; skill bodies are exempt),
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
the prompt names the team behind it. Four conversation skills — `discovery`,
`pricing_conversation`, `security_compliance`, `objection_handling` — turn the internal
documents into behaviour rules and approved wording, quoting no internal text
([ADR 0003](docs/adr/0003-internal-knowledge-never-enters-customer-context.md)).

## Context management

A long conversation must stay coherent without breaking the cached prefix on every
turn, so pressure is relieved in tiers and compaction is the last resort
([ADR 0006](docs/adr/0006-context-pressure-relieved-in-tiers.md)):

1. **Limits at the source.** One tool result is capped (`result_cap`), a turn's results
   are capped in total (`turn_result_budget`), heavy reading goes through the `research`
   sub-agent so only a brief enters the conversation, and a customer message over the
   attachment threshold is kept as an **attachment**: working memory gets a short stub
   with the id, size and opening, and the model reads the pieces it needs with
   `read_attachment`. Guardrails still see the whole message.
2. **Clearing.** When the previous response reported prompt tokens at or above the
   high-water mark, tool results from earlier turns are rendered as one-line stubs
   (`[cleared: earlier search_knowledge result (2,340 characters); call the tool again
   if you need it]`). The rows keep their content; only the rendering changes. Skill
   bodies are never cleared. Deterministic, free, and often enough.
3. **Compaction.** If clearing does not bring the estimate under the mark, everything
   before a token-budgeted recent window is folded into one rolling summary written
   by `deepseek-flash` in its own context — what the customer's business is and wants,
   every concrete fact they stated, what the agent recommended or quoted with sources,
   open questions, where things stand — followed by lines the harness writes itself:
   the active skills, the facts established this session (a customer's still-active
   memories, a prospect's lead), and the attachments the customer sent. The whole
   summary never exceeds its cap; the window is sized to land at the low-water mark and
   starts at a customer message (and shrinks to the last customer turn when it would
   otherwise hold everything); the current message is always verbatim; the static
   prefix is untouched. The next compaction folds the previous summary in. A failed
   summary throws nothing away.

Triggers read the provider's reported `prompt_tokens` (there is no local tokenizer);
the window and the summary cap use a characters/4 estimate. Every threshold lives in
`HarnessConfig`: `tool_round_budget` 8, `result_cap_chars` 6000, `turn_result_budget_chars`
24000, `attachment_threshold_chars` 8000, `context_budget_tokens` 96000, `high_water` 0.75,
`low_water` 0.40, `summary_max_tokens` 800, `recent_window_tokens` 24000 — validated so that
the summary plus the window fit under the low-water mark, which is where a compacted session
lands. The UI shows a `context` row when a turn cleared or compacted; metrics record
`cleared`, `compacted` and `compaction_failed`, and the summary's tokens are booked with the
sub-agents'.

## Customer memory

What a customer tells the agent outlives the session. During the conversation the model
records durable facts with `remember` — "we go live in Q1", "the CFO refuses per-seat
pricing", "email, don't call" — and corrects or drops them when told they changed. At the
next session's SessionStart the most recent active facts (12 at most) are rendered into
the frozen customer block, each with its `[m<id>]`, so the agent picks up where it left
off and can correct a fact by id. A fact remembered mid-session reaches the model as the
tool's result — appended to working memory, never re-rendered into the block — so the
cached prefix stays byte-identical ([ADR 0005](docs/adr/0005-append-only-prompt-prefix.md)).

**End conversation** in the UI (`POST /sales-agent/end`) runs `SessionEnd`: a reflection
sub-agent on `deepseek-flash`, in its own context, reads the finished conversation and
the facts already on file, and saves what the agent did not record — refining or merging
existing facts by id rather than duplicating them; a fact identical to one already on file
is never written twice, whoever tries. The pass is metered as a
`session_end` row (sub-agent tokens only), the session takes no more turns, and a failed
reflection still ends the session. Prospects have no memory: what they say is the lead.

## Prospects and leads

Pick **New prospect** in the UI (or omit `customer_id`) and the agent knows nothing. The
`discovery` skill — the sales playbook translated into behaviour, with none of its
qualification framework, segments or process — tells it what to learn (business model,
volume, timeline, current setup and pain, where they sell, who decides, alternatives),
how to ask (pain first, one or two questions a turn, `ask_customer` when the answers are
few), which starting set to recommend for which business model, and when to bring a
team in. As soon as it knows something concrete it calls `capture_lead`; every later
call refines the same row. `GET /api/leads` is the queue for whoever follows up.

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

A prospect — "a small online furniture store thinking about switching" — got the
`discovery` skill and two questions. Told "900 orders a month, average $350, US only,
Canada next year, on Shopify Payments, fraud chargebacks are killing us, I decide", the
model loaded `fraud_protection` and `payments`, captured the lead with the volume worked
out ($3.78M a year), priced Radar, and recommended Radar + Payments; "live before the
holiday season" refined the same lead with the timeline and the recommended set
(Payments, Checkout, Radar). Turn 2: 22,016 of 24,004 prompt tokens from cache.

With the budget shrunk to 12K tokens for the run (attachment threshold 3,000 characters), a
customer pasted a 25-point requirements list of 4,827 characters: the model read it in two
`read_attachment` pieces, loaded four skills, searched twice and answered. On the next turn
the reported prompt tokens were over the high-water mark: four spent results were cleared,
and that was enough. A turn later clearing one more was not, and working memory was compacted
into one summary on `deepseek-flash` — 15,395 reported tokens before, the next request 8,140
tokens with 8,064 of them from cache. Two turns after that, "remind me: what was our dispute
rate and what did you recommend for it?" was answered from the summary: 1.8% of orders, Radar
for Fraud Teams. Two further compactions folded the earlier summaries in; seven results were
cleared over the conversation.

A $3.1M SaaS customer opened with "we've decided to go live with Stripe Billing in Q1
next year, our CFO refuses anything with per-seat pricing, and please email rather than
call": the model called `remember` three times in one round (commitment, objection,
preference). After a second turn that mentioned usage-based pricing and Chargebee, **End
conversation** ran reflection on `deepseek-flash` (2 calls, 2,126 prompt tokens), which
added exactly those two facts and duplicated none of the three. The next session's block
listed all five and the model opened with "Welcome back! Here's where we left off".

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
