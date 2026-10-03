"""
Fitting Priming's threshold and margin (#18), checked without a network.

The fit reads only what the Golden Set and the behaviour cases already
recorded, so every step is exercised here on hand-made inputs: the calibration
test that decides whether a probability means the same thing for every skill,
the rules, the decision curve's bookkeeping, the quality check against the
noise of runs with Priming off, the choice, and a report whose published
figures come from the held-out split only. One test reads the committed
reports: the configuration ships the point the fit chooses from them.
"""

import json

import pytest

from app.harness import priming
from app.harness.core import HarnessConfig
from app.harness.skills import load_skills
from evals import thresholds as T
from evals.golden import Labels

pytestmark = pytest.mark.unit


def _labels(*required, acceptable=()):
    return Labels(required=tuple(tuple(r.split("|")) for r in required), acceptable=tuple(acceptable))


def _turn(id, probabilities, *required, acceptable=(), round_ms=3000, decider_ms=200):
    return T.Turn(id=id, cell="single_intent_single_turn", probabilities=probabilities,
                  skills=_labels(*required, acceptable=acceptable), decider_ms=decider_ms, baseline_round_ms=round_ms)


BODY = {name: 1000 for name in ("payments", "billing", "tax", "terminal", "fraud_protection")}


def _report(dev, held_out, rows, path, dev_before=None, held_out_before=None):
    return T.render(T.fit(dev, dev_before, held_out, held_out_before, rows, HarnessConfig(), BODY), path)


# =========================================================================
# Inputs
# =========================================================================
def test_a_baseline_round_counts_only_when_it_bought_nothing_the_customer_could_see(tmp_path):
    cases = [{"id": i, "skills": {"required": [["payments"]], "acceptable": []}} for i in ("a", "b", "c", "d")]
    decider = {"cases": cases, "decisions": [
        {"arm": "decider", "case_id": i, "cell": "single_intent_single_turn", "probabilities": {"payments": 0.9}, "latency_ms": 150}
        for i in ("a", "b", "c", "d")]}
    baseline = {"decisions": [
        {"arm": "main-thinking", "case_id": "a", "error": None, "skills": ["payments"], "paired": False, "latency_ms": 3100},
        {"arm": "main-thinking", "case_id": "b", "error": None, "skills": ["payments"], "paired": True, "latency_ms": 4000},
        {"arm": "main-thinking", "case_id": "c", "error": None, "skills": [], "paired": False, "latency_ms": 2000},
        {"arm": "main-thinking", "case_id": "d", "error": "Timeout", "skills": [], "paired": None, "latency_ms": 0},
        {"arm": "decider", "case_id": "a", "error": None, "skills": ["payments"], "paired": None, "latency_ms": 100},
    ]}
    (tmp_path / "d.json").write_text(json.dumps(decider), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(baseline), encoding="utf-8")
    turns = {t.id: t for t in T.load_turns(tmp_path / "d.json", tmp_path / "b.json")}
    assert turns["a"].baseline_round_ms == 3100, "loaded a skill and called nothing it informs: a round Priming can save"
    assert turns["b"].baseline_round_ms is None, "paired with an informed tool: that round already did real work"
    assert turns["c"].baseline_round_ms is None and turns["d"].baseline_round_ms is None
    assert turns["a"].decider_ms == 150 and turns["a"].skills.required == (("payments",),)


# =========================================================================
# Calibration
# =========================================================================
def test_only_required_and_unwanted_skills_say_whether_a_probability_was_right():
    turns = [_turn("a", {"payments": 0.9, "billing": 0.6, "tax": 0.1}, "payments", acceptable=("billing",))]
    assert T.pairs_by_skill(turns) == {"payments": [("a", 0.9, 1)], "tax": [("a", 0.1, 0)]}, \
        "an acceptable skill is neither right nor wrong to prime, so it is left out"


def test_reliability_and_ece_follow_their_textbook_definitions():
    perfect = [(f"c{i}", 0.25, int(i == 0)) for i in range(4)] + [(f"d{i}", 0.75, int(i < 3)) for i in range(4)]
    assert T.ece(perfect) == pytest.approx(0.0)
    assert [(r["n"], r["observed"]) for r in T.reliability(perfect)] == [(4, 0.25), (4, 0.75)]
    assert T.ece([("a", 0.9, 0), ("b", 0.9, 0)]) == pytest.approx(0.9), "confidently wrong is the worst case"


