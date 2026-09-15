# The model decides; deterministic logic only guards

The first version routed every turn through rules before the model saw it: a keyword
intent classifier picked the scenario, the scenario forced specific tool calls, and
literal trigger phrases decided whether to escalate. That made the system cheap and
predictable but dated — rules were making the decisions an LLM is better at, and the
model was reduced to filling in text.

We are rebuilding the harness on the opposite principle, the one Claude Code uses:
**the model chooses what to do (which skill to load, which tools to call, whether to
propose a handoff); deterministic code only validates or constrains those choices** as
guardrails — permission gates, evidence checks, output validators, context budgets.
No rule may select an action on the model's behalf.

## Consequences

- Every turn costs at least one model call carrying the full tool and skill index;
  the zero-cost keyword fast path is gone. We accept this and recover cost with
  prompt caching and cheaper models for sub-tasks.
- "Is this a router or a guardrail?" is the test for any new deterministic code.
  If removing it would change *what* the model does rather than *whether it is
  allowed to*, it is a router and does not belong.
