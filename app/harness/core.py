"""
The harness — one model-driven loop per turn.

A turn: bind the session (SessionStart on first contact), assemble the request
in the fixed order, stream the model's reply; while the reply asks for tools,
run them through the PreToolUse / PostToolUse hooks and go round again; then
append everything to working memory and record metrics. The harness decides
nothing about *what* to do; it builds requests, moves bytes, and keeps the
books (ADR 0001).
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Iterator

from app import database
from app.harness import guardrails, prompt
from app.harness.hooks import (
    Deny,
    HookEvent,
    HookRegistry,
    Replace,
    SessionStartContext,
    ToolUseContext,
    TurnState,
)
from app.harness.provider import (
    Completed,
    Completion,
    CompletionRequest,
    Provider,
    ReasoningDelta,
    TextDelta,
    ToolCall,
    Usage,
)
from app.harness.skills import Skill, load_skills, register_skill_tool, skills_index
from app.harness.tools import ToolContext, ToolRegistry, ToolResult
from app.metrics import TurnRecord, record_turn
from app.paths import SKILLS_DIR
from app.tools import register_all

FRIENDLY_FAILURE = (
    "I'm sorry — I couldn't finish that reply just now. "
    "Please try again in a moment; your conversation so far is safe."
)
HARD_STOP_REPLY = (
    "I wasn't able to finish checking everything for that. "
    "Here is what I can say so far — and I'm happy to pick up where I left off."
)


class UnknownCustomer(LookupError):
    """A session was opened for a customer id that is not in the seed database."""


class SessionCustomerMismatch(ValueError):
    """A request named a different customer than the one the session is bound to."""


@dataclass(frozen=True)
class HarnessConfig:
    main_model: str = "deepseek-v4-pro"
    max_tokens: int = 4096
    thinking: str = "enabled"
    skills_dir: Path = SKILLS_DIR
    tool_round_budget: int = 8  # model responses with tool calls allowed per turn
    result_cap_chars: int = 6000  # ≈1.5K tokens; larger tool results are truncated
    tool_cache_ttl_seconds: float = 900.0

    @classmethod
    def from_env(cls) -> "HarnessConfig":
        return cls(
            main_model=os.environ.get("HARNESS_MAIN_MODEL", cls.main_model),
            max_tokens=int(os.environ.get("HARNESS_MAX_TOKENS", cls.max_tokens)),
            thinking=os.environ.get("HARNESS_THINKING", cls.thinking),
            skills_dir=Path(os.environ.get("HARNESS_SKILLS_DIR", cls.skills_dir)),
            tool_round_budget=int(os.environ.get("HARNESS_TOOL_ROUND_BUDGET", cls.tool_round_budget)),
            result_cap_chars=int(os.environ.get("HARNESS_RESULT_CAP_CHARS", cls.result_cap_chars)),
            tool_cache_ttl_seconds=float(os.environ.get("HARNESS_TOOL_CACHE_TTL_SECONDS", cls.tool_cache_ttl_seconds)),
        )


@dataclass(frozen=True)
class TurnEvent:
    """What the transport layer forwards to the customer's client."""

    name: str  # text_delta | thinking | tool_call | tool_result | skill_loaded | hook_blocked | done | error
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Books:
    """Per-turn counters that end up in the TurnRecord."""

    usage: Usage = Usage()
    model: str = ""
    provider_calls: int = 0
    tools_called: list[str] = field(default_factory=list)
    skills_loaded: list[str] = field(default_factory=list)
    hook_outcomes: dict[str, int] = field(default_factory=dict)
    cache_hits: int = 0

    def add_usage(self, usage: Usage) -> None:
        self.usage = Usage(**{f.name: getattr(self.usage, f.name) + getattr(usage, f.name) for f in fields(Usage)})

    def outcome(self, name: str) -> None:
        self.hook_outcomes[name] = self.hook_outcomes.get(name, 0) + 1