def test_a_shift_is_fitted_toward_the_truth_shrunk_toward_its_centre_and_always_converges():
    over = [(f"c{i}", 0.8, 0) for i in range(20)] + [(f"d{i}", 0.8, 1) for i in range(5)]
    shift = T.fit_shift(over)
    assert shift < 0, "a skill that is required less often than claimed is shifted down"
    assert T.fit_shift(over[:2]) > shift, "with little evidence the prior holds the shift near its centre"
    assert T.fit_shift(over[:2], centre=-1.5) < -1.0, "a skill's own shift is shrunk toward the shared one, not toward zero"
    assert T.fit_shift([("a", 0.5, 1), ("b", 0.5, 0)]) == pytest.approx(0.0, abs=1e-6)
    every_outcome_one_way = [(f"c{i}", 0.95, 0) for i in range(40)]
    b = T.fit_shift(every_outcome_one_way)
    gradient = -b - 40 * T._sigmoid(T._logit(0.95) + b)
    assert b < -4 and gradient == pytest.approx(0.0, abs=1e-6), "an undamped Newton step oscillates here; the capped one converges"


def test_a_correction_is_called_for_only_when_skills_differ_from_one_another():
    # Both skills required half the time at 0.7: over-confident by the same amount, which the shared shift explains.
    same = [_turn(f"c{i}", {"payments": 0.7, "billing": 0.7}, "payments" if i % 2 else "billing") for i in range(40)]
    assert not T.calibration(same)["correction_called_for"]
    # At 0.9 payments is always required and billing never: a shift per skill predicts held-back cases better.
    differ = [_turn(f"c{i}", {"payments": 0.9, "billing": 0.9}, "payments") for i in range(40)]
    cal = T.calibration(differ)
    assert cal["skills"]["billing"]["shift"] < cal["skills"]["payments"]["shift"] and cal["correction_called_for"]


# =========================================================================
# The rules and the decision curve
# =========================================================================
def test_the_rule_before_18_gave_up_on_a_close_three_and_production_does_not():
    two_asks = {"fraud_protection": 0.92, "terminal": 0.89, "payments": 0.60}
    close = {"fraud_protection": 0.70, "terminal": 0.65, "payments": 0.60}
    old = T.RULES["top one when clear (#16)"].choose
    assert old(two_asks, 0.55, 0.15) == (["fraud_protection"], None), "the #15 finding: terminal at 0.89 dropped"
    assert old(close, 0.55, 0.15) == ([], "flat")
    assert T.RULES[T.PRODUCTION].choose is priming.choose
    assert priming.choose(two_asks, 0.55, 0.15) == (["fraud_protection", "terminal"], None)
    assert priming.choose(close, 0.55, 0.15) == (["fraud_protection", "terminal"], None)
    assert T.RULES["top two"].choose({"a": 0.9, "b": 0.6, "c": 0.56}, 0.55, 0.0) == (["a", "b"], None)
    assert T.RULES["top two"].margins == (0.0,) and len(T.RULES[T.PRODUCTION].margins) > 1


def test_a_round_is_saved_only_when_every_required_skill_was_primed_on_a_round_that_bought_nothing():
    turns = [
        _turn("complete", {"payments": 0.9, "tax": 0.8}, "payments", "tax", round_ms=4000),
        _turn("partial", {"payments": 0.9, "tax": 0.3}, "payments", "tax", round_ms=5000),
        _turn("paired-baseline", {"billing": 0.9}, "billing", round_ms=None),  # the first round already did real work
        _turn("nothing-needed", {"terminal": 0.7}, round_ms=1500),  # a needless skill round: priming cannot save it
        _turn("decider-failed", {}, "payments", round_ms=2500),  # a timeout: no probabilities, nothing primed
    ]
    p = T.evaluate(turns, priming.choose, 0.55, 0.20, BODY)
    assert (p["rounds_saved"], p["rounds_to_save"]) == (1, 3)
    assert p["seconds_saved"] == pytest.approx(4.0) and p["decider_seconds"] == pytest.approx(1.0)
    assert (p["wrong_primes"], p["wrong_prime_tokens"]) == (1, 1000), "terminal was primed where nothing was needed"
    assert p["missed"] == 2, "tax on 'partial' and payments on the failed Decider call"


