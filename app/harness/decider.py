"""
The Decider seam — a fast typed model that answers the harness's yes/no questions.

The Decider is asked things a model was already judging, in a form that needs no
prose: "does this turn call for the payments skill?" Every question travels in
one request and comes back as a probability, in roughly the time a single
DeepSeek round trip spends on its first token. Nothing the Decider returns ever
reaches a Customer — it only decides what context the main model starts with
(Priming), and it can never narrow what that model may do.

It cannot go through the `Provider` seam: the vendor's API is not
OpenAI-compatible, has no streaming, no tools and no text output, so a
`CompletionRequest` would be a lie for both adapters. Hence a second, smaller
seam with the same two-adapter shape: `TypeSafeDecider` over the real API and
`ScriptedDecider` for the suite, which stays offline.

**No vendor SDK.** Its documented defaults are exactly what must not happen on
this path — a 10 s timeout and a retry policy with a 30 s ceiling — and the one
call it would wrap is a single POST. `httpx`, already a dependency, gives the
explicit timeout and the single attempt directly, with nothing to override.

**Every failure is an answer.** No call to `ask` raises: a timeout, a rate
limit, an overload, a malformed body, a state too large to send — each comes
back as `Answers(skipped=<reason>)`. A turn that gets no answer simply behaves
as it always did and fetches its own Skill, so Priming's worst case is the time
it spent asking, never a worse turn. Construction is the one place that can
fail, and `build_decider` is the entry point that turns a missing key into the
same "no answer" rather than an exception.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.harness.context import CHARS_PER_TOKEN

log = logging.getLogger(__name__)

DEFAULT_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
API_KEY_ENV = "TYPESAFE_API_KEY"
BASE_URL_ENV = "TYPESAFE_BASE_URL"

# The vendor states its limits in tokens — 64k for the state plus every question, 32k for the state
# plus the longest single question — and does not document what it does on overflow, so the adapter
# refuses instead of sending. Sized in characters with the same characters/4 estimate the context
# tiers use (ADR 0006), imported rather than repeated.
MAX_TOTAL_CHARS = 64_000 * CHARS_PER_TOKEN
MAX_LONGEST_CHARS = 32_000 * CHARS_PER_TOKEN

# Why no answer came back. Recorded per turn, so a quiet Decider is visible in metrics.
SKIP_PRIMING_OFF = "priming_off"
SKIP_NO_KEY = "no_key"
SKIP_NO_QUESTIONS = "no_questions"
SKIP_BAD_STATE = "bad_state"
SKIP_TOO_LARGE = "state_too_large"
SKIP_TIMEOUT = "timeout"
SKIP_TRANSPORT = "transport"
SKIP_MALFORMED = "malformed"
_STATUS_REASONS = {401: "unauthorized", 403: "unauthorized", 422: "invalid_request", 429: "rate_limited", 529: "overloaded"}


@dataclass(frozen=True)
class YesNo:
    """A yes/no question about the state. The answer is the probability that the answer is yes."""

    instructions: str

    def payload(self) -> dict[str, Any]:
        return {"type": "noul", "instructions": self.instructions}


@dataclass(frozen=True)
class Answers:
    """What one call returned: a probability per question id, or the reason nothing came back."""

    probabilities: dict[str, float] = field(default_factory=dict)
    skipped: str | None = None
    elapsed_ms: int = 0

    @property
    def answered(self) -> bool:
        return self.skipped is None


class Decider(Protocol):
    def ask(self, state: dict[str, Any], questions: dict[str, YesNo]) -> Answers: ...

    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# The real adapter
# ---------------------------------------------------------------------------
@dataclass
class TypeSafeDecider:
    """One POST carrying every question. No retries: a retry costs more latency than the answer is worth."""

    client: httpx.Client
    url: str
    api_key: str
    model: str
    timeout: float

    @classmethod
    def from_env(cls, *, model: str = DEFAULT_MODEL, timeout: float = 0.7) -> "TypeSafeDecider":
        return cls(
            client=httpx.Client(),  # httpx does not retry unless asked; it must not be asked
            url=os.environ.get(BASE_URL_ENV, DEFAULT_URL),
            api_key=os.environ[API_KEY_ENV],
            model=model,
            timeout=timeout,
        )

    def ask(self, state: dict[str, Any], questions: dict[str, YesNo]) -> Answers:
        if not questions:
            return Answers(skipped=SKIP_NO_QUESTIONS)
        asked = {name: q.payload() for name, q in questions.items()}
        payload = {"model": self.model, "state": state, "questions": asked}
        try:
            encoded = json.dumps(payload, ensure_ascii=False)
            state_chars = len(json.dumps(state, ensure_ascii=False))
        except TypeError:  # a state the harness built wrongly is still an answer, never an exception in a turn
            log.warning("decider state is not JSON-serialisable; the turn goes on without priming")
            return Answers(skipped=SKIP_BAD_STATE)
        longest = max(len(json.dumps(one, ensure_ascii=False)) for one in asked.values())
        if len(encoded) > MAX_TOTAL_CHARS or state_chars + longest > MAX_LONGEST_CHARS:
            return Answers(skipped=SKIP_TOO_LARGE)

        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        try:
            response = self.client.post(
                self.url,
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except httpx.TimeoutException:
            return Answers(skipped=SKIP_TIMEOUT, elapsed_ms=elapsed())
        except httpx.HTTPError as exc:  # connect, read, protocol — one attempt, then give up
            log.warning("decider transport failure: %s", exc)
            return Answers(skipped=SKIP_TRANSPORT, elapsed_ms=elapsed())

        if response.status_code != 200:
            return Answers(skipped=_STATUS_REASONS.get(response.status_code, f"http_{response.status_code}"), elapsed_ms=elapsed())
        probabilities = _probabilities(response, questions)
        if probabilities is None:
            return Answers(skipped=SKIP_MALFORMED, elapsed_ms=elapsed())
        return Answers(probabilities=probabilities, elapsed_ms=elapsed())

    def close(self) -> None:
        """Release the HTTP connection pool; the harness closes its Decider as it closes its index."""
        self.client.close()


def _probabilities(response: httpx.Response, questions: dict[str, YesNo]) -> dict[str, float] | None:
    """Every question's probability, or None if the body does not answer all of them in the documented shape.

    All or nothing on purpose: a partial answer would silently under-prime, and a misread one would
    prime the wrong Skill. Under-priming costs a round; mis-priming costs the customer.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    answers = body.get("answers") if isinstance(body, dict) else None
    if not isinstance(answers, dict):
        return None
    out: dict[str, float] = {}
    for name in questions:
        answer = answers.get(name)
        if not isinstance(answer, dict) or answer.get("type") != "noul":
            return None
        value = answer.get("noul")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
            return None
        out[name] = float(value)
    return out


