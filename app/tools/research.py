"""
research — a Sub-agent that searches several times and returns a cited Brief.

For a question that spans products, needs a comparison, or came back thin from
a single search, the model delegates: a bounded loop on the cheaper model, with
`search_knowledge` as its only tool, reads as much as it needs in its own
context and hands back a short brief with sources. Only the brief enters the
main conversation (ADR 0006).
"""

from __future__ import annotations

from typing import Any

from app.harness.provider import Provider
from app.harness.subagent import SubagentSpec, run_subagent
from app.harness.tools import Tool, ToolContext, ToolFunction, ToolRegistry, ToolResult
from app.retrieval.index import KnowledgeIndex
from app.tools import knowledge

RESEARCH_SYSTEM_PROMPT = """You are a research assistant inside Stripe's AI sales agent. You receive one question about Stripe's products and answer it from Stripe's public documentation using the search_knowledge tool.

Method:
- Search first with the products and topics the question names. Read the passages.
- If the answer is incomplete, search again with a narrower question or a neighbouring product. You have a small number of searches; make each one count.
- Never invent facts, prices or limits. If the documentation does not say, say so.

Then write the brief:
- At most 200 words, plain prose or short bullets, in English.
- Every factual statement is followed by its source title in square brackets, e.g. [Stripe Checkout].
- Close with one line on what you could not confirm, if anything.
- No greetings, no advice on what to tell the customer — facts only."""

CAP_NOTE = (
    "You have used all your searches. Write the brief now from what you have found, "
    "and say what you could not confirm."
)
GAVE_UP_BRIEF = "Research could not be completed within its search budget; nothing reliable was found to report."


def make_research(
    provider: Provider, index: KnowledgeIndex, *, model: str, max_rounds: int, thinking: str, result_cap_chars: int
) -> ToolFunction:
    search_only = ToolRegistry()
    knowledge.register(search_only, index)
    spec = SubagentSpec(
        name="research", model=model, system_prompt=RESEARCH_SYSTEM_PROMPT, tools=search_only,
        max_rounds=max_rounds, thinking=thinking, result_cap_chars=result_cap_chars,
        cap_note=CAP_NOTE, gave_up_brief=GAVE_UP_BRIEF,
    )

    def research(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        question = (args.get("question") or "").strip()
        if not question:
            return ToolResult.error("research needs a question.")
        result = run_subagent(spec, provider, question, ctx)
        # The documents the brief cites in [Title] form are its sources. A brief that cites
        # nothing keeps everything it read, so the customer can still see what was consulted.
        cited = [s for s in result.sources if f"[{s['title']}]" in result.brief]
        result.sources = cited or result.sources
        return ToolResult.from_payload(result.payload(), sources=result.sources, subagent=result.metering())

    return research


def register(
    registry: ToolRegistry, provider: Provider, index: KnowledgeIndex, *,
    model: str, max_rounds: int, thinking: str, result_cap_chars: int,
) -> None:
    registry.register(Tool(
        name="research",
        description=(
            "Delegate a hard question to a research assistant that searches Stripe's public documentation "
            "several times and returns a short cited brief. Use it when the question spans several products, "
            "asks for a comparison, or when search_knowledge came back thin. Slower and heavier than a single "
            "search — for one specific question, call search_knowledge yourself."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "The question to research, self-contained: name the products, markets and constraints that matter."
                    ),
                },
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        run=make_research(provider, index, model=model, max_rounds=max_rounds, thinking=thinking, result_cap_chars=result_cap_chars),
        cacheable=True,  # the same question in one session gets the same brief; the delegation is not re-booked
    ))
