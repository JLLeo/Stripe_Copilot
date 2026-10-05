# A Decider primes the Skills a turn calls for

Customers waited too long. On the nineteen customer-viewpoint cases, a whole case took
13.7 s at p50 and 48.8 s at p90, agent time only. The arithmetic is the whole problem:
**turn latency ≈ sequential model calls × a few seconds each**, because every Skill load
and every tool decision is its own round trip to `deepseek-v4-pro` with thinking on. The
spec estimated about 4 s a call; #18 later measured a round that only loaded Skills at
about 3 s (54 s over 18 such rounds on the held-out split). Some of those rounds buy the
customer nothing. In 10 of the 19 cases, the first response of the first turn only loaded a
Skill, sometimes with a profile read: seconds spent deciding to read the agent's own
manual. In 6 the Skill load ran beside a real tool call, so that round was doing work. In 3
there was no Skill at all. So the ceiling was estimated in advance: a round could go in 10
of the 19 first turns, which would take p90 from 48.8 s to about 45 s and leave p50 where it
was. The Consequences below say what was measured instead.

We added **Priming** (spec #14, tickets #15–#20). Before the first model call of a turn, the
**Decider** answers one yes/no question per Skill not yet in Working Memory: "does the
customer's latest message call for the payments skill?" Every question goes in one request.
The Decider is Jev, TypeSafe AI's "System One": a typed model that returns a probability per
question, not text. The harness applies a fixed rule to those probabilities: threshold 0.55;
three or more above it keep the top two, the second only within 0.20 of the top. It puts the
chosen bodies into Working Memory before DeepSeek is called, so DeepSeek's first call is
spent on real work. The Decider gets 0.7 s and no retry. Every failure — timeout, rate
limit, malformed answer, missing key — skips Priming and runs the turn exactly as before.

## This is not the router ADR 0001 deleted

ADR 0001 removed a keyword intent classifier: deterministic code that picked the scenario
and forced the tool sequence. This is not rule-based intent classification. It is a model
analysing the customer's intent to name the Skills that apply, a judgment the main model
was already making, now made by a faster model one step earlier. Three things separate it
from that router:

- **A model judges, not a rule.** The deterministic part — the threshold, the margin and the
  cap of two — decides only how sure the Decider must be before its answer is used. It was
  fitted on the Golden Set's development split and published on the held-out split (#18).
- **It selects no action.** Priming adds context; it does not choose a tool call. The `Skill`
  tool stays in the tool list, Priming never forces `tool_choice` and hides no tool. The
  main model can still load any Skill the Decider missed, and it chooses every action the
  customer sees.
- **Its bias is measured, not assumed.** The Golden Set scores its selections against
  labels, and the behaviour cases run with Priming off and on.

ADR 0001's test asks whether removing a piece of code would change *what* the model does,
rather than *whether it is allowed to*. By its letter, Priming fails it: without Priming the
model would spend its first call loading the Skill. The test was written for deterministic
code standing in for a model's choice. Here the choice is still a model's, and nothing the
main model may do is taken away. What changes is when a Skill's instructions arrive.
ADR 0001 is amended to say so. Any later use of the Decider is held to the two lines
below.

## The two lines

1. **Priming only adds context.** Nothing the main model could do before is taken away.
   A wrong, silent, slow or unsure Decider costs a round, never a choice, so every failure
   degrades to today's behaviour and none below it.
2. **The Decider only takes over judgments a model was already making.** It answers
   questions that needed a model's reading of the conversation. Anything code already
   settles stays with code.

## Deterministic Guardrails were rejected as candidates, not deferred

`handoff_validity`'s evidence match, `internal_canary`'s blocklist, `turn_budget` and
`result_cap` each run in microseconds. Handing one to a network call would add 0.2–0.7 s
to the turn, the opposite of the goal. It would also replace a check that cannot be
argued with by one that answers with a probability. No measurement could change that,
because the cost is in the shape of the call, not in its tuning. These checks are
therefore recorded as rejected candidates for the Decider, not as later work. The same goes for a
Guardrail that would deny a tool call sharing a round with a `Skill` call. It would cost a
round exactly when Priming did not fire, making the fallback slower than today. The rate
of such calls is measured instead: with Priming off it was 3, 2 and 5 of 19 first turns per
run, and with Priming on it was 0.

## The primed message is a persisted `system` message

The chosen bodies go into Working Memory as one harness-authored `system` message, just
before the customer's new message. Its marker names the primed Skills and says `Skill` need
not be called for them.

- **`system`, not `user`.** `handoff_validity` reads the customer's words from `user` rows.
  So do the Compaction summariser and the Reflection pass. A `user`-role Skill body would let
  the model quote the Skill's own wording as the customer's evidence for a Handoff. All three
  already skip `system` rows, so none of them needed a change.
- **Persisted, not request-only.** A message inserted into one request and not stored would
  make the next turn's message sequence diverge at that position, and the rest would miss the
  prompt cache. Stored, the prefix stays append-only (ADR 0005). A probe during design,
  with thinking on and tools present, saw the next turn's cache hit through it: 384 of 511
  prompt tokens (spec #14).
- **At most once per Session.** The Decider is asked only about Skills not already in Working
  Memory. A `Skill` call for a body already there gets a short "already in context" note
  instead of a second copy (`skill_already_in_context`). This also bounds the cost of the
  model ignoring the marker. When Compaction folds a turn away, its primed message goes with
  it, and the Skill may be primed or loaded again.

## Considered Options

- **A fabricated tool call.** The harness would write a synthetic `assistant` message calling
  `Skill`, plus its tool result, so Working Memory kept its usual shape. With thinking on,
  DeepSeek rejects an `assistant` message that carries tool calls without its
  `reasoning_content` (HTTP 400: "The `reasoning_content` in the thinking mode must be passed
  back to the API"). The harness would have to invent the model's reasoning. The message
  would also differ between thinking on and thinking off, forking both the code and the
  four-arm experiment.
- **Pre-loading every Skill.** The eleven bodies are about 8,000 tokens together. They would
  go into every turn, and the model would read nine manuals that do not apply.
- **The keyword classifier back.** This is what ADR 0001 forbids.
- **One `choice` question instead of eleven yes/no questions.** `choice` picks exactly one
  option, but a turn can need two Skills, for example `pricing_conversation` with
  `discovery`. The vendor's documented form for several labels is one yes/no question per
  candidate.
- **Narrowing the model on the Decider's word**, by forcing `tool_choice`, hiding tools or
  skipping rounds. Each breaks the first line.
- **Turning thinking off, or a cheaper main model, in the same change.** Either might be
  faster, but if it landed with Priming neither could be credited. Both were measured as
  arms on the Golden Set and neither was shipped.
- **The vendor's SDK.** Its defaults are a 10 s timeout and retries up to 30 s, exactly what
  this path must not do. It would wrap one POST, which `httpx` sends with an explicit
  timeout and one attempt.

## Consequences

Measured in #19 on three behaviour runs with Priming off and two with it on, at the shipped
defaults ([`priming-verdict.md`](../../evals/reports/priming-verdict.md)):

- **Quality held.** First-action accuracy went from 98% to 100%, the judge's mean from 4.26
  to 4.38, and nothing leaked. A primed Skill counts as the first move, and 27 of the 38
  passes with Priming on rest on that credit. So that number says the right Skill got in
  first; the judge says what the model did with it.
- **About a third of the tool rounds went: −0.64 per turn (95% −0.97 to −0.29).** On the
  13 turns whose first round only loaded Skills, rounds fell by 1.2 on average, a full
  round on 10.
- **Whether turns got faster is not established: −1.6 s per turn (95% −4.1 to +0.9).** Whole
  runs drift with the provider's speed: mean turn latency per run was 13.0, 14.8 and 15.8 s
  off, and 13.1 and 12.8 s on. About five runs a side would separate a change of this size.
  The p90 gain #14 expected could not be confirmed or refuted either: the runs with Priming
  off disagree by 10.1 s at turn p90. Per case, p50 / p90 was 15.7 / 37.6 s with Priming off
  and 12.1 / 36.7 s with it on. #14's 13.7 / 48.8 s came from an earlier run, before
  #15–#18, so it is not a like-for-like baseline.
- **The Decider stayed in budget and Priming is used.** Its p95 was 0.3 s. 76% of turns were
  primed, and the rest were below the threshold. No primed turn reloaded a primed Skill.
- **Skill selection at the shipped point**, on the held-out Golden Set: exact set 80%,
  recall 91%, 18 of 22 Skill rounds saved, 4 wrong primes.
- **Priming ships off** (`HARNESS_PRIMING=1` turns it on). It needs `TYPESAFE_API_KEY` and
  adds a call to a second vendor on every turn that has a Skill left to ask about. The
  Decider's p50 was 0.2 s.
- **The rest of the gap is a different decision.** On the Golden Set, `deepseek-flash` picks
  Skills as well as the main model with thinking on (F1 96% against 93%) and decides 0.9 s
  faster. That is roughly 1.5 s a turn, short of a 6 s p50 on its own. Turning thinking off
  loses 25 points of F1. Adopting either is outside this record.
- **A new Skill is a new question.** Its one-line description becomes the Decider's
  question, so it needs Golden Set labels, and the threshold fit needs rerunning, before its
  priming can be trusted.
