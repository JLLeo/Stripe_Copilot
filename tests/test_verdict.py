"""
The Priming verdict (#19), checked without a network.

Every number the verdict states is read from behaviour-case reports and the
Golden Set's four-arm runs; here those are written by hand, so each claim's
bookkeeping can be checked against a case whose answer is known, and the report
can be shown to say what the numbers say — including when they say no. One test
reads the committed runs and checks the committed report is what they give.
"""

import itertools
import json

import pytest

from app.harness.core import HarnessConfig
from evals import verdict as V
from evals.runner import REPORTS_DIR

pytestmark = pytest.mark.unit

SHIPPED = {"threshold": HarnessConfig().priming_threshold, "margin": HarnessConfig().priming_margin, "decider": "jev-latest"}


def _turn(latency, rounds, primed=(), first_skills=(), first_tools=(), decider=0, skipped=None, redundant=0, paired=False):
    return {"latency_ms": latency, "tool_rounds": rounds, "primed_skills": list(primed), "first_skills": list(first_skills),
            "first_tools": list(first_tools), "decider_ms": decider,
            "priming_skipped": skipped if (skipped or primed) else "priming_off", "redundant_skill_calls": redundant,
            "skill_paired_with_tool": paired, "provider_calls": rounds + 1}


def _first_actions(turn):
    """As the runner records them: primed skills first, then the model's own first response."""
    return [f"skill:{s}" for s in turn["primed_skills"] + turn["first_skills"]] + turn["first_tools"]


