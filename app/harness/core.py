"""
The harness — one model-driven loop per turn.

A turn: bind the session (SessionStart on first contact), assemble the request
in the fixed order, stream the model's reply, append both sides to working
memory, record metrics. The harness decides nothing about *what* to say; it
only builds the request, moves bytes, and keeps the books (ADR 0001).

Tool dispatch, hooks around tools, and the Stop hook arrive with later tickets;
this loop is shaped so they slot into `run_turn` without changing its contract.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator

from app import database
from app.harness import prompt
from app.harness.hooks import HookEvent, HookRegistry, SessionStartContext
from app.harness.provider import (
    Completed,
    Completion,
    CompletionRequest,
    Provider,
    ReasoningDelta,
    TextDelta,
    Usage,
)
from app.metrics import TurnRecord, record_turn

FRIENDLY_FAILURE = (
    "I'm sorry — I couldn't finish that reply just now. "
    "Please try again in a moment; your conversation so far is safe."
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

    @classmethod
    def from_env(cls) -> "HarnessConfig":
        return cls(
            main_model=os.environ.get("HARNESS_MAIN_MODEL", cls.main_model),
            max_tokens=int(os.environ.get("HARNESS_MAX_TOKENS", cls.max_tokens)),
            thinking=os.environ.get("HARNESS_THINKING", cls.thinking),
        )


@dataclass(frozen=True)
class TurnEvent:
    """What the transport layer forwards to the customer's client."""

    name: str  # text_delta | thinking | done | error
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Harness:
    provider: Provider
    config: HarnessConfig
    static_prompt: str
    hooks: HookRegistry

    @classmethod
    def build(cls, provider: Provider, config: HarnessConfig | None = None) -> "Harness":
        """Render the static prompt once, from the policy register, and wire default hooks."""
        config = config or HarnessConfig.from_env()
        static = prompt.static_system_prompt(database.get_active_policies())
        hooks = HookRegistry()
        hooks.register(HookEvent.SESSION_START, _profile_hook)
        return cls(provider=provider, config=config, static_prompt=static, hooks=hooks)

    # ------------------------------------------------------------------
    def run_turn(self, session_id: str, customer_id: str | None, message: str) -> Iterator[TurnEvent]:
        session = self._bind_session(session_id, customer_id)
        # Assistant rows carry their reasoning_content on purpose: DeepSeek requires it
        # back whenever `tools` are present and ignores it otherwise (thinking-mode guide).
        working_memory = database.load_messages(session_id)
        request = CompletionRequest(
            model=self.config.main_model,
            messages=prompt.assemble_messages(self.static_prompt, session["customer_block"], working_memory, message),
            tools=(),
            max_tokens=self.config.max_tokens,
            thinking=self.config.thinking,
        )

        turn_id = uuid.uuid4().hex
        started = time.perf_counter()
        completion: Completion | None = None
        announced_thinking = False

        def book(usage: Usage = Usage(), model: str = request.model, error: str | None = None) -> None:
            record_turn(TurnRecord(
                turn_id=turn_id, session_id=session_id, customer_id=session["customer_id"], model=model,
                prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                cache_hit_tokens=usage.cache_hit_tokens, cache_miss_tokens=usage.cache_miss_tokens,
                provider_calls=1, latency_ms=int((time.perf_counter() - started) * 1000), error=error,
            ))

        try:
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

        assistant: dict[str, Any] = {"role": "assistant", "content": completion.content}
        if completion.reasoning_content:
            assistant["reasoning_content"] = completion.reasoning_content
        database.append_messages(session_id, [{"role": "user", "content": message}, assistant])

        book(usage=completion.usage, model=completion.model or request.model)
        yield TurnEvent("done", {
            "turn_id": turn_id,
            "session_id": session_id,
            "reply": completion.content,
            "usage": asdict(completion.usage),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        })

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


def _profile_hook(ctx: SessionStartContext) -> str:
    return prompt.customer_block(ctx.profile, ctx.product_usage)
