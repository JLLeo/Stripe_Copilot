"""
The Golden Set runner, checked without a network.

The measurement instrument is itself tested: case loading and validation, the
two-layer scoring, how each arm's decision is read — the model arms off the
request a turn's first call would send, the Decider through the production
Priming code — the per-cell aggregation, and the report. The real models only
appear under `python -m evals.golden`.
"""

import json
from dataclasses import replace

import pytest

from app.harness.decider import Answers
from app.harness.provider import Completion, ToolCall
from app.harness.skills import ALREADY_IN_CONTEXT
from evals import golden
from evals.golden import (
    CELLS,
    Arm,
    Decision,
    GoldenCase,
    GoldenSetError,
    Labels,
    PriorTurn,
    SetScore,
    arms_for,
    decide,
    load_golden,
    percentile,
    run,
    stats,
    summarise,
    write_report,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def harness(client):
    """The app's harness over the test's scripted provider and Decider, on a fresh runtime database."""
    from app import main

    return main.app.state.harness


def _calls(*specs):
    return Completion(
        content="", finish_reason="tool_calls", reasoning_content="thinking it over",
        tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=json.dumps(a)) for i, (n, a) in enumerate(specs)),
    )


def _labels(*required, acceptable=()):
    return Labels(required=tuple(tuple(r.split("|")) for r in required), acceptable=tuple(acceptable))


def _case(**overrides) -> GoldenCase:
    base = dict(
        id="ss-cost", cell="single_intent_single_turn", split="dev", customer="seed:C013",
        message="What does Checkout cost per transaction?",
        skills=_labels("pricing_conversation", acceptable=("payments",)), tools=_labels("get_pricing"),
        first_action=("skill:pricing_conversation",),
    )
    base.update(overrides)
    return GoldenCase(**base)


MAIN = Arm("main-thinking", "deepseek-v4-pro", "enabled")
DECIDE = Arm(golden.DECIDER)


# =========================================================================
# The set itself
# =========================================================================
def test_the_golden_set_is_eighty_labelled_cases_in_four_even_cells(harness):
    cases = load_golden(skill_names=harness.skills, tool_names=harness.tools.names())
    assert len(cases) == 80
    for cell in CELLS:
        mine = [c for c in cases if c.cell == cell]
        assert len(mine) == 20, cell
        assert sum(c.split == "dev" for c in mine) == 10, f"{cell}: forty development cases, ten per cell"
    for split in ("dev", "test"):
        required = {s for c in cases if c.split == split for alternatives in c.skills.required for s in alternatives}
        assert required == set(harness.skills), f"every skill is required somewhere in the {split} split"
    multi_turn = [c for c in cases if c.cell.endswith("multi_turn")]
    assert all(c.working_memory for c in multi_turn) and not any(c.working_memory for c in cases if c.cell.endswith("single_turn"))
    assert any(not c.skills.required for c in multi_turn), "a follow-up in an area already loaded needs no new skill"


def test_a_malformed_case_file_names_every_problem_at_once(tmp_path, harness):
    (tmp_path / "single_intent_single_turn.yaml").write_text("""
- id: a
  split: train
  customer: somebody
  message: hi
  skills: {required: [payments, tax], acceptable: [payments, nonsense]}
  tools: {required: [Skill, get_my_profile, "search_knowledge|research", research]}
  first_action: [skill:connect, tool:ask_customer, waves]
  tool: {required: [get_pricing]}
- id: b
  split: dev
  customer: prospect
  message: and that?
  working_memory:
  - {customer: earlier, agent: reply, skills: [payments]}
  skills: {required: [discovery]}
  first_action: [skill:discovery]
""", encoding="utf-8")
    (tmp_path / "single_intent_multi_turn.yaml").write_text("""
- id: b
  split: test
  customer: small
  message: what about it?
  skills: {required: [], acceptable: [payments]}
  first_action: [answer, clarify]
- id: c
  split: dev
  customer: enterprise
  working_memory:
  - {customer: earlier, agent: reply, skills: [payments]}
  - {customer: later, agent: reply, skills: [tax], tools: [get_pricing]}
  message: and the fee?
  skills: {required: [payments]}
  first_action: [answer]
""", encoding="utf-8")
    (tmp_path / "misc.yaml").write_text("[]", encoding="utf-8")

    with pytest.raises(GoldenSetError) as caught:
        load_golden(tmp_path, skill_names=harness.skills, tool_names=harness.tools.names())
    report = str(caught.value)
    for expected in (
        "split must be one of", "customer must be", "unknown 'nonsense'", "'payments' is both required and acceptable",
        "unknown 'Skill'", "at most one skill", "'skill:connect' names a skill outside", "write 'clarify'",
        "'waves': use answer", "a single-turn case has no prior working_memory", "a multi-turn case needs a prior working_memory",
        "first action 'clarify' needs ask_customer", "'payments' is already in context", "duplicate id",
        "misc.yaml: not a cell", "unknown key 'tool'", "'research' is required twice",
        "'get_my_profile' is informed by no skill and never scored", "'customer', 'agent' and optionally 'skills', nothing else",
    ):
        assert expected in report, expected


