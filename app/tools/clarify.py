"""
ask_customer — a clarifying question with options the customer can click.

Claude Code's AskUserQuestion, pointed at the customer. When a request could
reasonably mean different things, the model asks instead of guessing; the
turn ends with the question, the UI shows the options, and whatever the
customer picks (or types) is simply the next message. The tool's result is
written immediately, so working memory stays a valid sequence without any pending state.
"""

from __future__ import annotations

from typing import Any

from app.harness.guardrails import find_placeholders, leaks
from app.harness.hooks import Deny, HookEvent, HookRegistry, ToolUseContext
from app.harness.tools import EndTurn, Tool, ToolContext, ToolRegistry, ToolResult

MIN_OPTIONS, MAX_OPTIONS = 2, 5


def ask_customer(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    question = (args.get("question") or "").strip()
    options = [str(o).strip() for o in args.get("options") or [] if str(o).strip()]
    if not question:
        return ToolResult.error("ask_customer needs a question.")
    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        return ToolResult.error(
            f"ask_customer needs between {MIN_OPTIONS} and {MAX_OPTIONS} distinct options (got {len(options)}). "
            "If the answer is open-ended, ask in plain text instead of calling the tool."
        )
    if len(set(o.lower() for o in options)) != len(options):
        return ToolResult.error("ask_customer options must be distinct.")
    return ToolResult(
        content="The question and options are shown to the customer; their answer arrives as the next message.",
        meta={"end_turn": EndTurn(event="ask_customer", data={"question": question, "options": options}, reply=question)},
    )


def clean_question(ctx: ToolUseContext) -> Deny | None:
    """The question and its options reach the customer as-is, so they pass the same checks as a reply."""
    if ctx.tool.name != "ask_customer":
        return None
    shown = " | ".join([str(ctx.arguments.get("question") or ""), *(str(o) for o in ctx.arguments.get("options") or [])])
    problems = [*find_placeholders(shown), *leaks(shown)]
    if not problems:
        return None
    return Deny(
        "the question would reach the customer with material they must not see or unfilled blanks ("
        + ", ".join(dict.fromkeys(problems)) + "). Ask it again without them."
    )


def register_guardrails(hooks: HookRegistry) -> None:
    hooks.register(HookEvent.PRE_TOOL_USE, clean_question)


def register(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="ask_customer",
        description=(
            "Ask the customer a clarifying question with 2-5 short options they can click, when their request "
            "could reasonably mean different things and the difference changes your answer. Ends your turn; "
            "their choice comes back as their next message. Do not use it for open-ended questions or when "
            "the profile already answers it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question, in the customer's language, one sentence."},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": MIN_OPTIONS,
                    "maxItems": MAX_OPTIONS,
                    "description": "Short, distinct, mutually exclusive choices. Add an 'Other' style option when the list may not cover it.",
                },
            },
            "required": ["question", "options"],
            "additionalProperties": False,
        },
        run=ask_customer,
        cacheable=False,
    ))