# ---------------------------------------------------------------------------
# The fake, and the no-op
# ---------------------------------------------------------------------------
ScriptItem = dict[str, float] | Answers | BaseException


class ScriptedDecider:
    """Plays queued answers and records every request — the Provider seam's ScriptedProvider, for decisions.

    Queue a mapping of probabilities, or a whole `Answers` to script any skip the real adapter can
    report (`Answers(skipped="timeout")`, `"rate_limited"`, …). An exception stands for the adapter
    falling over, which a caller sees as a transport failure.
    """

    def __init__(self) -> None:
        self.requests: list[tuple[dict[str, Any], dict[str, YesNo]]] = []
        self._script: list[ScriptItem] = []

    def script(self, *items: ScriptItem) -> "ScriptedDecider":
        self._script.extend(items)
        return self

    def ask(self, state: dict[str, Any], questions: dict[str, YesNo]) -> Answers:
        self.requests.append((state, questions))
        assert self._script, "ScriptedDecider: script exhausted — the harness asked for one more decision than the test scripted"
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            return Answers(skipped=SKIP_TRANSPORT)
        if isinstance(item, Answers):
            return item
        return Answers(probabilities=dict(item))

    def close(self) -> None:
        """Nothing to release; the Protocol asks so the harness never needs to know which adapter it has."""


@dataclass(frozen=True)
class NullDecider:
    """No Decider is configured; every call says why. Priming then simply never fires."""

    reason: str

    def ask(self, state: dict[str, Any], questions: dict[str, YesNo]) -> Answers:
        return Answers(skipped=self.reason)

    def close(self) -> None:
        """Nothing to release."""


def build_decider(config: Any) -> Decider:
    """The Decider a harness should use: the real one only when Priming is on and a key is present."""
    if not config.priming:
        return NullDecider(SKIP_PRIMING_OFF)
    if not os.environ.get(API_KEY_ENV):
        log.warning("priming is on but TYPESAFE_API_KEY is not set; turns will fetch their own skills")
        return NullDecider(SKIP_NO_KEY)
    return TypeSafeDecider.from_env(model=config.decider_model, timeout=config.decider_timeout_seconds)