# =========================================================================
# Two layers
# =========================================================================
def test_a_choice_inside_either_layer_never_costs_precision():
    labels = _labels("payments", "tax", acceptable=("billing",))
    assert labels.score(["payments", "tax", "billing"]) == SetScore(chosen=3, correct=3, required=2, found=2)
    assert labels.score(["payments", "tax", "billing"]).exact, "an acceptable extra is still an exact set"
    missed = labels.score(["payments", "billing"])
    assert (missed.found, missed.correct, missed.exact) == (1, 2, False), "a missing required skill costs recall only"
    stray = labels.score(["payments", "tax", "connect"])
    assert (stray.correct, stray.chosen, stray.exact) == (2, 3, False), "only a choice outside both layers costs precision"
    assert labels.score([]) == SetScore(chosen=0, correct=0, required=2, found=0)


def test_a_required_entry_may_name_alternatives():
    labels = _labels("search_knowledge|research")
    assert labels.score(["research"]).exact and labels.score(["search_knowledge"]).exact
    both = labels.score(["search_knowledge", "research"])
    assert both.found == 1 and both.correct == 2 and both.exact
    assert _labels().score([]).exact, "nothing required, nothing chosen: exact"


# =========================================================================
# The model arms
# =========================================================================
def test_a_model_arm_that_only_loads_skills_chooses_its_tools_once_the_bodies_are_in(harness, provider):
    provider.script(_calls(("Skill", {"name": "pricing_conversation"})), _calls(("get_pricing", {"product": "Checkout"})))
    d = decide(_case(), MAIN, harness=harness, decider=None)

    assert d.error is None
    assert d.skills == ["pricing_conversation"] and d.skill_score.exact
    assert d.tools == ["get_pricing"] and d.tool_score.exact and d.paired is False
    assert d.first_actions == ["skill:pricing_conversation"] and d.first_action_ok

    first, second = provider.requests
    assert (first.model, first.thinking) == ("deepseek-v4-pro", "enabled")
    assert first.tool_choice is None and [t["function"]["name"] for t in first.tools] == harness.tools.names()
    assert first.messages[-1] == {"role": "user", "content": "What does Checkout cost per transaction?"}
    assert second.messages[len(first.messages)]["reasoning_content"] == "thinking it over", "the response goes back as it came"
    assert second.messages[-1] == {"role": "tool", "tool_call_id": "c0", "content": harness.skills["pricing_conversation"].body}


def test_a_model_arm_that_pairs_a_skill_with_a_tool_is_read_from_its_first_response(harness, provider):
    provider.script(_calls(("Skill", {"name": "pricing_conversation"}), ("get_pricing", {"product": "Checkout"}), ("get_my_profile", {})))
    d = decide(_case(), MAIN, harness=harness, decider=None)
    assert d.tools == ["get_pricing", "get_my_profile"] and d.paired is True
    assert d.tool_score == SetScore(chosen=1, correct=1, required=1, found=1), "the profile read beside them is free"
    assert len(provider.requests) == 1, "the tools were chosen already; no second response"