def test_the_curve_covers_every_rule_and_best_prefers_rounds_then_fewer_wrong_primes_then_priming_less():
    turns = [_turn("a", {"payments": 0.7}, "payments"), _turn("b", {"billing": 0.5}, round_ms=None)]
    curve = T.curve(turns, BODY)
    assert set(curve) == set(T.RULES)
    assert len(curve["top two"]) == len(T.THRESHOLDS)
    assert len(curve[T.PRODUCTION]) == len(T.THRESHOLDS) * len(T.MARGINS)
    best = T.best(curve[T.PRODUCTION])
    assert best["rounds_saved"] == 1 and best["wrong_primes"] == 0, "billing at 0.5 is wrong to prime, so the threshold rises past it"
    assert (best["threshold"], best["margin"]) == (0.70, 0.05), "on a plateau: the highest threshold, then the smallest margin"
    assert T.plateau_margins(curve[T.PRODUCTION], 0.70) == list(T.MARGINS), "with nothing in the margin's way, every margin ties"


# =========================================================================
# Quality and the choice
# =========================================================================
def _row(name, threshold, first, judge, errors=0, margin=0.20, rounds=40):
    settings = None if threshold is None else {"threshold": threshold, "margin": margin, "decider": "jev-latest"}
    return {"name": name, "priming": settings, "threshold": threshold, "margin": None if threshold is None else margin,
            "cases": 19, "errors": errors, "first_action": first, "judge": judge, "leak_free": 19, "turns": 25,
            "primed_turns": 0 if threshold is None else 18, "tool_rounds": rounds, "p50_ms": 12000, "p90_ms": 24000,
            "redundant_skill_calls": 0}


def test_quality_is_judged_against_the_noise_between_two_runs_with_priming_off():
    rows = [_row("off-a", None, 1.0, 4.30), _row("off-b", None, 18 / 19, 4.60),
            _row("t045", 0.45, 18 / 19, 4.35, rounds=28), _row("t055", 0.55, 17 / 19, 4.50), _row("t065", 0.65, 1.0, 4.10),
            _row("t075", 0.75, 1.0, 4.60, errors=2)]
    q = T.quality(rows)
    assert q["noise"]["judge"] == pytest.approx(0.30) and q["noise"]["first_action"] == pytest.approx(1 / 19)
    within = {r["name"]: r["within_noise"] for r in q["runs"]}
    assert within == {"t045": True, "t055": False, "t065": False, "t075": False}, \
        "two cases down is outside a one-case noise; 0.35 under the judge baseline is outside 0.30; an errored run is not comparable"
    assert next(r for r in q["runs"] if r["name"] == "t045")["d_tool_rounds"] == pytest.approx(-12)
    tight = T.quality([_row("off-a", None, 1.0, 4.40), _row("off-b", None, 1.0, 4.42), _row("t", 0.6, 1.0, 4.25)])
    assert tight["noise"]["judge"] == T.JUDGE_NOISE_FLOOR and tight["runs"][0]["within_noise"], "agreeing off runs still allow the floor"


def test_the_choice_is_the_curve_s_best_point_among_settings_that_kept_quality():
    points = [{"threshold": t, "margin": 0.2, "rounds_saved": r, "wrong_primes": w}
              for t, r, w in ((0.45, 28, 6), (0.55, 28, 5), (0.65, 27, 3))]
    keep_all = {"runs": [{"threshold": t, "margin": 0.2, "within_noise": True} for t in (0.45, 0.55, 0.65)]}
    assert T.operating_point(points, keep_all)["threshold"] == 0.55, "most rounds, then fewest wrong primes"
    hurt = {"runs": [{"threshold": 0.55, "margin": 0.2, "within_noise": False}, {"threshold": 0.65, "margin": 0.2, "within_noise": True}]}
    assert T.operating_point(points, hurt)["threshold"] == 0.65, "a setting that hurt quality is never chosen, however many rounds it saves"
    assert T.operating_point(points, {"runs": []}) is None


def test_the_configuration_ships_the_point_the_fit_chooses_from_the_committed_reports():
    inputs = T.load_all()
    config = HarnessConfig()
    body = {name: 1000 for name in load_skills(config.skills_dir)}
    result = T.fit(inputs["dev"], inputs["dev_before"], inputs["held_out"], inputs["held_out_before"], inputs["rows"], config, body)
    assert result["choice"] is not None and result["shipped_is_choice"], \
        "change the defaults only by refitting: python -m evals.thresholds says which point the data supports"
    assert result["outranking_unrun"] == [], "no setting left unrun could have outranked the choice"