def _write_run(path, name, priming, cases, judge=4.3, leaks=0, errors=0, expected=None):
    """cases: {case_id: [turn, ...]} in order. Expected first actions default to whatever came first, so every case passes."""
    expected = expected or {cid: _first_actions(ts[0])[:1] for cid, ts in cases.items()}
    results = []
    for cid, ts in cases.items():
        first = _first_actions(ts[0])
        results.append({"id": cid, "turns": ts, "expected_first": expected[cid], "first_actions": first,
                        "first_action_ok": any(a in first for a in expected[cid]), "judge_score": judge, "leak_free": True,
                        "latency_ms": sum(t["latency_ms"] for t in ts), "error": None})
    every = [t for ts in cases.values() for t in ts]
    lat = sorted(t["latency_ms"] for t in every)
    matched = sum(r["first_action_ok"] for r in results)
    summary = {
        "cases": len(cases), "first_action_accuracy": matched / len(cases), "first_action_matched": matched,
        "mean_judge_score": judge, "leak_free": len(cases) - leaks, "errors": errors, "turns": len(every),
        "primed_turns": sum(1 for t in every if t["primed_skills"]), "tool_rounds": sum(t["tool_rounds"] for t in every),
        "turn_p50_ms": lat[max(0, -(-len(lat) // 2) - 1)], "turn_p90_ms": lat[max(0, -(-len(lat) * 9 // 10) - 1)],
        "redundant_skill_calls": sum(t["redundant_skill_calls"] for t in every),
        "paired_turns": sum(1 for t in every if t["skill_paired_with_tool"]),
    }
    (path / f"{name}.json").write_text(json.dumps({"summary": summary, "priming": priming, "results": results}), encoding="utf-8")


def _write_golden(path):
    def arm(f1, recall, p50, tool_recall=None):
        s = {"f1": f1, "recall": recall, "p50_ms": p50}
        if tool_recall is not None:
            s["tools"] = {"recall": tool_recall}
        return {"all": s}
    for split in ("dev", "test"):
        summary = {"main-thinking": arm(0.93, 0.88, 2900, 0.65), "main-no-thinking": arm(0.68, 0.52, 1850, 0.30),
                   "sub-model": arm(0.95, 0.94, 1950, 0.69), "decider": arm(0.84, 0.78, 190)}
        (path / f"golden-{split}.json").write_text(json.dumps({"summary": summary}), encoding="utf-8")


def _cases(mode, drift=0, gain=0, n=12):
    """n one-turn cases. With Priming off, half spend their first round only loading a skill and half pair a skill with
    a tool; with it on, every first turn is primed, the skill-only round goes, and each turn is `gain` ms faster.
    `drift` moves every turn of a run alike, as the provider's speed does."""
    out = {}
    for i in range(n):
        skill_only = i < n // 2
        base = 10000 + 200 * i + (2000 if skill_only else 0) + drift
        if mode == "off":
            t = _turn(base, 2 if skill_only else 1, first_skills=["payments" if skill_only else "tax"],
                      first_tools=[] if skill_only else ["get_pricing"], paired=not skill_only)
        else:
            t = _turn(base - gain, 1, primed=["payments" if skill_only else "tax"], first_tools=["get_pricing"], decider=200)
        out[f"case{i}"] = [t]
    return out


# =========================================================================
# The claims, turn by turn
# =========================================================================
def test_a_skill_call_on_a_primed_turn_is_told_apart_from_a_reload():
    on = {
        ("a", 0): [_turn(9000, 1, primed=["payments"])],
        ("c", 0): [_turn(9000, 2, primed=["payments"], first_skills=["tax"])],  # Priming missed tax: the fallback
        ("d", 0): [_turn(9000, 2, first_skills=["billing"], skipped="below_threshold")],  # not primed: not counted
    }
    assert V.first_responses_on_primed_turns(on) == {
        "primed_turns": 2, "with_skill_call": 1, "reloaded_a_primed_skill": 0, "loaded_a_skill_priming_missed": 1, "held": True}
    on[("b", 0)] = [_turn(9000, 2, primed=["payments"], first_skills=["payments"], redundant=1)]  # paid for, not used
    reloaded = V.first_responses_on_primed_turns(on)
    assert reloaded["reloaded_a_primed_skill"] == 1 and not reloaded["held"]


def test_rounds_are_compared_only_where_a_round_bought_nothing_and_priming_primed():
    off = {
        ("skill-only", 0): [_turn(12000, 2, first_skills=["payments"]), _turn(13000, 2, first_skills=["payments"], first_tools=["get_my_profile"])],
        ("paired", 0): [_turn(9000, 1, first_skills=["payments"], first_tools=["get_pricing"], paired=True)] * 2,
        ("not-primed", 0): [_turn(12000, 2, first_skills=["tax"])] * 2,
    }
    on = {
        ("skill-only", 0): [_turn(9000, 1, primed=["payments"]), _turn(9500, 1, primed=["payments"])],
        ("paired", 0): [_turn(8000, 1, primed=["payments"])] * 2,
        ("not-primed", 0): [_turn(12000, 2, skipped="timeout")] * 2,
    }
    keys = V.removable_round_turns(off, on)
    assert keys == [("skill-only", 0)], "a profile lookup informs nothing, so that round still bought nothing"
    assert V.rounds_where_a_skill_only_round_existed(off, on, keys) == {
        "turns": 1, "dropped_by_one_or_more": 1, "mean_drop": 1, "held": True}
    assert V.rounds_where_a_skill_only_round_existed(off, on, [])["held"] is False, "no such turns is not a claim held"


def test_the_decider_s_time_is_counted_only_where_it_was_asked():
    on = {("a", i): [_turn(9000, 1, primed=["payments"], decider=ms)] for i, ms in enumerate((150, 180, 200, 220, 650))}
    on[("b", 0)] = [_turn(9000, 1, skipped="all_loaded", decider=0)]
    d = V.decider_time(on)
    assert d["asked"] == 5 and d["p95_ms"] == 650 and d["max_ms"] == 650 and d["held"]
    on[("c", 0)] = [_turn(9000, 1, skipped="timeout", decider=720)] * 3
    assert not V.decider_time(on)["held"], "a 0.7 s timeout still costs its 0.72 s"
    assert V.decider_time({})["held"] is False and V.decider_time({})["max_ms"] is None


def test_a_turn_is_slower_by_median_or_in_every_run_against_what_chance_gives():
    off = {("x", 0): [_turn(10000, 2), _turn(12000, 2), _turn(11000, 2)],
           ("y", 0): [_turn(5000, 1), _turn(6000, 1), _turn(5500, 1)]}
    on = {("x", 0): [_turn(9000, 1, primed=["payments"]), _turn(13000, 1, primed=["payments"]), _turn(11500, 1, primed=["payments"])],
          ("y", 0): [_turn(6500, 1, decider=200, skipped="below_threshold")] * 3}
    s = V.slower_turns(off, on)
    assert s["matched"] == 2 and s["slower_by_median"] == 2
    (every,) = s["slower_in_every_run"]
    assert every["case"] == "y" and every["turn"] == 1 and every["decider_ms"] == [200, 200, 200], \
        "every run with Priming on slower than every run without: worth a row, with what Priming did there"
    assert not every["fewer_rounds_yet_slower"]
    assert s["expected_by_chance"] == pytest.approx(2 / 20), "three runs each way: 1 in C(6, 3) = 20 per turn by chance"
    assert s["chance_p"] == pytest.approx(1 - 2.718281828 ** -0.1, rel=1e-6) and s["held"], \
        "one such turn in two has a 10% chance of happening anyway: not evidence of a slower turn"
    both = V.slower_turns(off, {("x", 0): [_turn(13000, 1)] * 3, ("y", 0): [_turn(6500, 1)] * 3})
    assert len(both["slower_in_every_run"]) == 2 and not both["held"], "both of two: under a 1% chance, so a real slowdown"
    assert both["slower_in_every_run"][0]["fewer_rounds_yet_slower"], "x lost a round and was still slower: said, not hidden"


# =========================================================================
# Speed and rounds, with the runs' own variation
# =========================================================================
def _maps(mode, drifts, gain=0):
    return [V.run_turns({"results": [{"id": cid, "turns": ts} for cid, ts in _cases(mode, d, gain).items()]}) for d in drifts]


def test_a_change_every_run_shows_is_decided_and_a_drift_between_runs_is_not():
    keys = sorted(_maps("off", [0])[0])
    faster = V.two_level(_maps("off", [0, 200]), _maps("on", [0, 200], gain=3000), keys, "latency_ms")
    assert faster["decided"] and faster["delta"] == pytest.approx(-3000) and faster["high"] < 0

    one_each = V.two_level(_maps("off", [0]), _maps("on", [0], gain=1000), keys, "latency_ms")
    assert one_each["high"] < 0, "one run a side: every turn 1 s faster looks certain"
    drifting = V.two_level(_maps("off", [0, 4000]), _maps("on", [0, 4000], gain=1000), keys, "latency_ms")
    assert drifting["delta"] == pytest.approx(-1000) and drifting["low"] < 0 < drifting["high"], \
        "the same turns, seen beside a 4 s drift between runs: not separated from zero"

    rounds = V.two_level(_maps("off", [0, 4000]), _maps("on", [0, 4000], gain=1000), keys, "tool_rounds")
    assert rounds["delta"] == pytest.approx(-0.5) and rounds["high"] < 0, "rounds do not drift with the provider"
    few = V.two_level(_maps("off", [0]), _maps("on", [0]), keys[: V.MIN_TURNS - 1], "latency_ms")
    assert few == {"turns": V.MIN_TURNS - 1, "delta": None, "low": None, "high": None, "decided": False}


def test_runs_needed_follows_the_spread_between_runs():
    assert V.runs_needed([10000, 12000], [9000, 11000], -1000) == 16, "sd 1.41 s against a 1 s change: 2(1.96 x 1.41)^2"
    assert V.runs_needed([10000, 12000], [9000, 11000], -4000) == 2
    assert V.runs_needed([10000, 10000], [9000, 9000], -1000) is None, "no spread: nothing to separate"
    assert V.runs_needed([10000, 12000], [9000, 11000], None) is None
    assert V.run_means(_maps("off", [0, 1000]), [("case0", 0)], "latency_ms") == [12000, 13000]


# =========================================================================
# The reported numbers and the next lever
# =========================================================================
def test_case_latency_is_a_whole_conversation_and_leaves_out_errored_cases():
    run = {"results": [{"latency_ms": 10000, "error": None}, {"latency_ms": 30000, "error": None},
                       {"latency_ms": 900, "error": "HTTP 402"}]}
    assert V.case_latency([run]) == {"cases": 2, "p50_ms": 10000, "p90_ms": 30000}


def test_pairing_is_counted_on_first_turns_run_by_run():
    run = {"results": [{"id": "a", "turns": [_turn(1, 1, paired=True), _turn(1, 1, paired=True)]},
                       {"id": "b", "turns": [_turn(1, 1)]}, {"id": "c", "turns": [_turn(1, 1, paired=True)]}]}
    assert V.paired_first_turns([V.run_turns(run), V.run_turns({"results": []})]) == [2, 0], "a's second turn is not a first turn"


def test_first_action_passes_decided_by_the_primed_skill_are_counted():
    cases = {"credited": [_turn(9000, 1, primed=["payments"], first_tools=["get_pricing"])],
             "own": [_turn(9000, 1, primed=["payments"], first_skills=["tax"])],
             "failed": [_turn(9000, 1, first_tools=["search_docs"], skipped="below_threshold")]}
    expected = {"credited": ["skill:payments"], "own": ["skill:tax"], "failed": ["skill:billing"]}
    run = {"results": [{"id": cid, "turns": ts, "first_actions": _first_actions(ts[0]), "expected_first": expected[cid],
                        "first_action_ok": any(a in _first_actions(ts[0]) for a in expected[cid])} for cid, ts in cases.items()]}
    assert V.first_action_credit([run]) == {"passes": 2, "decided_by_priming": 1}


def test_priming_use_reports_why_turns_went_unprimed_and_raises_the_alarm_when_the_model_asks_again():
    on = {("a", i): [_turn(1, 1, primed=["payments"], redundant=int(i < 2))] for i in range(4)}
    on[("b", 0)] = [_turn(1, 1, skipped="below_threshold")]
    on[("c", 0)] = [_turn(1, 1, skipped="timeout")]
    use = V.priming_use(on)
    assert (use["primed"], use["turns"]) == (4, 6) and use["skip_reasons"] == {"below_threshold": 1, "timeout": 1}
    assert use["primed_turns_asking_again"] == 2 and use["asking_again_rate"] == pytest.approx(0.5) and use["alarm"]
    quiet = V.priming_use({("b", 0): [_turn(1, 1, skipped="below_threshold")]})
    assert quiet["asking_again_rate"] is None and not quiet["alarm"]


def test_the_next_lever_is_an_arm_as_accurate_as_today_within_noise_and_faster_with_its_saving_projected():
    table = {"main-thinking": {"f1": 0.93, "p50_ms": 2900}, "main-no-thinking": {"f1": 0.68, "p50_ms": 1850},
             "sub-model": {"f1": 0.95, "p50_ms": 1950}}
    lever = V.next_lever(table, calls_per_turn=2.0, turn_p50_ms=11000)
    assert lever["recommended"] == "sub-model"
    assert lever["candidates"]["sub-model"]["turn_saving_ms"] == pytest.approx(1900), "0.95 s a decision, two decisions a turn"
    assert lever["candidates"]["sub-model"]["projected_p50_ms"] == pytest.approx(9100)
    assert not lever["candidates"]["main-no-thinking"]["viable"], "25 points of F1 is not noise"
    table["sub-model"]["f1"] = 0.80
    assert V.next_lever(table, 2.0, 11000)["recommended"] is None
    assert V.next_lever({}, None, None) == {"candidates": {}, "recommended": None}


# =========================================================================
# The headline and the recommendation, from the same statuses
# =========================================================================
def _v(status, faster, fewer, alarm):
    lever = {"faster_ms": 950, "f1_gap": -0.02, "viable": True, "turn_saving_ms": 1600, "projected_p50_ms": 9800}
    return {"quality": {"status": status, "errored_runs": ["verdict-on-2"] if status == "incomplete" else []},
            "speed": {"faster": faster, "fewer_rounds": fewer, "runs_needed": 5},
            "priming_use": {"alarm": alarm}, "calls_per_turn_on": 1.7,
            "next_lever": {"recommended": "sub-model", "candidates": {"sub-model": lever}}}


@pytest.mark.parametrize("status,faster,fewer,alarm", list(itertools.product(("held", "degraded", "incomplete"), *[(True, False)] * 3)))
def test_the_report_never_recommends_what_its_headline_rules_out(status, faster, fewer, alarm):
    v = _v(status, faster, fewer, alarm)
    head, advice = V.headline(v), " ".join(V.recommendation(v))
    usable = status == "held" and not alarm
    assert ("can be turned on" in advice) == (usable and (faster or fewer))
    assert ("faster without making it worse" in head) == (usable and faster)
    assert ("runs a side" in advice) == (usable and fewer and not faster)
    assert ("The next lever" in advice) == (status == "held"), "no lever on top of a worse or unfinished result"
    if status == "incomplete":
        assert "No verdict" in head and "verdict-on-2" in head and "rerun" in advice
    if status == "degraded":
        assert "stay off" in head and "keep Priming off" in advice
    if status == "held" and alarm:
        assert "asks again" in head and "make it used" in advice


# =========================================================================
# The verdict, end to end
# =========================================================================
def _verdict(tmp_path, off_drifts, on_drifts, gain, off_judge=4.3, on_judge=4.3, errors=0):
    _write_golden(tmp_path)
    for i, d in enumerate(off_drifts, 1):
        _write_run(tmp_path, f"off-{i}", None, _cases("off", d), judge=off_judge)
    for i, d in enumerate(on_drifts, 1):
        _write_run(tmp_path, f"on-{i}", SHIPPED, _cases("on", d, gain), judge=on_judge, errors=errors if i == 1 else 0)
    v = V.verdict([f"off-{i}" for i in range(1, len(off_drifts) + 1)], [f"on-{i}" for i in range(1, len(on_drifts) + 1)], tmp_path)
    md, js = V.render(v, tmp_path / "verdict.md")
    return v, md.read_text(encoding="utf-8"), json.loads(js.read_text(encoding="utf-8"))


def test_rounds_away_with_latency_inside_the_drift_between_runs_is_said_as_exactly_that(tmp_path):
    v, text, js = _verdict(tmp_path, off_drifts=[0, 4000], on_drifts=[0, 4000], gain=1000)
    assert v["quality"]["status"] == "held" and v["speed"]["fewer_rounds"] and not v["speed"]["faster"]
    assert all(claim["held"] for claim in v["claims"].values())
    assert "**Priming kept quality and took tool rounds away; whether that made turns faster is inside the runs' own variation.**" in text
    assert "| Turn latency | -1.0 s (95% " in text and "| not established |" in text
    assert "Priming can be turned on" in text and "runs a side would show" in text and "Its speed gain is measured" not in text
    assert "| 6, 6 | 0, 0 |" in text, "pairing per run, beside #14's 6 of 19"
    assert "Of the 24 passes with Priming on, 24 rest on that credit" in text
    assert "The next lever is `sub-model`" in text and "Turning thinking off is not the lever: it loses 25 points" in text
    assert js["next_lever"]["recommended"] == "sub-model"


def test_a_change_every_run_shows_is_called_faster(tmp_path):
    v, text, _ = _verdict(tmp_path, off_drifts=[0, 200], on_drifts=[0, 200], gain=3000)
    assert v["speed"]["faster"] and "**Priming made the agent faster without making it worse.**" in text
    assert "Its speed gain is measured." in text and "runs a side" not in text


def test_a_run_that_hurt_quality_gets_that_verdict_and_no_lever(tmp_path):
    v, text, _ = _verdict(tmp_path, off_drifts=[0, 200], on_drifts=[0, 200], gain=3000, off_judge=4.4, on_judge=3.6)
    assert v["quality"]["status"] == "degraded"
    assert "**Priming made the agent worse on the behaviour cases; it should stay off.**" in text and "did not hold" in text
    assert "can be turned on" not in text and "The next lever" not in text


def test_a_run_with_errored_cases_gives_no_verdict(tmp_path):
    _, text, _ = _verdict(tmp_path, off_drifts=[0, 200], on_drifts=[0, 200], gain=3000, errors=1)
    assert "**No verdict: on-1 had errored cases, which are not comparable.**" in text and "rerun" in text


def test_the_committed_report_is_what_the_committed_runs_give(tmp_path):
    v = V.verdict(V.OFF_RUNS, V.ON_RUNS)
    assert v["quality"]["status"] == "held" and v["speed"]["fewer_rounds"]
    assert all(claim["held"] for claim in v["claims"].values())
    md, _ = V.render(v, tmp_path / "priming-verdict.md")
    assert md.read_text(encoding="utf-8") == (REPORTS_DIR / "priming-verdict.md").read_text(encoding="utf-8"), \
        "regenerate the report: python -m evals.verdict"


def test_the_command_refuses_runs_not_made_at_the_configured_defaults(tmp_path, monkeypatch, capsys):
    _write_golden(tmp_path)
    _write_run(tmp_path, "verdict-off-1", None, _cases("off"))
    _write_run(tmp_path, "verdict-on-1", {"threshold": 0.45, "margin": 0.2, "decider": "jev-latest"}, _cases("on"))
    monkeypatch.setattr(V, "REPORTS_DIR", tmp_path)
    assert V.main(["--off", "verdict-off-1", "--on", "verdict-on-1"]) == 2
    assert "verdict-on-1 was not made at the configured defaults" in capsys.readouterr().out
    _write_run(tmp_path, "verdict-on-2", SHIPPED, _cases("on"))
    assert V.main(["--off", "verdict-on-2", "--on", "verdict-on-2"]) == 2, "a run with Priming on cannot be a baseline"
    assert "was made with Priming on" in capsys.readouterr().out
