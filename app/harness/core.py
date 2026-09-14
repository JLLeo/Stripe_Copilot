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
import queue
import threading
import time
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Generator, Iterator

from app import database
from app.harness import context, guardrails, prompt
from app.harness.hooks import (
    Deny,
    HookEvent,
    HookRegistry,
    Pause,
    Replace,
    SessionEndContext,
    SessionStartContext,
    StopContext,
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
from app.harness.subagent import SubagentMetering
from app.harness.tools import EndTurn, ToolContext, ToolRegistry, ToolResult
from app.metrics import TurnRecord, record_turn
from app.paths import SKILLS_DIR
from app.retrieval.index import DEFAULT_MILVUS_URI, KnowledgeIndex
from app.tools import handoff, register_all

log = logging.getLogger(__name__)

FRIENDLY_FAILURE = (
    "I'm sorry — I couldn't finish that reply just now. "
    "Please try again in a moment; your conversation so far is safe."
)
HARD_STOP_REPLY = (
    "I wasn't able to finish checking everything for that. "
    "Here is what I can say so far — and I'm happy to pick up where I left off."
)
SAFE_REPLY = (
    "I want to give you an accurate answer, and my draft wasn't right. "
    "Could you tell me a little more about what you need? I can also bring in a colleague who can help directly."
)
MAX_REWRITES = 2  # Stop-hook rewrites before the safe reply replaces the draft


class UnknownCustomer(LookupError):
    """A session was opened for a customer id that is not in the seed database."""


class SessionCustomerMismatch(ValueError):
    """A request named a different customer than the one the session is bound to."""


class NothingPending(LookupError):
    """A confirmation arrived for a session with no handoff waiting for one."""


class UnknownSession(LookupError):
    """A request named a session that was never started."""


class SessionEnded(ValueError):
    """The customer ended this conversation; it takes no more turns and cannot be ended twice."""


@dataclass(frozen=True)
class HarnessConfig:
    main_model: str = "deepseek-v4-pro"
    max_tokens: int = 4096
    thinking: str = "enabled"
    skills_dir: Path = SKILLS_DIR
    tool_round_budget: int = 8  # model responses with tool calls allowed per turn
    result_cap_chars: int = 6000  # ≈1.5K tokens; larger tool results are truncated
    tool_cache_ttl_seconds: float = 900.0
    milvus_uri: str = DEFAULT_MILVUS_URI
    sub_model: str = "deepseek-flash"  # sub-agents: research, reflection; also the compaction summary
    subagent_max_rounds: int = 3
    memory_limit: int = 12  # active Customer Memory facts rendered into the customer block at SessionStart
    # Context pressure (ADR 0006). Every threshold lives here; triggers read the provider's reported
    # prompt_tokens, sizes use a characters/4 estimate.
    turn_result_budget_chars: int = 24_000  # ≈6K tokens of tool results per turn, then results are cut to what is left
    attachment_threshold_chars: int = 8_000  # ≈2K tokens; a longer customer message becomes an Attachment
    context_budget_tokens: int = 96_000  # the share of the context window a session may occupy
    high_water: float = 0.75  # relief runs when the last response reported this share of the budget
    low_water: float = 0.40  # compaction lands here: the summary plus the recent window
    summary_max_tokens: int = 800  # the rolling summary never grows past this
    recent_window_tokens: int = 24_000  # kept verbatim through a compaction

    def __post_init__(self) -> None:
        if not 0 < self.low_water < self.high_water <= 1:
            raise ValueError("water marks must satisfy 0 < low_water < high_water <= 1")
        if self.summary_max_tokens + self.recent_window_tokens > self.low_water * self.context_budget_tokens:
            raise ValueError("summary_max_tokens + recent_window_tokens must fit under the low-water mark")

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
            milvus_uri=os.environ.get("MILVUS_URI", cls.milvus_uri),
            sub_model=os.environ.get("HARNESS_SUB_MODEL", cls.sub_model),
            subagent_max_rounds=int(os.environ.get("HARNESS_SUBAGENT_MAX_ROUNDS", cls.subagent_max_rounds)),
            memory_limit=int(os.environ.get("HARNESS_MEMORY_LIMIT", cls.memory_limit)),
            turn_result_budget_chars=int(os.environ.get("HARNESS_TURN_RESULT_BUDGET_CHARS", cls.turn_result_budget_chars)),
            attachment_threshold_chars=int(os.environ.get("HARNESS_ATTACHMENT_THRESHOLD_CHARS", cls.attachment_threshold_chars)),
            context_budget_tokens=int(os.environ.get("HARNESS_CONTEXT_BUDGET_TOKENS", cls.context_budget_tokens)),
            high_water=float(os.environ.get("HARNESS_HIGH_WATER", cls.high_water)),
            low_water=float(os.environ.get("HARNESS_LOW_WATER", cls.low_water)),
            summary_max_tokens=int(os.environ.get("HARNESS_SUMMARY_MAX_TOKENS", cls.summary_max_tokens)),
            recent_window_tokens=int(os.environ.get("HARNESS_RECENT_WINDOW_TOKENS", cls.recent_window_tokens)),
        )


