"""
The Decider seam.

The Decider is the fast typed model the harness asks yes/no questions about a
Turn — "does this call for the payments skill?" — and it answers every question
in one request with a probability each. Nothing it returns reaches a customer.

Two adapters: `TypeSafeDecider` over the vendor's HTTP API, exercised here
against a mock transport so the suite stays offline, and `ScriptedDecider`, the
fake the rest of the suite will use. Every failure — a timeout, a rate limit, a
malformed answer, a missing key — comes back as "no answer" with a reason, so a
turn can always fall back to fetching its own Skill.
"""

import httpx
import pytest

from app.harness.core import HarnessConfig
from app.harness.decider import (
    MAX_LONGEST_CHARS,
    Answers,
    NullDecider,
    ScriptedDecider,
    TypeSafeDecider,
    YesNo,
    build_decider,
)

pytestmark = pytest.mark.unit

QUESTIONS = {
    "payments": YesNo("Does this turn call for the payments skill? Online card payments, wallets, Checkout."),
    "billing": YesNo("Does this turn call for the billing skill? Subscriptions, metered usage, invoices."),
    "terminal": YesNo("Does this turn call for the terminal skill? Card readers, in-person payments."),
}
STATE = {"customer_message": "What does Checkout cost?", "profile": {"business_model": "Direct sales"}, "loaded_skills": []}


class _RecordingClient(httpx.Client):
    """An httpx client that keeps the keyword arguments of the last POST, so the test can see the timeout applied."""

    last_post: dict | None = None

    def post(self, *args, **kwargs):  # type: ignore[override]
        self.last_post = kwargs
        return super().post(*args, **kwargs)


def _decider(handler, *, timeout: float = 0.7, model: str = "jev-latest") -> tuple[TypeSafeDecider, list[httpx.Request]]:
    """A TypeSafeDecider whose transport is `handler`; returns it with the list of requests it received."""
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = _RecordingClient(transport=httpx.MockTransport(recording))
    decider = TypeSafeDecider(client=client, url="https://api.typesafe.ai/v1/systemone", api_key="apikey_test", model=model, timeout=timeout)
    return decider, seen


def _answers(**probabilities: float) -> httpx.Response:
    body = {
        "model": "jev-1.13.0",
        "answers": {name: {"type": "noul", "noul": p} for name, p in probabilities.items()},
        "usage": {"input_tokens": 420, "output_tokens": 12},
    }
    return httpx.Response(200, json=body)


# =========================================================================
# One request, every question
# =========================================================================
def test_one_request_carries_every_question_in_the_documented_shape():
    decider, seen = _decider(lambda r: _answers(payments=0.93, billing=0.04, terminal=0.01))
    answers = decider.ask(STATE, QUESTIONS)

    assert len(seen) == 1, "every question travels in one request, not one request per question"
    request = seen[0]
    assert request.method == "POST" and str(request.url) == "https://api.typesafe.ai/v1/systemone"
    assert request.headers["authorization"].startswith("Bearer ")
    assert request.headers["content-type"] == "application/json"

    import json

    payload = json.loads(request.content)
    assert payload["model"] == "jev-latest", "the model is always sent; the HTTP API has no default"
    assert payload["state"] == STATE
    assert set(payload["questions"]) == set(QUESTIONS)
    assert payload["questions"]["payments"] == {"type": "noul", "instructions": QUESTIONS["payments"].instructions}
    assert answers.answered


def test_answers_come_back_keyed_by_question_id_with_the_time_it_took():
    decider, _ = _decider(lambda r: _answers(payments=0.93, billing=0.04, terminal=0.01))
    answers = decider.ask(STATE, QUESTIONS)

    assert answers.probabilities == {"payments": 0.93, "billing": 0.04, "terminal": 0.01}
    assert answers.skipped is None and answers.answered
    assert answers.elapsed_ms >= 0