def test_a_profile_read_beside_a_skill_load_is_not_the_tool_decision(harness, provider):
    from app import database

    provider.script(
        _calls(("Skill", {"name": "pricing_conversation"}), ("get_my_profile", {}), ("remember", {"kind": "plan", "fact": "x"})),
        _calls(("get_pricing", {"product": "Checkout"})),
    )
    d = decide(_case(), MAIN, harness=harness, decider=None)

    assert d.tools == ["get_my_profile", "remember", "get_pricing"] and d.paired is False
    assert d.tool_score.exact, "tools no skill informs are free; the decision is get_pricing, chosen with the body in hand"
    results = {m["tool_call_id"]: m["content"] for m in provider.requests[1].messages if m["role"] == "tool"}
    assert results["c0"] == harness.skills["pricing_conversation"].body
    assert "GreenCart" in results["c1"], "the profile read runs for real"
    assert results["c2"] == "Noted."
    count = database.get_connection().execute("SELECT COUNT(*) FROM customer_memory").fetchone()[0]
    assert count == 0, "a measurement never writes a fact a later case's Decider state would read"


def test_a_model_arm_that_answers_in_text_chooses_nothing(harness, provider):
    provider.script("Checkout costs 2.9% + 30c.")
    d = decide(_case(first_action=("skill:pricing_conversation",)), MAIN, harness=harness, decider=None)
    assert d.skills == [] and d.tools == [] and d.first_actions == ["answer"] and not d.first_action_ok
    assert d.skill_score.found == 0 and d.tool_score.found == 0 and len(provider.requests) == 1


def test_every_model_arm_decides_from_the_same_bytes(harness, provider):
    model_arms = [a for a in arms_for(harness.config) if a.model]
    assert [(a.name, a.model, a.thinking) for a in model_arms] == [
        ("main-thinking", harness.config.main_model, "enabled"),
        ("main-no-thinking", harness.config.main_model, "disabled"),
        ("sub-model", harness.config.sub_model, harness.config.thinking),
    ]
    provider.script("a", "b", "c")
    for arm in model_arms:
        decide(_case(), arm, harness=harness, decider=None)
    assert len({json.dumps(r.messages, sort_keys=True) for r in provider.requests}) == 1
    assert [(r.model, r.thinking) for r in provider.requests] == [(a.model, a.thinking) for a in model_arms]


def test_a_multi_turn_case_starts_from_its_fixed_prior_working_memory(harness, provider):
    case = _case(
        id="sm-radar-cost", cell="single_intent_multi_turn", message="Is Radar extra?",
        working_memory=(PriorTurn(customer="Chargebacks are hurting us.", agent="Radar can help with that.", skills=("fraud_protection",)),),
    )
    provider.script(_calls(("Skill", {"name": "fraud_protection"}), ("Skill", {"name": "pricing_conversation"})), "Radar is 5c.")
    decide(case, MAIN, harness=harness, decider=None)

    first, second = provider.requests
    prior = first.messages[2:-1]
    assert prior[0]["role"] == "system" and prior[0]["content"].startswith("[Skills primed by the harness: fraud_protection.")
    assert harness.skills["fraud_protection"].body in prior[0]["content"]
    assert prior[1:] == [
        {"role": "user", "content": "Chargebacks are hurting us."},
        {"role": "assistant", "content": "Radar can help with that."},
    ], "plain text: no tool call is fabricated, so no reasoning is invented"
    results = [m["content"] for m in second.messages if m["role"] == "tool"]
    assert results == [ALREADY_IN_CONTEXT.format(name="fraud_protection"), harness.skills["pricing_conversation"].body], \
        "a load of a skill in context is answered as the harness would answer it"