@dataclass(frozen=True)
class Paused:
    """A turn stopped at a tool call that needs the customer's answer."""

    reply: str
    data: dict[str, Any]


@dataclass(frozen=True)
class Ended:
    """A tool result that also ends the turn (a question for the customer); the result is already written."""

    message: dict[str, Any]
    end: EndTurn


@dataclass(frozen=True)
class TurnEvent:
    """What the transport layer forwards to the customer's client."""

    name: str  # text_delta | thinking | tool_call | tool_result | skill_loaded | hook_blocked | subagent_* | handoff_pending | ask_customer | context_relieved | done | error
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
    subagent_calls: int = 0
    subagent_prompt_tokens: int = 0
    subagent_completion_tokens: int = 0

    def add_subagent(self, metering: SubagentMetering) -> None:
        self.subagent_calls += 1  # one delegation, however many rounds it took
        self.subagent_prompt_tokens += metering.usage.prompt_tokens
        self.subagent_completion_tokens += metering.usage.completion_tokens

    def add_relief(self, relief: "context.Relief") -> None:
        """Relief runs on the sub-agent model: its tokens are booked with the sub-agents', but it is no delegation."""
        self.subagent_prompt_tokens += relief.usage.prompt_tokens
        self.subagent_completion_tokens += relief.usage.completion_tokens
        self.provider_calls += relief.provider_calls
        if relief.cleared:
            self.hook_outcomes["cleared"] = relief.cleared
        if relief.compacted:
            self.hook_outcomes["compacted"] = 1
        if relief.failed:
            self.hook_outcomes["compaction_failed"] = 1

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
    index: KnowledgeIndex

    @classmethod
    def build(cls, provider: Provider, config: HarnessConfig | None = None) -> "Harness":
        """Load skills, register tools and guardrails, and render the static prompt once."""
        config = config or HarnessConfig.from_env()
        skills = load_skills(config.skills_dir)

        index = KnowledgeIndex(provider=provider, milvus_uri=config.milvus_uri)
        hooks = HookRegistry()
        hooks.register(HookEvent.SESSION_START, _profile_hook)
        guardrails.register_defaults(
            hooks,
            tool_round_budget=config.tool_round_budget,
            result_cap_chars=config.result_cap_chars,
            turn_result_budget_chars=config.turn_result_budget_chars,
            cache=guardrails.ToolCache(ttl_seconds=config.tool_cache_ttl_seconds),
        )

        tools = ToolRegistry()
        register_skill_tool(tools, skills)
        register_all(
            tools, hooks, index, provider=provider, sub_model=config.sub_model,
            subagent_max_rounds=config.subagent_max_rounds, thinking=config.thinking,
            result_cap_chars=config.result_cap_chars,
        )

        static = prompt.static_system_prompt(database.get_active_policies(), skills_index(skills), team_for=handoff.team_for_policy)
        return cls(provider=provider, config=config, static_prompt=static, hooks=hooks, tools=tools, skills=skills, index=index)

    def close(self) -> None:
        """Release the knowledge index connection (Milvus Lite holds a file handle)."""
        self.index.close()

    # ------------------------------------------------------------------
    def run_turn(self, session_id: str, customer_id: str | None, message: str) -> Iterator[TurnEvent]:
        """One customer message, to the model's final reply or to a pause for confirmation."""
        session = self._bind_session(session_id, customer_id)
        # Settle first, so relief works on a valid transcript; then relieve pressure from the last
        # response before this turn's request is built (ADR 0006); then render what the model sees.
        self._settled_working_memory(session_id)
        relief = context.relieve(session, self.provider, self.config)
        working_memory = database.load_messages(session_id)
        turn = TurnState(session_id=session_id, customer_id=session["customer_id"], customer_message=message)
        # A long message is kept as an Attachment; the model reads it in pieces. Guardrails still
        # see the whole text on the turn.
        user_message = message
        if len(message) > self.config.attachment_threshold_chars:
            attachment = database.create_attachment(session_id, turn.turn_id, message)
            user_message = context.attachment_stub(attachment["id"], message)
        # Assistant rows carry their reasoning_content on purpose: DeepSeek requires it
        # back whenever `tools` are present (thinking-mode guide).
        messages = prompt.assemble_messages(self.static_prompt, session["customer_block"], working_memory, user_message)
        yield from self._loop(session, turn, messages, new_messages=[messages[-1]], relief=relief)

    def resume_turn(self, session_id: str, accept: bool) -> Iterator[TurnEvent]:
        """The customer answered a pending handoff: settle the paused tool call, then let the model go on.

        The tool result is written to working memory before the model is called, so a
        provider failure here can never leave the transcript with a dangling tool call.
        """
        resolved = handoff.resolve(session_id, accept)
        if resolved is None:
            raise NothingPending(session_id)
        call_id, result = resolved
        session = database.load_session(session_id)
        if session is None:
            raise NothingPending(session_id)
        tool_message = {"role": "tool", "tool_call_id": call_id, "content": result.content}
        database.append_messages(session_id, [tool_message])
        messages = prompt.assemble_prefix(self.static_prompt, session["customer_block"], database.load_messages(session_id))
        turn = TurnState(session_id=session_id, customer_id=session["customer_id"])
        yield from self._loop(session, turn, messages, new_messages=[])

    def end_session(self, session_id: str) -> dict[str, Any]:
        """SessionEnd: the customer is done. The session takes no more turns; reflection keeps what was learned."""
        session = database.load_session(session_id)
        if session is None:
            raise UnknownSession(session_id)
        if not database.end_session(session_id):
            raise SessionEnded(session_id)
        # Marked ended first, so a message racing the reflection is refused rather than forgotten.
        # From here on nothing may fail the request: the session is ended, and cannot be ended again.
        summary: dict[str, Any] = {"session_id": session_id, "reflected": False, "remembered": 0, "merged": 0}
        try:
            customer_id = session["customer_id"]
            ctx = SessionEndContext(
                session_id=session_id, customer_id=customer_id, pass_id=uuid.uuid4().hex,
                working_memory=self._settled_working_memory(session_id),
                memories=database.active_memories(customer_id) if customer_id else [],
            )
            summary.update(self.hooks.run_session_end(ctx))
        except Exception as exc:  # noqa: BLE001 — the customer is gone; report, do not fail
            log.warning("SessionEnd for %s did not complete", session_id, exc_info=True)
            summary["error"] = f"{type(exc).__name__}: {exc}"[:500]
        return summary

    def _settled_working_memory(self, session_id: str) -> list[dict[str, Any]]:
        """Working memory with every proposal answered and every tool call resulted — a valid transcript.

        A handoff still pending when the customer says something else counts as declined. A
        pending row whose tool call never reached working memory (the customer disconnected
        while the question was on its way) is abandoned. Any other tool call left without a
        result gets a "not run" one. Whatever this settles is appended, never rewritten.
        """
        working_memory = database.load_messages(session_id)
        settled: list[dict[str, Any]] = []
        pending = database.pending_handoff(session_id)
        if pending is not None:
            in_transcript = any(
                c["id"] == pending["tool_call_id"]
                for m in working_memory if m["role"] == "assistant" for c in m.get("tool_calls") or []
            )
            if in_transcript:
                resolved = handoff.resolve(session_id, accept=False)
                if resolved is not None:
                    call_id, result = resolved
                    settled.append({"role": "tool", "tool_call_id": call_id, "content": result.content})
            else:
                database.resolve_handoff(pending["id"], database.HANDOFF_ABANDONED)
        answered = {m["tool_call_id"] for m in settled}
        for call_id in database.dangling_tool_call_ids(working_memory):
            if call_id not in answered:
                settled.append({"role": "tool", "tool_call_id": call_id, "content": "Not run: the turn ended before this tool could run."})
        if settled:
            database.append_messages(session_id, settled)
        return working_memory + settled

    def _loop(
        self, session: dict[str, Any], turn: TurnState, messages: list[dict[str, Any]], new_messages: list[dict[str, Any]],
        relief: "context.Relief | None" = None,
    ) -> Iterator[TurnEvent]:
        """Request → tool rounds → reply. `new_messages` is what this turn appends to working memory."""
        session_id = turn.session_id
        tool_definitions = self.tools.definitions()
        turn_id = turn.turn_id
        started = time.perf_counter()
        books = _Books(model=self.config.main_model)
        announced_thinking = False
        paused: Paused | None = None
        ended: Ended | None = None
        rewrites = 0
        if relief is not None and relief.happened:
            books.add_relief(relief)
            yield TurnEvent("context_relieved", {"cleared": relief.cleared, "compacted": relief.compacted, "failed": relief.failed})

        def book(error: str | None = None) -> None:
            record_turn(TurnRecord(
                turn_id=turn_id, session_id=session_id, customer_id=session["customer_id"], model=books.model,
                prompt_tokens=books.usage.prompt_tokens, completion_tokens=books.usage.completion_tokens,
                reasoning_tokens=books.usage.reasoning_tokens,
                cache_hit_tokens=books.usage.cache_hit_tokens, cache_miss_tokens=books.usage.cache_miss_tokens,
                provider_calls=books.provider_calls, tool_rounds=turn.tool_rounds,
                tools_called=books.tools_called, skills_loaded=books.skills_loaded,
                hook_outcomes=books.hook_outcomes, cache_hits=books.cache_hits,
                subagent_calls=books.subagent_calls, subagent_prompt_tokens=books.subagent_prompt_tokens,
                subagent_completion_tokens=books.subagent_completion_tokens,
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
                # Text is held back until the Stop hooks have approved it: a rejected draft is
                # rewritten, and the customer never sees a word of it.
                held: list[TurnEvent] = []
                for event in self.provider.complete(request):
                    if isinstance(event, TextDelta):
                        held.append(TurnEvent("text_delta", {"text": event.text}))
                    elif isinstance(event, ReasoningDelta) and not announced_thinking:
                        announced_thinking = True
                        yield TurnEvent("thinking", {})
                    elif isinstance(event, Completed):
                        completion = event.completion
                if completion is None:
                    raise RuntimeError("provider stream ended without a completion")
                books.usage = books.usage + completion.usage
                books.model = completion.model or books.model
                if completion.usage.prompt_tokens:
                    database.set_last_prompt_tokens(session_id, completion.usage.prompt_tokens)

                if completion.tool_calls and asked_for_text:
                    # The model ignored tool_choice="none". Stop here rather than loop on denials.
                    books.outcome("hard_stop")
                    completion = Completion(
                        content=completion.content or HARD_STOP_REPLY,
                        reasoning_content=completion.reasoning_content,
                        finish_reason="stop", usage=completion.usage, model=completion.model,
                    )
                    held = [TurnEvent("text_delta", {"text": completion.content})]

                if not completion.tool_calls:
                    decision = self.hooks.run_stop(StopContext(turn=turn, reply=completion.content, attempt=rewrites))
                    if isinstance(decision.outcome, Deny):
                        books.outcome("stop_denied")
                        yield TurnEvent("hook_blocked", {"call_id": "", "tool": "reply", "hook": decision.hook})
                        if rewrites < MAX_REWRITES:
                            # Send the draft back with the feedback; neither enters working memory.
                            rewrites += 1
                            messages.append(completion.to_message())
                            messages.append({"role": "user", "content": f"[Stop hook {decision.hook}] {decision.outcome.feedback}"})
                            continue
                        books.outcome("stop_gave_up")
                        completion = Completion(
                            content=SAFE_REPLY, reasoning_content=completion.reasoning_content,
                            finish_reason="stop", usage=completion.usage, model=completion.model,
                        )
                        held = [TurnEvent("text_delta", {"text": SAFE_REPLY})]
                    yield from held

                assistant = completion.to_message()
                messages.append(assistant)
                new_messages.append(assistant)
                if not completion.tool_calls:
                    break

                turn.tool_rounds += 1
                for call in completion.tool_calls:
                    if paused is not None or ended is not None:
                        # The turn is over to the customer; nothing else in this round runs.
                        why = "paused for the customer's confirmation" if paused else "ended with a question for the customer"
                        skipped = _tool_message(call, f"Not run: the turn {why}.")
                        messages.append(skipped)
                        new_messages.append(skipped)
                        continue
                    outcome = yield from self._run_tool(turn, call, books)
                    if isinstance(outcome, Paused):
                        paused = outcome  # its tool result arrives when the customer answers
                        continue
                    if isinstance(outcome, Ended):
                        ended = outcome
                        messages.append(outcome.message)
                        new_messages.append(outcome.message)
                        continue
                    messages.append(outcome)
                    new_messages.append(outcome)
                if paused is not None or ended is not None:
                    break
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
        if paused:
            # When the model asked the customer in its own words alongside the tool call, use those —
            # after the same checks as any reply; if they fail, the harness's own proposal stands in.
            reply = completion.content.strip() or paused.reply
            if reply != paused.reply:
                decision = self.hooks.run_stop(StopContext(turn=turn, reply=reply, attempt=0))
                if isinstance(decision.outcome, Deny):
                    books.outcome("stop_denied")
                    yield TurnEvent("hook_blocked", {"call_id": "", "tool": "reply", "hook": decision.hook})
                    reply = paused.reply
        elif ended:
            reply = ended.end.reply
        else:
            reply = completion.content
        book()
        yield TurnEvent("done", {
            "turn_id": turn_id,
            "session_id": session_id,
            "reply": reply,
            "usage": asdict(books.usage),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "tool_rounds": turn.tool_rounds,
            "sources": turn.sources,
            "pending_handoff": paused.data if paused else None,
            "ask_customer": ended.end.data if ended else None,
        })

    # ------------------------------------------------------------------
    def _run_tool(self, turn: TurnState, call: ToolCall, books: _Books) -> Generator[TurnEvent, None, "dict[str, Any] | Paused | Ended"]:
        """Dispatch one tool call through the hooks, yielding events as they happen.

        Returns the tool message to append — or a `Paused` marker when a hook stopped the
        turn to ask the customer (the tool result arrives with their answer), or an `Ended`
        marker when the tool itself ended the turn with a question (its result is included).
        """
        yield TurnEvent("tool_call", {"call_id": call.id, "name": call.name, "arguments": call.arguments})
        books.tools_called.append(call.name)

        tool = self.tools.get(call.name)
        if tool is None:
            return _tool_message(call, f"No tool named {call.name!r}. Available tools: {', '.join(self.tools.names())}.")

        parsed = self.tools.parse_arguments(tool, call.arguments)
        if isinstance(parsed, str):
            return _tool_message(call, parsed)

        ctx = ToolUseContext(turn=turn, tool=tool, call_id=call.id, arguments=parsed)
        decision = self.hooks.run_pre_tool_use(ctx)
        if isinstance(decision.outcome, Deny):
            # The feedback is for the model; the customer's client only learns which hook spoke.
            books.outcome("denied")
            yield TurnEvent("hook_blocked", {"call_id": call.id, "tool": call.name, "hook": decision.hook})
            return _tool_message(call, f"Blocked by {decision.hook}: {decision.outcome.feedback}")

        if isinstance(decision.outcome, Pause):
            books.outcome("paused")
            yield TurnEvent(decision.outcome.event, {"call_id": call.id, **decision.outcome.data})
            return Paused(reply=decision.outcome.reply, data=decision.outcome.data)

        if isinstance(decision.outcome, Replace):
            books.outcome("replaced")
            raw = decision.outcome.result
        else:
            books.outcome("allowed")
            raw = yield from self._call_streaming_progress(tool, turn, parsed)

        # A served (cached) result goes through PostToolUse too: source extraction must see it.
        result = self.hooks.run_post_tool_use(ctx, raw)
        if result is not raw:
            books.outcome("modified")
        cached = bool(result.meta.get("cached"))
        if cached:
            books.cache_hits += 1
        metering = result.meta.get("subagent")
        if isinstance(metering, SubagentMetering) and not cached:  # a served brief is not a new delegation
            books.add_subagent(metering)

        if skill := result.meta.get("skill"):
            books.skills_loaded.append(skill)
            yield TurnEvent("skill_loaded", {"call_id": call.id, "name": skill})
        elif isinstance(end := result.meta.get("end_turn"), EndTurn):
            books.outcome("asked_customer" if end.event == "ask_customer" else end.event)
            yield TurnEvent(end.event, {"call_id": call.id, **end.data})
            return Ended(message=_tool_message(call, result.content), end=end)
        else:
            yield TurnEvent("tool_result", {
                "call_id": call.id, "name": call.name, "chars": len(result.content),
                "cached": cached, "is_error": result.is_error,
            })
        return _tool_message(call, result.content)

    def _call_streaming_progress(self, tool, turn: TurnState, parsed: dict[str, Any]) -> Generator[TurnEvent, None, ToolResult]:
        """Run the tool on a worker thread and yield the progress it reports while it runs.

        A sub-agent reports each of its rounds through `ToolContext.emit`; running the tool
        off-thread lets those events reach the customer as they happen instead of in a burst
        when the tool returns.
        """
        progress: queue.Queue[TurnEvent | None] = queue.Queue()
        outcome: dict[str, Any] = {}
        tool_ctx = ToolContext(
            turn.session_id, turn.customer_id, emit=lambda name, data: progress.put(TurnEvent(name, data)), turn_id=turn.turn_id,
        )

        def work() -> None:
            try:
                outcome["result"] = self.tools.call(tool, tool_ctx, parsed)
            except BaseException as exc:  # noqa: BLE001 — re-raised on the main thread below
                outcome["error"] = exc
            finally:
                progress.put(None)

        threading.Thread(target=work, name=f"tool:{tool.name}", daemon=True).start()
        while (event := progress.get()) is not None:
            yield event
        if "error" in outcome:
            raise outcome["error"]
        return outcome["result"]

    # ------------------------------------------------------------------
    def _bind_session(self, session_id: str, customer_id: str | None) -> dict[str, Any]:
        """Return the session, starting it on first contact; refuse a customer switch."""
        session = database.load_session(session_id)
        if session is None:
            return self._start_session(session_id, customer_id)
        if session["ended_at"]:
            raise SessionEnded(session_id)
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
            memories=database.active_memories(customer_id, limit=self.config.memory_limit) if profile else [],
        )
        block = "\n\n".join(self.hooks.run_session_start(ctx))
        return database.create_session(session_id, ctx.customer_id, block)


def _tool_message(call: ToolCall, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call.id, "content": content}


def _profile_hook(ctx: SessionStartContext) -> str:
    return prompt.customer_block(ctx.profile, ctx.product_usage, ctx.memories)