# =========================================================================
# Every failure is "no answer" with a reason — never an exception
# =========================================================================
def test_a_rate_limit_or_an_overload_is_skipped_and_never_retried():
    for status, reason in ((429, "rate_limited"), (529, "overloaded")):
        decider, seen = _decider(lambda r, s=status: httpx.Response(s, json={"error": "nope"}, headers={"Retry-After": "2"}))
        answers = decider.ask(STATE, QUESTIONS)
        assert answers.skipped == reason and not answers.answered
        assert answers.probabilities == {}
        assert len(seen) == 1, "no retries: a retry would cost more latency than the answer is worth"


def test_every_transport_and_protocol_failure_names_its_reason():
    def raising(exc):
        def handler(request):
            raise exc

        return handler

    cases = [
        (raising(httpx.TimeoutException("too slow")), "timeout"),
        (raising(httpx.ConnectError("no route")), "transport"),
        (lambda r: httpx.Response(401, json={"error": "bad key"}), "unauthorized"),
        (lambda r: httpx.Response(422, json={"error": "bad field"}), "invalid_request"),
        (lambda r: httpx.Response(500, text="boom"), "http_500"),
    ]
    for handler, reason in cases:
        decider, _ = _decider(handler)
        answers = decider.ask(STATE, QUESTIONS)
        assert answers.skipped == reason, reason
        assert not answers.answered and answers.probabilities == {}


def test_an_answer_that_does_not_match_the_contract_is_skipped():
    bodies = [
        {"model": "jev-1.13.0"},  # no answers at all
        {"answers": {"payments": {"type": "noul", "noul": 0.9}}},  # an unanswered question
        {"answers": {n: {"type": "noul", "noul": "high"} for n in QUESTIONS}},  # not a number
        {"answers": {n: {"type": "noul", "noul": 1.4} for n in QUESTIONS}},  # outside 0–1
        {"answers": {n: {"type": "choice", "choice": "yes"} for n in QUESTIONS}},  # the wrong question type
    ]
    for body in bodies:
        decider, _ = _decider(lambda r, b=body: httpx.Response(200, json=b))
        answers = decider.ask(STATE, QUESTIONS)
        assert answers.skipped == "malformed", body
        assert answers.probabilities == {}, "a partial answer is no answer: under-priming is safe, mis-priming is not"

    decider, _ = _decider(lambda r: httpx.Response(200, text="not json at all"))
    assert decider.ask(STATE, QUESTIONS).skipped == "malformed"


def test_a_request_that_would_exceed_the_model_s_limits_is_skipped_before_it_is_sent():
    decider, seen = _decider(lambda r: _answers(payments=0.9, billing=0.1, terminal=0.1))
    huge = {"customer_message": "x" * (MAX_LONGEST_CHARS + 1)}
    answers = decider.ask(huge, QUESTIONS)

    assert answers.skipped == "state_too_large"
    assert seen == [], "the limit is checked here because the vendor does not document what it does on overflow"


def test_asking_nothing_is_skipped_before_it_is_sent():
    decider, seen = _decider(lambda r: _answers())
    answers = decider.ask(STATE, {})
    assert answers.skipped == "no_questions" and seen == []


def test_the_timeout_is_applied_to_the_request():
    decider, _ = _decider(lambda r: _answers(payments=0.9, billing=0.1, terminal=0.1), timeout=0.7)
    decider.ask(STATE, QUESTIONS)
    assert decider.client.last_post["timeout"] == 0.7  # type: ignore[union-attr]


# =========================================================================
# The fake the rest of the suite uses, and the no-op
# =========================================================================
def test_every_adapter_can_be_closed_so_the_harness_need_not_know_which_it_has():
    decider, _ = _decider(lambda r: _answers(payments=0.9, billing=0.1, terminal=0.1))
    decider.ask(STATE, QUESTIONS)
    decider.close()
    assert decider.client.is_closed, "the real adapter owns a connection pool and must release it"
    ScriptedDecider().close()  # no-op, but present: the Protocol asks for it
    NullDecider("priming_off").close()