# =========================================================================
# The Decider arm
# =========================================================================
def test_the_decider_arm_runs_the_production_priming_code_and_keeps_every_probability(harness, decider):
    skills = sorted(harness.skills)
    case = _case(
        id="mm-x", cell="multi_intent_multi_turn", message="And tax for Canada, plus readers for the shop?",
        skills=_labels("tax", "terminal"), first_action=("skill:tax", "skill:terminal"),
        working_memory=(PriorTurn(customer="We sell online.", agent="Checkout fits.", skills=("payments",)),),
    )
    decider.script({name: (0.9 if name in ("tax", "terminal") else 0.1) for name in skills})
    d = decide(case, DECIDE, harness=harness, decider=decider)

    (state, questions), = decider.requests
    assert "payments" not in questions and len(questions) == len(skills) - 1, "only skills not in context are asked about"
    assert state["customer_message"] == case.message and state["skills_in_context"] == ["payments"]
    assert d.skills == ["tax", "terminal"] and d.skill_score.exact and d.first_action_ok
    assert set(d.probabilities) == set(questions) and d.probabilities["tax"] == 0.9, "kept for calibration (#18)"
    assert d.tools is None and d.tool_score is None, "the Decider is scored on skills alone"


def test_a_decider_that_primes_nothing_leaves_the_turn_to_the_model(harness, decider):
    low = {name: 0.1 for name in harness.skills}
    decider.script(low, low, Answers(skipped="timeout"))
    handoff_case = _case(skills=_labels(), tools=_labels("request_handoff"), first_action=("handoff",))
    d = decide(handoff_case, DECIDE, harness=harness, decider=decider)
    assert d.skills == [] and d.skipped == "below_threshold" and d.first_action_ok, "abstaining is right when no skill is needed"
    d = decide(_case(), DECIDE, harness=harness, decider=decider)
    assert not d.first_action_ok and d.skill_score.found == 0, "abstaining misses a turn that needed a skill"
    d = decide(_case(), DECIDE, harness=harness, decider=decider)
    assert d.skipped == "timeout" and d.skills == [] and d.error is None, "a Decider failure is a decision: nothing primed"


def test_the_decider_arm_uses_the_configured_threshold(harness, decider):
    harness.config = replace(harness.config, priming_threshold=0.30)
    decider.script({name: (0.35 if name == "pricing_conversation" else 0.05) for name in harness.skills})
    assert decide(_case(), DECIDE, harness=harness, decider=decider).skills == ["pricing_conversation"]


# =========================================================================
# Running, aggregating, reporting
# =========================================================================
def test_a_failed_call_is_recorded_and_the_run_goes_on(harness, provider):
    provider.script(RuntimeError("provider down"), "fine")
    first = decide(_case(), MAIN, harness=harness, decider=None)
    assert first.error and "provider down" in first.error and first.skills == []
    second = decide(_case(id="ss-two"), MAIN, harness=harness, decider=None)
    assert second.error is None
    s = stats([first, second])
    assert s["cases"] == 2 and s["errors"] == 1 and s["first_action"] == 0.0, "errors are counted, not scored"


def test_run_decides_every_case_with_every_arm_and_reports_progress(harness, provider, decider):
    provider.script(_calls(("Skill", {"name": "pricing_conversation"}), ("get_pricing", {"product": "Checkout"})), "plain answer")
    decider.script({n: 0.1 for n in harness.skills}, {n: 0.9 if n == "payments" else 0.1 for n in harness.skills})
    seen = []
    decisions = run([_case(), _case(id="ss-two", split="test")], [MAIN, DECIDE], harness=harness, decider=decider,
                    progress=lambda case, made: seen.append((case.id, [d.arm for d in made])))
    assert [(d.case_id, d.arm) for d in decisions] == [
        ("ss-cost", "main-thinking"), ("ss-cost", "decider"), ("ss-two", "main-thinking"), ("ss-two", "decider"),
    ]
    assert seen == [("ss-cost", ["main-thinking", "decider"]), ("ss-two", ["main-thinking", "decider"])]


def _decision(arm, cell, chosen, labels, latency, *, first_ok=True, tools=None, tool_labels=None, paired=None, error=None,
              case_id=None, **extra):
    return Decision(
        case_id=case_id or f"{arm}-{cell}-{latency}", arm=arm, cell=cell, split="dev", skills=chosen, skill_score=labels.score(chosen),
        first_actions=[], first_action_ok=first_ok, latency_ms=latency, error=error,
        tools=tools, tool_score=tool_labels.score(tools) if tools is not None else None,
        tool_latency_ms=latency * 2 if tools is not None else None, paired=paired, **extra,
    )


