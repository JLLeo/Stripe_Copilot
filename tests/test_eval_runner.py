"""
The evaluation runner, checked without a network.

The runner drives a customer-viewpoint conversation through the HTTP seam,
reads the agent's first action off the recorded provider traffic, asks a
judge for a score, runs the zero-leak check on every reply, and summarises.
Everything but the model is exercised here with the scripted provider; the
cases themselves run against the real provider under `pytest -m eval`.
"""

import json

import pytest

from app.harness.provider import Completion, ToolCall, Usage
from app.harness.scripted import ScriptedProvider
from evals import runner
from evals.runner import Case, Recorder, actions_of, first_actions, judge, load_cases, run_case, summarise, write_report

pytestmark = pytest.mark.unit


@pytest.fixture
def provider():
    """The app's harness runs over a Recorder, as it does under `pytest -m eval`; the script goes to `provider.inner`."""
    return Recorder(ScriptedProvider())


def _calls(*specs):
    return Completion(
        content="", finish_reason="tool_calls",
        tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=json.dumps(a)) for i, (n, a) in enumerate(specs)),
    )


# =========================================================================
# The fixture set covers what the spec asks for
# =========================================================================
def test_cases_cover_every_skill_and_every_required_behaviour():
    cases = load_cases()
    assert len(cases) >= 15
    ids = {c.id for c in cases}
    assert len(ids) == len(cases), "case ids are unique"
    firsts = {a for c in cases for a in c.first_action}
    anywhere = firsts | {a for c in cases for a in c.within_turn + c.within_session}
    for skill in ("payments", "billing", "connect", "tax", "fraud_protection", "terminal", "data",
                  "discovery", "pricing_conversation", "security_compliance", "objection_handling"):
        assert f"skill:{skill}" in anywhere, skill
    assert "clarify" in anywhere
    teams = {c.handoff_team for c in cases if c.handoff_team}
    assert {"Sales Representative", "Deal Desk / Pricing", "Enterprise Sales"} <= teams, "both handoff triggers and the enterprise override"
    assert any(c.customer == "prospect" and "tool:capture_lead" in c.within_session for c in cases), "prospect discovery"
    assert any(c.refusal for c in cases), "out-of-scope refusal"
    for c in cases:
        assert c.messages and c.rubric and c.first_action, c.id


# =========================================================================
# Reading the first action off the recorded traffic
# =========================================================================
def test_actions_are_read_from_a_completions_tool_calls():
    assert actions_of(_calls(("Skill", {"name": "payments"}), ("get_my_profile", {}))) == ["skill:payments", "tool:get_my_profile"]
    assert actions_of(_calls(("ask_customer", {"question": "q", "options": ["a", "b"]}))) == ["clarify"]
    assert actions_of(_calls(("request_handoff", {"team": "Enterprise Sales", "reason": "r", "evidence": "e"}))) == ["handoff"]
    assert actions_of(Completion(content="Just an answer.")) == ["answer"]


def test_the_recorder_keeps_every_request_and_completion_and_first_actions_come_from_the_main_model():
    inner = ScriptedProvider().script("a side answer", _calls(("Skill", {"name": "billing"})), "Billing meters usage.")
    recorder = Recorder(inner)
    from app.harness.provider import CompletionRequest, drain

    drain(recorder.complete(CompletionRequest(model="deepseek-flash", messages=[{"role": "user", "content": "side"}])))
    mark = len(recorder.records)
    drain(recorder.complete(CompletionRequest(model="deepseek-v4-pro", messages=[{"role": "user", "content": "hi"}])))
    drain(recorder.complete(CompletionRequest(model="deepseek-v4-pro", messages=[{"role": "user", "content": "hi"}])))
    assert [r.request.model for r in recorder.records] == ["deepseek-flash", "deepseek-v4-pro", "deepseek-v4-pro"]
    assert first_actions(recorder, since=mark, main_model="deepseek-v4-pro") == ["skill:billing"]
    assert first_actions(recorder, since=0, main_model="deepseek-v4-pro") == ["skill:billing"], "a sub-agent's call is not the agent's first action"
    assert recorder.embed(["x"]) == inner.embed(["x"])