def test_the_scripted_decider_plays_answers_in_order_and_records_what_it_was_asked():
    decider = ScriptedDecider().script(
        {"payments": 0.9, "billing": 0.1},
        Answers(skipped="rate_limited"),
        RuntimeError("the decider fell over"),
    )

    first = decider.ask(STATE, QUESTIONS)
    assert first.probabilities == {"payments": 0.9, "billing": 0.1} and first.answered

    second = decider.ask({"customer_message": "and Terminal?"}, {"terminal": QUESTIONS["terminal"]})
    assert second.skipped == "rate_limited", "a whole Answers can be scripted, so a test can pin any skip reason"

    third = decider.ask(STATE, QUESTIONS)
    assert third.skipped == "transport", "a scripted exception is the adapter's failure path, not a test crash"

    assert [state for state, _ in decider.requests] == [STATE, {"customer_message": "and Terminal?"}, STATE]
    assert [sorted(q) for _, q in decider.requests] == [sorted(QUESTIONS), ["terminal"], sorted(QUESTIONS)],         "every request is kept with the questions it carried, which is how later tickets assert what was asked"

    with pytest.raises(AssertionError):
        decider.ask(STATE, QUESTIONS)  # the script ran out: fail loudly, as ScriptedProvider does


def test_a_state_the_harness_cannot_serialise_is_still_an_answer():
    decider, seen = _decider(lambda r: _answers(payments=0.9, billing=0.1, terminal=0.1))
    answers = decider.ask({"customer_message": object()}, QUESTIONS)
    assert answers.skipped == "bad_state" and seen == [], "the contract is absolute: a turn never sees an exception"


def test_the_null_decider_reports_why_it_answered_nothing():
    answers = NullDecider("priming_off").ask(STATE, QUESTIONS)
    assert not answers.answered and answers.skipped == "priming_off" and answers.probabilities == {}


def test_build_decider_needs_both_the_switch_and_the_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    off = build_decider(HarnessConfig(priming=False))
    assert isinstance(off, NullDecider) and off.ask(STATE, QUESTIONS).skipped == "priming_off"

    on = build_decider(HarnessConfig(priming=True))
    assert isinstance(on, TypeSafeDecider) and on.model == "jev-latest" and on.timeout == 0.7
    on.close()

    monkeypatch.delenv("TYPESAFE_API_KEY")
    keyless = build_decider(HarnessConfig(priming=True))
    assert isinstance(keyless, NullDecider) and keyless.ask(STATE, QUESTIONS).skipped == "no_key"


# =========================================================================
# Configuration
# =========================================================================
def test_the_priming_settings_come_from_the_configuration_object(monkeypatch):
    default = HarnessConfig()
    assert default.priming is False, "off until #16 wires it into the turn"
    assert (default.decider_model, default.decider_timeout_seconds) == ("jev-latest", 0.7)
    assert (default.priming_threshold, default.priming_margin) == (0.55, 0.15)

    monkeypatch.setenv("HARNESS_PRIMING", "true")
    monkeypatch.setenv("HARNESS_DECIDER_MODEL", "jev-preview")
    monkeypatch.setenv("HARNESS_DECIDER_TIMEOUT_SECONDS", "0.4")
    monkeypatch.setenv("HARNESS_PRIMING_THRESHOLD", "0.6")
    monkeypatch.setenv("HARNESS_PRIMING_MARGIN", "0.2")
    config = HarnessConfig.from_env()
    assert config.priming is True and config.decider_model == "jev-preview"
    assert config.decider_timeout_seconds == 0.4
    assert (config.priming_threshold, config.priming_margin) == (0.6, 0.2)

    for value in ("0", "no", "off", "false", ""):
        monkeypatch.setenv("HARNESS_PRIMING", value)
        assert HarnessConfig.from_env().priming is False, value


def test_a_threshold_outside_its_range_is_refused():
    for bad in ({"priming_threshold": 0.0}, {"priming_threshold": 1.5}, {"priming_margin": -0.1}, {"priming_margin": 1.0}):
        with pytest.raises(ValueError):
            HarnessConfig(**bad)
    with pytest.raises(ValueError):
        HarnessConfig(decider_timeout_seconds=0)