def test_numbers_are_micro_averaged_per_arm_and_per_cell():
    two = _labels("payments", "tax")
    decisions = [
        _decision("a", CELLS[0], ["payments"], _labels("payments"), 100, tools=["get_pricing"], tool_labels=_labels("get_pricing")),
        _decision("a", CELLS[0], ["payments", "connect"], _labels("payments"), 300, first_ok=False, tools=[], tool_labels=_labels("get_pricing")),
        _decision("a", CELLS[1], ["payments"], two, 200, tools=["search_knowledge"], tool_labels=_labels(), paired=True),
        _decision("a", CELLS[1], [], two, 400, error="boom"),
        _decision("decider", CELLS[0], [], _labels("payments"), 50),
    ]
    s = summarise(decisions)
    all_a = s["a"]["all"]
    assert all_a["cases"] == 4 and all_a["errors"] == 1
    assert all_a["precision"] == pytest.approx(3 / 4) and all_a["recall"] == pytest.approx(3 / 4)
    assert all_a["f1"] == pytest.approx(3 / 4) and all_a["exact"] == pytest.approx(1 / 3)
    assert all_a["first_action"] == pytest.approx(2 / 3)
    assert (all_a["p50_ms"], all_a["p90_ms"]) == (200, 300), "nearest rank, errors left out"
    assert s["a"][CELLS[1]]["recall"] == pytest.approx(1 / 2)
    assert all_a["tools"]["paired"] == 1 and all_a["tools"]["recall"] == pytest.approx(1 / 2)
    assert all_a["tools"]["precision"] == pytest.approx(1 / 2), "search_knowledge was outside that case's empty tool labels"
    assert s["decider"]["all"]["precision"] is None and s["decider"]["all"]["recall"] == 0.0, "nothing chosen: no precision to speak of"
    assert s["decider"]["all"]["f1"] == 0.0, "nothing required was found: F1 is zero, not undefined"
    assert "tools" not in s["decider"]["all"]
    assert percentile([100, 200, 300, 400, 1000], 0.9) == 1000 and percentile([], 0.5) is None


def test_the_report_states_its_split_and_has_a_machine_readable_twin(tmp_path, harness):
    case, other = _case(), _case(id="ss-two")
    decisions = [
        _decision("main-thinking", CELLS[0], ["pricing_conversation"], case.skills, 900, tools=["get_pricing"],
                  tool_labels=case.tools, case_id="ss-cost"),
        _decision(golden.DECIDER, CELLS[0], [], other.skills, 120, case_id="ss-two", skipped="below_threshold",
                  probabilities={"payments": 0.2}),
    ]
    md, js = write_report(decisions, [case, other], tmp_path / "golden-dev.md", split="dev",
                          arms=[MAIN, DECIDE], config=harness.config)
    text = md.read_text(encoding="utf-8")
    assert "covers the development split (dev), 2 cases" in text
    assert "## Skill selection" in text and "## Tool selection (model arms)" in text and "## Decisions by case" in text
    assert "pricing_conversation ✓" in text and "— (below_threshold)" in text
    assert "NDCG" not in text and "rank" not in text.lower()
    assert _labels("search_knowledge|research").show() == "search_knowledge or research", "no bare | inside a table cell"
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["split"] == "dev" and data["summary"]["main-thinking"]["all"]["precision"] == 1.0
    assert data["decisions"][1]["probabilities"] == {"payments": 0.2}
    assert data["cases"][0]["skills"]["required"] == [["pricing_conversation"]]
    assert data["decider"]["threshold"] == harness.config.priming_threshold


def test_the_command_refuses_an_unknown_arm_or_a_decider_without_its_key(tmp_path, monkeypatch, capsys):
    import dotenv

    from app import database

    monkeypatch.setenv("RUNTIME_DB_PATH", str(tmp_path / "runtime.db"))
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    try:
        assert golden.main(["--arms", "decider,main-thinkin"]) == 2
        assert "unknown arm(s) main-thinkin" in capsys.readouterr().err
        assert golden.main(["--arms", "decider"]) == 2
        assert "the decider arm needs TYPESAFE_API_KEY" in capsys.readouterr().err, \
            "a run without the key must not publish an empty Decider row"
    finally:
        database.close_connection()