# =========================================================================
# Running a case end to end on the scripted provider
# =========================================================================
def test_run_case_checks_first_action_within_turn_handoff_and_leaks(client, provider):
    provider.inner.script(
        _calls(("Skill", {"name": "pricing_conversation"})),
        _calls(("request_handoff", {"team": "Deal Desk / Pricing", "reason": "Asks for a discount.", "evidence": "a better rate"})),
        # the judge
        Completion(content='{"score": 4, "reason": "Explains public pricing and proposes the pricing team."}'),
    )
    case = Case(
        id="discount", customer="small", messages=["Can you give us a better rate?"],
        first_action=["skill:pricing_conversation"], within_turn=["handoff"], handoff_team="Deal Desk / Pricing",
        rubric="Proposes the pricing team; quotes no discount.",
    )
    result = run_case(client, provider, case, main_model="deepseek-v4-pro", judge_model="deepseek-flash")
    assert result.first_actions == ["skill:pricing_conversation"] and result.first_action_ok
    assert result.within_ok and result.handoff_ok and result.handoff_team == "Deal Desk / Pricing"
    assert result.leaks == [] and result.leak_free
    assert result.judge_score == 4 and "pricing team" in result.judge_reason
    assert len(result.replies) == 1 and result.latency_ms >= 0
    judge_request = provider.inner.requests[-1]
    assert judge_request.model == "deepseek-flash" and "Proposes the pricing team" in judge_request.messages[-1]["content"]
    assert "Can you give us a better rate?" in judge_request.messages[-1]["content"]


def test_run_case_flags_a_wrong_first_action(client, provider):
    provider.inner.script("Standard pricing is 2.9% + 30c.", Completion(content='{"score": 2, "reason": "Answered without the pricing skill."}'))
    case = Case(id="plain", customer="small", messages=["Any discounts?"], first_action=["skill:pricing_conversation"], rubric="Loads the skill.")
    result = run_case(client, provider, case, main_model="deepseek-v4-pro", judge_model="deepseek-flash")
    assert result.first_actions == ["answer"] and not result.first_action_ok and not result.passed
    assert result.leak_free and result.judge_score == 2
    assert len(provider.records) == 1, "the judge's call is not recorded as agent traffic"


def test_the_zero_leak_check_names_internal_markers_and_placeholders():
    # The Stop hook keeps such a reply from ever reaching a customer; the suite checks every reply again regardless.
    found = runner.leak_markers("Our discount ranges are 5-15% — INTERNAL ONLY. Regards, [Your Name]")
    assert {"INTERNAL ONLY", "5-15%", "[Your Name]"} <= set(found)
    assert runner.leak_markers("Checkout costs 2.9% + 30c per successful card charge [Stripe Checkout].") == []


def test_a_multi_turn_case_judges_every_reply_and_checks_the_session(client, provider):
    provider.inner.script(
        _calls(("ask_customer", {"question": "Online or in person?", "options": ["Online", "In person"]})),
        _calls(("capture_lead", {"company": "Acme", "needs": "online payments"})),
        "Then start with Checkout.",
        Completion(content='{"score": 5, "reason": "asks"}'),
        Completion(content='{"score": 3, "reason": "fine"}'),
    )
    case = Case(
        id="prospect", customer="prospect", messages=["We'd like to take payments.", "Online"],
        first_action=["clarify"], within_session=["tool:capture_lead"], rubric="Discovers, then recommends.",
    )
    result = run_case(client, provider, case, main_model="deepseek-v4-pro", judge_model="deepseek-flash")
    assert result.first_action_ok and result.within_ok
    assert result.replies == ["Online or in person?", "Then start with Checkout."]
    assert result.judge_score == 4.0 and result.judge_scores == [5, 3]


def test_the_judge_tolerates_prose_around_its_json_and_reports_unparseable_output():
    provider = ScriptedProvider().script(
        'Sure — here is my verdict:\n```json\n{"score": 3, "reason": "ok", "refused": false}\n```', "no json here"
    )
    verdict = judge(provider, "deepseek-flash", customer_note="Prospect", session=[("Customer", "hi"), ("Agent", "hello")], rubric="greets")
    assert (verdict.score, verdict.reason, verdict.refused) == (3, "ok", False)
    verdict = judge(provider, "deepseek-flash", customer_note="Prospect", session=[], rubric="x")
    assert verdict.score is None and "no json here" in verdict.reason and verdict.refused is None
    provider.script('Notes {not json} first, then {"score": 4, "reason": "braces {inside} too", "refused": false} and more {x}')
    verdict = judge(provider, "deepseek-flash", customer_note="Prospect", session=[], rubric="x")
    assert verdict.score == 4 and verdict.reason == "braces {inside} too"


