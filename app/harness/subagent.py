"""
Sub-agents — a bounded model loop with its own context that returns a Brief.

A sub-agent is a tool whose implementation is itself a small agent: it gets a
task, a system prompt of its own, a restricted tool set, its own (usually
cheaper) model, and a round cap. Nothing from the main conversation is passed
in and nothing but the brief comes out, so the main context stays small no
matter how much the sub-agent reads (ADR 0006). The same runner serves
research now and reflection later; the wording a sub-agent uses when its
budget runs out belongs to its spec, not to the runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.harness.guardrails import cap_result
from app.harness.provider import CompletionRequest, Provider, Usage, drain
from app.harness.tools import ToolContext, ToolRegistry


# ---------------------------------------------------------------------------
# What a sub-agent is
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SubagentSpec:
    name: str
    model: str
    system_prompt: str
    tools: ToolRegistry  # the only tools this loop may call
    max_rounds: int = 3  # model responses with tool calls before the brief is forced
    max_tokens: int = 2048
    thinking: str = "enabled"
    result_cap_chars: int = 6000
    cap_note: str = (
        "You have used all your tool rounds. Write your brief now from what you have found, "
        "and say what you could not confirm."
    )
    gave_up_brief: str = "The task could not be completed within its budget; nothing reliable was found to report."


@dataclass(frozen=True)
class SubagentMetering:
    """What the harness books for one delegation, apart from the main model's own usage."""

    provider_calls: int
    usage: Usage
    rounds: int


@dataclass
class SubagentResult:
    brief: str = ""
    usage: Usage = field(default_factory=Usage)
    provider_calls: int = 0
    rounds: int = 0
    tool_calls: list[str] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    stopped_by_cap: bool = False  # the brief was forced after max_rounds
    gave_up: bool = False  # the model still asked for tools when forced; the brief is the spec's fallback text

    def payload(self) -> dict[str, Any]:
        """The tool-result shape a sub-agent hands back to the main conversation."""
        return {
            "brief": self.brief,
            "sources": self.sources,
            "tool_calls": len(self.tool_calls),
            "stopped_by_cap": self.stopped_by_cap,
            "gave_up": self.gave_up,
        }

    def metering(self) -> SubagentMetering:
        return SubagentMetering(provider_calls=self.provider_calls, usage=self.usage, rounds=self.rounds)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
def run_subagent(spec: SubagentSpec, provider: Provider, task: str, ctx: ToolContext) -> SubagentResult:
    """Run the loop to a brief. Progress is reported through `ctx.emit` as it happens."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content": task},
    ]
    definitions = spec.tools.definitions()
    result = SubagentResult()
    ctx.emit("subagent_started", {"name": spec.name, "task": task})

    while True:
        forced = result.rounds >= spec.max_rounds
        completion, _ = drain(provider.complete(CompletionRequest(
            model=spec.model, messages=list(messages), tools=definitions,
            max_tokens=spec.max_tokens, thinking=spec.thinking, tool_choice="none" if forced else None,
        )))
        result.provider_calls += 1
        result.usage = result.usage + completion.usage
        messages.append(completion.to_message())

        if not completion.tool_calls or forced:
            result.gave_up = bool(completion.tool_calls)  # ignored the forced text round
            result.brief = spec.gave_up_brief if result.gave_up else (completion.content.strip() or spec.gave_up_brief)
            result.stopped_by_cap = forced
            break

        result.rounds += 1
        for call in completion.tool_calls:
            result.tool_calls.append(call.name)
            ctx.emit("subagent_tool_call", {"name": spec.name, "tool": call.name, "arguments": call.arguments})
            tool_result = spec.tools.dispatch(call.name, call.arguments, ctx)
            tool_result = cap_result(tool_result, spec.result_cap_chars) or tool_result
            for source in tool_result.meta.get("sources") or ():
                if source not in result.sources:
                    result.sources.append(source)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": tool_result.content})
        if result.rounds >= spec.max_rounds:
            messages.append({"role": "user", "content": spec.cap_note})

    ctx.emit("subagent_finished", {
        "name": spec.name, "rounds": result.rounds, "tool_calls": len(result.tool_calls),
        "chars": len(result.brief), "stopped_by_cap": result.stopped_by_cap, "gave_up": result.gave_up,
    })
    return result