# =========================================================================
# The report
# =========================================================================
def _behaviour_report(path, name, settings, first, judge, rounds, errors=0):
    summary = {"cases": 19, "first_action_accuracy": first, "mean_judge_score": judge, "leak_free": 19, "errors": errors,
               "turns": 25, "primed_turns": 0 if settings is None else 18, "tool_rounds": rounds,
               "turn_p50_ms": 12000, "turn_p90_ms": 24000, "redundant_skill_calls": 0}
    (path / f"{name}.json").write_text(json.dumps({"summary": summary, "priming": settings, "results": []}), encoding="utf-8")


SHIPPED = {"threshold": HarnessConfig().priming_threshold, "margin": HarnessConfig().priming_margin, "decider": "jev-latest"}


def test_published_figures_come_from_the_held_out_split_and_every_conclusion_is_computed(tmp_path):
    _behaviour_report(tmp_path, "off-a", None, 1.0, 4.4, 42)
    _behaviour_report(tmp_path, "off-b", None, 1.0, 4.3, 40)
    _behaviour_report(tmp_path, "on", SHIPPED, 1.0, 4.5, 28)
    rows = T.behaviour(["off-a", "missing", "off-b", "on"], reports=tmp_path)
    assert [r["name"] for r in rows] == ["off-a", "off-b", "on"], "a run that was not made is skipped, not invented"

    dev = [_turn(f"d{i}", {"payments": 0.9, "billing": 0.2}, "payments") for i in range(6)]
    held_out = [_turn("h1", {"payments": 0.9}, "payments", round_ms=5000), _turn("h2", {"tax": 0.6}, "billing", round_ms=6000)]
    md, js = _report(dev, held_out, rows, tmp_path / "priming-thresholds.md")
    text = md.read_text(encoding="utf-8")
    assert "**development split** (6 cases)" in text and "**held-out split** (2 cases)" in text
    results = text.split("## Results (held-out split)")[1].split("## How the values were chosen")[0]
    assert "1 of 2" in results and "5 s" in results and "1 (1,000 tokens)" in results, \
        "h1 saved its 5-second round; h2 primed tax where billing was needed"
    assert "Decider's state before #18" not in results and "**The state.**" not in results, "no before-#18 claim without its data"
    assert "**These are the shipped values.**" in text and "| on | 0.55 / 0.2 |" in text and "28 (-13)" in text
    assert (tmp_path / "priming-thresholds-reliability.svg").read_text(encoding="utf-8").startswith("<svg")
    assert "<polyline" in (tmp_path / "priming-thresholds-curve.svg").read_text(encoding="utf-8")
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["held_out"]["shipped"]["rounds_saved"] == 1 and data["development"]["shipped"]["cases"] == 6


def test_the_report_never_claims_a_correction_it_did_not_make_or_quality_it_did_not_keep(tmp_path):
    differ = [_turn(f"c{i}", {"payments": 0.9, "billing": 0.9}, "payments") for i in range(40)]
    _behaviour_report(tmp_path, "off-a", None, 1.0, 4.4, 42)
    _behaviour_report(tmp_path, "off-b", None, 1.0, 4.4, 42)
    _behaviour_report(tmp_path, "bad", SHIPPED, 1.0, 3.5, 28)
    rows = T.behaviour(["off-a", "off-b", "bad"], reports=tmp_path)
    md, _ = _report(differ, differ[:5], rows, tmp_path / "r.md")
    text = md.read_text(encoding="utf-8")
    assert "a per-skill correction is called for. **This fit does not apply one**" in text
    assert "| bad |" in text and "✗" in text and "No setting qualified" in text
    assert "**The shipped values (0.55 / 0.2) are not this point.**" in text


def test_a_chart_survives_an_empty_axis_and_markup_in_its_labels(tmp_path):
    path = tmp_path / "c.svg"
    T._svg_chart(path, "Rounds & <primes>", "x", "y", {"a < b": [(0.3, 0), (0.4, 0)]}, (0.3, 0.9), (0, 0))
    svg = path.read_text(encoding="utf-8")
    assert "Rounds &amp; &lt;primes&gt;" in svg and "a &lt; b" in svg and "nan" not in svg.lower()