@dataclass
class Harness:
    provider: Provider
    config: HarnessConfig
    static_prompt: str
    hooks: HookRegistry
    tools: ToolRegistry
    skills: dict[str, Skill]

    @classmethod
    def build(cls, provider: Provider, config: HarnessConfig | None = None) -> "Harness":
        """Load skills, register tools and guardrails, and render the static prompt once."""
        config = config or HarnessConfig.from_env()
        skills = load_skills(config.skills_dir)

        tools = ToolRegistry()
        register_skill_tool(tools, skills)
        register_all(tools)

        hooks = HookRegistry()
        hooks.register(HookEvent.SESSION_START, _profile_hook)
        guardrails.register_defaults(
            hooks,
            tool_round_budget=config.tool_round_budget,
            result_cap_chars=config.result_cap_chars,
            cache=guardrails.ToolCache(ttl_seconds=config.tool_cache_ttl_seconds),
        )

        static = prompt.static_system_prompt(database.get_active_policies(), skills_index(skills))
        return cls(provider=provider, config=config, static_prompt=static, hooks=hooks, tools=tools, skills=skills)

    # ------------------------------------------------------------------
    def run_turn(self, session_id: str, customer_id: str | None, message: str) -> Iterator[TurnEvent]:
        session = self._bind_session(session_id, customer_id)
        turn = TurnState(session_id=session_id, customer_id=session["customer_id"])
        # Assistant rows carry their reasoning_content on purpose: DeepSeek requires it
        # back whenever `tools` are present (thinking-mode guide).
        messages = prompt.assemble_messages(
            self.static_prompt, session["customer_block"], database.load_messages(session_id), message
        )
        new_messages: list[dict[str, Any]] = [messages[-1]]  # the customer's message, then everything this turn adds
        tool_definitions = self.tools.definitions()

        turn_id = uuid.uuid4().hex
        started = time.perf_counter()
        books = _Books(model=self.config.main_model)
        announced_thinking = False

        def book(error: str | None = None) -> None:
            record_turn(TurnRecord(
                turn_id=turn_id, session_id=session_id, customer_id=session["customer_id"], model=books.model,
                prompt_tokens=books.usage.prompt_tokens, completion_tokens=books.usage.completion_tokens,
                reasoning_tokens=books.usage.reasoning_tokens,
                cache_hit_tokens=books.usage.cache_hit_tokens, cache_miss_tokens=books.usage.cache_miss_tokens,
                provider_calls=books.provider_calls, tool_rounds=turn.tool_rounds,
                tools_called=books.tools_called, skills_loaded=books.skills_loaded,
                hook_outcomes=books.hook_outcomes, cache_hits=books.cache_hits,
                latency_ms=int((time.perf_counter() - started) * 1000), error=error,
            ))

        try:
            while True:
                request = CompletionRequest(
                    model=self.config.main_model,
                    messages=list(messages),
                    tools=tool_definitions,
                    max_tokens=self.config.max_tokens,
                    thinking=self.config.thinking,
                    # Once turn_budget has denied a call, the model must answer in text.
                    tool_choice="none" if turn.tools_exhausted else None,
                )
                asked_for_text = turn.tools_exhausted
                completion: Completion | None = None
                books.provider_calls += 1
                for event in self.provider.complete(request):
                    if isinstance(event, TextDelta):
                        yield TurnEvent("text_delta", {"text": event.text})
                    elif isinstance(event, ReasoningDelta) and not announced_thinking:
                        announced_thinking = True
                        yield TurnEvent("thinking", {})
                    elif isinstance(event, Completed):
                        completion = event.completion
                if completion is None:
                    raise RuntimeError("provider stream ended without a completion")
                books.add_usage(completion.usage)
                books.model = completion.model or books.model

                if completion.tool_calls and asked_for_text:
                    # The model ignored tool_choice="none". Stop here rather than loop on denials.
                    books.outcome("hard_stop")
                    completion = Completion(
                        content=completion.content or HARD_STOP_REPLY,
                        reasoning_content=completion.reasoning_content,
                        finish_reason="stop", usage=completion.usage, model=completion.model,
                    )
                assistant = _assistant_message(completion)
                messages.append(assistant)
                new_messages.append(assistant)
                if not completion.tool_calls:
                    break

                turn.tool_rounds += 1
                for call in completion.tool_calls:
                    result_message, events = self._run_tool(turn, call, books)
                    yield from events
                    messages.append(result_message)
                    new_messages.append(result_message)
        except GeneratorExit:
            # The customer went away mid-reply. The tokens were still spent; keep the books.
            book(error="ClientDisconnected")
            raise
        except Exception as exc:  # noqa: BLE001 — any provider failure ends the turn gently
            book(error=f"{type(exc).__name__}: {exc}"[:500])
            yield TurnEvent("error", {
                "turn_id": turn_id, "session_id": session_id,
                "reply": FRIENDLY_FAILURE, "error": type(exc).__name__,
            })
            return

        database.append_messages(session_id, new_messages)
        book()
        yield TurnEvent("done", {
            "turn_id": turn_id,
            "session_id": session_id,
            "reply": completion.content,
            "usage": asdict(books.usage),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "tool_rounds": turn.tool_rounds,
        })

    # ------------------------------------------------------------------
    def _run_tool(self, turn: TurnState, call: ToolCall, books: _Books) -> tuple[dict[str, Any], list[TurnEvent]]:
        """Dispatch one tool call through the hooks; return its tool message and the events to emit."""
        events: list[TurnEvent] = [TurnEvent("tool_call", {"call_id": call.id, "name": call.name, "arguments": call.arguments})]
        books.tools_called.append(call.name)

        tool = self.tools.get(call.name)
        if tool is None:
            feedback = f"No tool named {call.name!r}. Available tools: {', '.join(self.tools.names())}."
            return _tool_message(call, feedback), events

        parsed = self.tools.parse_arguments(tool, call.arguments)
        if isinstance(parsed, str):
            return _tool_message(call, parsed), events

        ctx = ToolUseContext(turn=turn, tool=tool, call_id=call.id, arguments=parsed)
        decision = self.hooks.run_pre_tool_use(ctx)
        if isinstance(decision.outcome, Deny):
            # The feedback is for the model; the customer's client only learns which hook spoke.
            books.outcome("denied")
            events.append(TurnEvent("hook_blocked", {"call_id": call.id, "tool": call.name, "hook": decision.hook}))
            return _tool_message(call, f"Blocked by {decision.hook}: {decision.outcome.feedback}"), events

        if isinstance(decision.outcome, Replace):
            books.outcome("replaced")
            result = decision.outcome.result
        else:
            books.outcome("allowed")
            raw = self.tools.call(tool, ToolContext(turn.session_id, turn.customer_id), parsed)
            result = self.hooks.run_post_tool_use(ctx, raw)
            if result is not raw:
                books.outcome("modified")
        if result.meta.get("cached"):
            books.cache_hits += 1

        if skill := result.meta.get("skill"):
            books.skills_loaded.append(skill)
            events.append(TurnEvent("skill_loaded", {"call_id": call.id, "name": skill}))
        else:
            events.append(TurnEvent("tool_result", {
                "call_id": call.id, "name": call.name, "chars": len(result.content),
                "cached": bool(result.meta.get("cached")), "is_error": result.is_error,
            }))
        return _tool_message(call, result.content), events

    # ------------------------------------------------------------------
    def _bind_session(self, session_id: str, customer_id: str | None) -> dict[str, Any]:
        """Return the session, starting it on first contact; refuse a customer switch."""
        session = database.load_session(session_id)
        if session is None:
            return self._start_session(session_id, customer_id)
        if customer_id and customer_id != session["customer_id"]:
            raise SessionCustomerMismatch(
                f"session {session_id} belongs to customer {session['customer_id']!r}, not {customer_id!r}"
            )
        return session

    def _start_session(self, session_id: str, customer_id: str | None) -> dict[str, Any]:
        """SessionStart: freeze the customer block for the life of the session."""
        profile = database.get_customer(customer_id) if customer_id else None
        if customer_id and profile is None:
            raise UnknownCustomer(customer_id)
        ctx = SessionStartContext(
            session_id=session_id,
            customer_id=customer_id or None,
            profile=profile,
            product_usage=database.get_customer_product_usage(customer_id) if profile else [],
        )
        block = "\n\n".join(self.hooks.run_session_start(ctx))
        return database.create_session(session_id, ctx.customer_id, block)


def _assistant_message(completion: Completion) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant", "content": completion.content}
    if completion.reasoning_content:
        msg["reasoning_content"] = completion.reasoning_content
    if completion.tool_calls:
        msg["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in completion.tool_calls
        ]
    return msg


def _tool_message(call: ToolCall, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call.id, "content": content}


def _profile_hook(ctx: SessionStartContext) -> str:
    return prompt.customer_block(ctx.profile, ctx.product_usage)