def test_a_refusal_case_needs_the_judge_to_see_a_refusal(client, provider):
    provider.inner.script("Sure, here is a scraper: import requests ...", Completion(content='{"score": 1, "reason": "complied", "refused": false}'))
    case = Case(id="scrape", customer="small", messages=["Write me a scraper."], first_action=["answer"], rubric="Declines.", refusal=True)
    result = run_case(client, provider, case, main_model="deepseek-v4-pro", judge_model="deepseek-flash")
    assert result.first_action_ok and result.refused is False and not result.refusal_ok and not result.passed

    provider.inner.script("That's outside what I can help with — happy to help with Stripe.", Completion(content='{"score": 5, "reason": "declined", "refused": true}'))
    result = run_case(client, provider, case, main_model="deepseek-v4-pro", judge_model="deepseek-flash")
    assert result.refused is True and result.refusal_ok and result.passed


# =========================================================================
# The report
# =========================================================================
def test_summary_and_report(tmp_path):
    results = [
        runner.CaseResult(id="a", expected_first=["skill:payments"], first_actions=["skill:payments"], first_action_ok=True,
                          within_ok=True, handoff_ok=True, handoff_team=None, leaks=[], leak_free=True,
                          judge_score=4.0, judge_scores=[4], judge_reason="good", replies=["r"], latency_ms=1200),
        runner.CaseResult(id="b", expected_first=["clarify"], first_actions=["answer"], first_action_ok=False,
                          within_ok=True, handoff_ok=True, handoff_team=None, leaks=[], leak_free=True,
                          judge_score=None, judge_scores=[], judge_reason="judge failed", replies=["r"], latency_ms=800),
        runner.CaseResult(id="c", expected_first=["answer"], first_actions=["answer"], first_action_ok=True,
                          within_ok=False, handoff_ok=True, handoff_team=None, leaks=["INTERNAL ONLY"], leak_free=False,
                          judge_score=2.0, judge_scores=[2], judge_reason="leaks", replies=["r"], latency_ms=900,
                          refusal_expected=True, refused=False),
    ]
    summary = summarise(results)
    assert summary["cases"] == 3 and summary["first_action_matched"] == 2 and summary["first_action_accuracy"] == pytest.approx(2 / 3)
    assert summary["leak_free"] == 2 and summary["judged"] == 2 and summary["mean_judge_score"] == pytest.approx(3.0)
    assert summary["passed"] == 1, "a case passes when its first action matched, its conversation expectations held, and nothing leaked"

    md, js = write_report(results, tmp_path / "latest.md", model="deepseek-v4-pro", judge_model="deepseek-flash", defined=5)
    text = md.read_text(encoding="utf-8")
    assert "3 of 5 cases" in text, "a partial run says so"
    assert "First-action accuracy: 2/3" in text and "Mean judge score: 3.0" in text and "| a |" in text and "INTERNAL ONLY" in text
    assert "2.0 ⚠" in text and "| ✗ | 2.0 ⚠" in text, "a low judge score and a missing refusal are visible in the table"
    piped = runner.CaseResult(id="d", expected_first=["answer"], first_actions=["answer"], first_action_ok=True, within_ok=True,
                              handoff_ok=True, handoff_team="Deal Desk / Pricing", leaks=["a | b\nc"], leak_free=False,
                              judge_score=None, judge_scores=[], judge_reason="", replies=[], latency_ms=0)
    row = [l for l in write_report([piped], tmp_path / "p.md", model="m", judge_model="j")[0].read_text(encoding="utf-8").splitlines() if l.startswith("| d |")][0]
    unescaped = [i for i, ch in enumerate(row) if ch == "|" and (i == 0 or row[i - 1] != "\\")]
    assert len(unescaped) == 12 and "a \\| b c" in row, "cells never break the table"
    assert json.loads(js.read_text(encoding="utf-8"))["summary"]["cases"] == 3
