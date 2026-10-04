"""
The verdict on Priming (#19): faster without being worse, measured the same way before and after.

The nineteen behaviour cases run several times with Priming off and several
times on at the fitted defaults, each run written to its own report
(`EVAL_REPORT=<name> pytest -m eval`). This module reads those reports and the
Golden Set's four-arm runs (#17) and states, from the numbers alone:

1. **Quality.** First-action accuracy, the judge's mean and the leak count must
   not degrade. Each run with Priming on is checked against the noise between
   the runs with it off (`thresholds.quality`). First-action accuracy is not
   measured quite the same way on both sides — with Priming on, a primed skill
   counts as the first move — so the report says how many passes that credit
   decided.
2. **The committed claims, turn by turn.** A turn is matched across runs by its
   case and its position, so the same customer message is compared with itself:
   - on a primed turn the first response does not reload a primed skill;
   - where the first round loaded skills and bought nothing, a round goes away;
   - the Decider spends no more than 0.7 s at p95;
   - no turn is slower with Priming on. With a handful of runs some turns are
     slower in every run by chance, so the count is set against that.
3. **Speed and rounds.** Whole runs differ from one another — the provider is
   faster at some hours than others — and that drift touches every turn of a
   run alike. So the change per turn, on minus off, gets its interval from a
   two-level bootstrap that resamples the runs of each mode as well as the
   turns. Faster means the whole interval is below zero. Tool rounds get the
   same treatment; they do not move with the provider's speed.
4. **The reported numbers.** Turn and case latency p50/p90 before and after (#14
   stated its baseline per case), the share of primed turns asking again for a
   skill already in context, the first turns pairing a `Skill` call with a tool
   it informs (per run, so they can be set beside #14's 6 of 19), the share
   primed and why the rest were not.
5. **The next lever.** The four-arm table read against this result: which arm
   keeps skill selection within the Golden Set's noise and decides faster, and
   roughly how much of a turn that would save.

The headline and every recommendation follow from the same few computed
statuses, so the report cannot recommend what its own headline rules out.

    python -m evals.verdict        # → evals/reports/priming-verdict.md and its JSON
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from app.harness.core import HarnessConfig
from app.harness.skills import UNINFORMED_TOOLS
from evals.runner import REPORTS_DIR, percentile
from evals.thresholds import behaviour, quality

OFF_RUNS = ["verdict-off-1", "verdict-off-2", "verdict-off-3"]
# A third run with Priming on, verdict-on-2, was lost: the provider first rate-limited it alongside five others,
# then refused it for an empty account balance (HTTP 402). Errored cases are not comparable, so it is left out.
ON_RUNS = ["verdict-on-1", "verdict-on-3"]
DECIDER_BUDGET_MS = 700  # #14: the Decider spends no more than 0.7 s at p95
REDUNDANT_ALARM = 0.25  # a skill already in context asked for again on a quarter of primed turns: Priming paid for, not used
ARM_NOISE = 0.07  # the Golden Set's run-to-run spread on forty cases (#17): smaller differences in F1 are not differences
TARGET_P50_MS = 6000  # #14: a turn p50 of 6 s is what a second lever would be for
SPEC_CASE_P50_MS, SPEC_CASE_P90_MS = 13700, 48800  # #14's baseline, per case
SPEC_PAIRED_FIRST_TURNS = 6  # #14: first turns pairing Skill with a tool it informs, of 19
BOOTSTRAP = 4000  # resamples; seeded, so a report is reproducible
MIN_TURNS = 10  # fewer matched turns than this and no verdict on speed is given
Z = 1.96

RunTurns = dict[tuple[str, int], dict[str, Any]]  # one run's turns, keyed by (case, position)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def load_runs(names: list[str], reports: Path = REPORTS_DIR) -> list[dict[str, Any]]:
    """The behaviour-case reports, as written; a missing one is an error, not a smaller sample."""
    runs = []
    for name in names:
        data = json.loads((reports / f"{name}.json").read_text(encoding="utf-8"))
        runs.append({"name": name, "priming": data.get("priming"), "summary": data["summary"], "results": data["results"]})
    return runs


def run_turns(run: dict[str, Any]) -> RunTurns:
    """A run's recorded turns; a turn whose metrics row was missing is left out, and the positions stay true."""
    return {(r["id"], i): t for r in run["results"] for i, t in enumerate(r.get("turns", [])) if t}


def pooled(maps: list[RunTurns]) -> dict[tuple[str, int], list[dict[str, Any]]]:
    """Every run's sample of each turn, together."""
    out: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for m in maps:
        for key, turn in m.items():
            out.setdefault(key, []).append(turn)
    return out


def _skill_only(turn: dict[str, Any]) -> bool:
    """The first response loaded skills and called nothing a skill informs: a round that bought nothing."""
    return bool(turn["first_skills"]) and all(t in UNINFORMED_TOOLS for t in turn["first_tools"])


def _mean_or_none(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


# ---------------------------------------------------------------------------
# The claims
# ---------------------------------------------------------------------------
def first_responses_on_primed_turns(on: dict) -> dict[str, Any]:
    """On a primed turn, what the first response did with Skill: nothing (the claim), reload a primed skill, or load
    one Priming missed — the second breaks the claim, the third is the fallback working."""
    primed = [t for samples in on.values() for t in samples if t["primed_skills"]]
    reloaded = [t for t in primed if set(t["first_skills"]) & set(t["primed_skills"])]
    missed = [t for t in primed if set(t["first_skills"]) - set(t["primed_skills"])]
    return {"primed_turns": len(primed), "with_skill_call": sum(1 for t in primed if t["first_skills"]),
            "reloaded_a_primed_skill": len(reloaded), "loaded_a_skill_priming_missed": len(missed),
            "held": not reloaded}


def removable_round_turns(off: dict, on: dict) -> list[tuple[str, int]]:
    """Turns whose first round, with Priming off, loaded skills and bought nothing in most runs, and that Priming
    primed in most runs: where #14 says a round goes away."""
    return [key for key in sorted(set(off) & set(on))
            if sum(_skill_only(t) for t in off[key]) * 2 > len(off[key])
            and sum(bool(t["primed_skills"]) for t in on[key]) * 2 > len(on[key])]


def rounds_where_a_skill_only_round_existed(off: dict, on: dict, keys: list[tuple[str, int]]) -> dict[str, Any]:
    """On those turns, by how many tool rounds the median fell."""
    drops = [statistics.median(t["tool_rounds"] for t in off[k]) - statistics.median(t["tool_rounds"] for t in on[k]) for k in keys]
    mean_drop = _mean_or_none(drops)
    return {"turns": len(drops), "dropped_by_one_or_more": sum(1 for d in drops if d >= 1), "mean_drop": mean_drop,
            "held": mean_drop is not None and mean_drop >= 1}


def decider_time(on: dict) -> dict[str, Any]:
    """The Decider's time on every turn it was asked about."""
    asked = [t["decider_ms"] for samples in on.values() for t in samples if t["priming_skipped"] != "all_loaded"]
    p95 = percentile(asked, 0.95)
    return {"asked": len(asked), "p50_ms": percentile(asked, 0.5), "p95_ms": p95, "max_ms": max(asked) if asked else None,
            "held": p95 is not None and p95 <= DECIDER_BUDGET_MS}


def _poisson_tail(observed: int, expected: float) -> float:
    """P(X >= observed) for X ~ Poisson(expected)."""
    return 1.0 - sum(math.exp(-expected) * expected ** k / math.factorial(k) for k in range(observed))


def slower_turns(off: dict, on: dict) -> dict[str, Any]:
    """Turns slower with Priming on: by median, and in every run (every on run slower than every off run).

    With n runs on and m off and no difference at all, a turn is slower in every run with probability
    1 / C(n + m, n); summed over the turns that is how many to expect by chance. The claim stands while seeing
    at least as many by chance is still likely (a one-sided Poisson tail above 5%). With few runs this test only
    catches a slowdown on many turns, and the report says so; each turn slower in every run is listed with what
    Priming did there.
    """
    beyond, slower_by_median, expected = [], 0, 0.0
    for key in sorted(set(off) & set(on)):
        off_ms, on_ms = [t["latency_ms"] for t in off[key]], [t["latency_ms"] for t in on[key]]
        expected += 1 / math.comb(len(on_ms) + len(off_ms), len(on_ms))
        slower_by_median += statistics.median(on_ms) > statistics.median(off_ms)
        if min(on_ms) > max(off_ms):
            off_rounds, on_rounds = [t["tool_rounds"] for t in off[key]], [t["tool_rounds"] for t in on[key]]
            beyond.append({
                "case": key[0], "turn": key[1] + 1, "off_ms": sorted(off_ms), "on_ms": sorted(on_ms),
                "decider_ms": [t["decider_ms"] for t in on[key]], "off_rounds": off_rounds, "on_rounds": on_rounds,
                "primed": [t["primed_skills"] for t in on[key]],
                "fewer_rounds_yet_slower": statistics.mean(on_rounds) < statistics.mean(off_rounds),
            })
    chance_p = _poisson_tail(len(beyond), expected)
    return {"matched": len(set(off) & set(on)), "slower_by_median": slower_by_median, "slower_in_every_run": beyond,
            "expected_by_chance": expected, "chance_p": chance_p, "held": chance_p > 0.05}


# ---------------------------------------------------------------------------
# Speed and rounds, with the runs' own variation
# ---------------------------------------------------------------------------
def two_level(off_maps: list[RunTurns], on_maps: list[RunTurns], keys: list[tuple[str, int]], field: str) -> dict[str, Any]:
    """The mean over turns of (mean over on runs - mean over off runs), with a 95% interval from resampling the runs
    of each mode and the turns. Only turns present in every run are used, so every resample is defined."""
    keys = [k for k in keys if all(k in m for m in off_maps + on_maps)]
    if len(keys) < MIN_TURNS or not off_maps or not on_maps:
        return {"turns": len(keys), "delta": None, "low": None, "high": None, "decided": False}

    def delta(offs: list[RunTurns], ons: list[RunTurns], ks: list[tuple[str, int]]) -> float:
        return statistics.mean(statistics.mean(m[k][field] for m in ons) - statistics.mean(m[k][field] for m in offs) for k in ks)

    rng = random.Random(0)
    draws = sorted(
        delta([rng.choice(off_maps) for _ in off_maps], [rng.choice(on_maps) for _ in on_maps], [rng.choice(keys) for _ in keys])
        for _ in range(BOOTSTRAP)
    )
    low, high = draws[int(BOOTSTRAP * 0.025)], draws[int(BOOTSTRAP * 0.975) - 1]
    return {"turns": len(keys), "delta": delta(off_maps, on_maps, keys), "low": low, "high": high, "decided": True}


def run_means(maps: list[RunTurns], keys: list[tuple[str, int]], field: str) -> list[float]:
    """Each run's mean over the turns every run has."""
    keys = [k for k in keys if all(k in m for m in maps)]
    return [statistics.mean(m[k][field] for k in keys) for m in maps] if keys else []


def runs_needed(off_means: list[float], on_means: list[float], effect: float | None) -> int | None:
    """Runs a side for a run-level comparison to separate an effect of this size from the runs' own spread (95%)."""
    if not effect or len(off_means) + len(on_means) < 3:
        return None
    deviations = [m - statistics.mean(off_means) for m in off_means] + [m - statistics.mean(on_means) for m in on_means]
    sd = math.sqrt(sum(d * d for d in deviations) / (len(deviations) - 2))
    return max(2, math.ceil(2 * (Z * sd / abs(effect)) ** 2)) if sd else None


# ---------------------------------------------------------------------------
# The reported numbers
# ---------------------------------------------------------------------------
def turn_latency(samples: dict) -> dict[str, Any]:
    ms = [t["latency_ms"] for ts in samples.values() for t in ts]
    return {"turns": len(ms), "p50_ms": percentile(ms, 0.5), "p90_ms": percentile(ms, 0.9)}


def case_latency(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Per case, as #14 stated its baseline: a whole conversation from its first message to its last reply."""
    ms = [r["latency_ms"] for run in runs for r in run["results"] if r.get("error") is None and r.get("latency_ms")]
    return {"cases": len(ms), "p50_ms": percentile(ms, 0.5), "p90_ms": percentile(ms, 0.9)}


def spread(runs: list[dict[str, Any]], key: str) -> float:
    values = [r["summary"][key] for r in runs if r["summary"].get(key) is not None]
    return max(values) - min(values) if values else 0.0


def paired_first_turns(maps: list[RunTurns]) -> list[int]:
    """Per run: first turns whose first response paired a Skill call with a tool it informs — #14's measure."""
    return [sum(1 for (case, i), t in m.items() if i == 0 and t["skill_paired_with_tool"]) for m in maps]


def first_action_credit(on_runs: list[dict[str, Any]]) -> dict[str, Any]:
    """With Priming on, how many first-action passes the primed skill decided: the case passed, and would not have on
    the model's own first response."""
    passes = credited = 0
    for run in on_runs:
        for r in run["results"]:
            if not r.get("first_action_ok"):
                continue
            passes += 1
            primed = {f"skill:{s}" for s in (r.get("turns") or [{}])[0].get("primed_skills", [])}
            own = [a for a in r.get("first_actions", []) if a not in primed]
            if not any(a in r.get("expected_first", []) for a in own):
                credited += 1
    return {"passes": passes, "decided_by_priming": credited}


def priming_use(on: dict) -> dict[str, Any]:
    every = [t for ts in on.values() for t in ts]
    primed = [t for t in every if t["primed_skills"]]
    asked_again = sum(1 for t in primed if t["redundant_skill_calls"])
    rate = asked_again / len(primed) if primed else None
    return {
        "turns": len(every), "primed": len(primed), "share_primed": len(primed) / len(every) if every else None,
        "skip_reasons": dict(Counter(t["priming_skipped"] for t in every if not t["primed_skills"]).most_common()),
        "primed_turns_asking_again": asked_again, "asking_again_rate": rate,
        "alarm": rate is not None and rate >= REDUNDANT_ALARM,
    }


# ---------------------------------------------------------------------------
# The four arms
# ---------------------------------------------------------------------------
def arms(reports: Path = REPORTS_DIR) -> dict[str, dict[str, Any]]:
    """Skill selection per arm from the four-arm Golden Set runs (#17), development and held-out averaged."""
    out: dict[str, dict[str, list[float]]] = {}
    for split in ("dev", "test"):
        data = json.loads((reports / f"golden-{split}.json").read_text(encoding="utf-8"))
        for arm, scopes in data["summary"].items():
            s = scopes["all"]
            mine = out.setdefault(arm, {"f1": [], "recall": [], "p50_ms": [], "tool_recall": []})
            for key, value in (("f1", s.get("f1")), ("recall", s.get("recall")), ("p50_ms", s.get("p50_ms")),
                               ("tool_recall", (s.get("tools") or {}).get("recall"))):
                if value is not None:
                    mine[key].append(value)
    return {arm: {k: _mean_or_none(v) for k, v in m.items()} for arm, m in out.items()}


def next_lever(table: dict[str, dict[str, Any]], calls_per_turn: float | None, turn_p50_ms: float | None) -> dict[str, Any]:
    """Which arm could take over the main model's decisions: as accurate as today's within the Golden Set's noise, and
    faster to decide — and roughly what that would take off a turn: its time saved per decision, once per model call."""
    today = table.get("main-thinking")
    candidates: dict[str, dict[str, Any]] = {}
    for arm in ("main-no-thinking", "sub-model"):
        a = table.get(arm)
        if not today or not a or None in (a["f1"], a["p50_ms"], today["f1"], today["p50_ms"]):
            continue
        faster_ms = today["p50_ms"] - a["p50_ms"]
        saving = faster_ms * calls_per_turn if calls_per_turn and faster_ms > 0 else None
        candidates[arm] = {
            "f1_gap": today["f1"] - a["f1"], "faster_ms": faster_ms,
            "viable": today["f1"] - a["f1"] <= ARM_NOISE and faster_ms > 0,
            "turn_saving_ms": saving,
            "projected_p50_ms": turn_p50_ms - saving if saving is not None and turn_p50_ms is not None else None,
        }
    viable = [arm for arm, c in candidates.items() if c["viable"]]
    return {"candidates": candidates, "recommended": max(viable, key=lambda a: candidates[a]["faster_ms"]) if viable else None}


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------
def verdict(off_names: list[str], on_names: list[str], reports: Path = REPORTS_DIR) -> dict[str, Any]:
    off_runs, on_runs = load_runs(off_names, reports), load_runs(on_names, reports)
    checked = quality(behaviour(off_names + on_names, reports))
    off_maps, on_maps = [run_turns(r) for r in off_runs], [run_turns(r) for r in on_runs]
    off, on = pooled(off_maps), pooled(on_maps)
    keys = sorted(set(off) & set(on))
    removable = removable_round_turns(off, on)
    elsewhere = [k for k in keys if k not in set(removable)]

    def mean_of(runs: list[dict[str, Any]], key: str) -> float | None:
        return _mean_or_none([r["summary"][key] for r in runs if r["summary"].get(key) is not None])

    errored = [r["name"] for r in off_runs + on_runs if r["summary"].get("errors")]
    gate = {
        "first_action": {"off": mean_of(off_runs, "first_action_accuracy"), "on": mean_of(on_runs, "first_action_accuracy")},
        "first_action_credit": first_action_credit(on_runs),
        "judge": {"off": mean_of(off_runs, "mean_judge_score"), "on": mean_of(on_runs, "mean_judge_score")},
        "leaks": {"off": sum(r["summary"]["cases"] - r["summary"]["leak_free"] for r in off_runs),
                  "on": sum(r["summary"]["cases"] - r["summary"]["leak_free"] for r in on_runs)},
        "errored_runs": errored,
        "runs_outside_noise": [r["name"] for r in checked["runs"] if not r["within_noise"] and r["complete"]],
        "noise": checked["noise"],
    }
    gate["status"] = ("incomplete" if errored else
                      "held" if not gate["runs_outside_noise"] and checked["runs"] and gate["leaks"]["on"] == 0 else "degraded")
    latency = two_level(off_maps, on_maps, keys, "latency_ms")
    rounds = two_level(off_maps, on_maps, keys, "tool_rounds")
    off_means, on_means = run_means(off_maps, keys, "latency_ms"), run_means(on_maps, keys, "latency_ms")
    on_turn = turn_latency(on)
    calls = _mean_or_none([t["provider_calls"] for ts in on.values() for t in ts])
    table = arms(reports)
    return {
        "off_runs": off_names, "on_runs": on_names, "priming": on_runs[0]["priming"] if on_runs else None,
        "quality": gate,
        "claims": {
            "first_response": first_responses_on_primed_turns(on),
            "rounds": rounds_where_a_skill_only_round_existed(off, on, removable),
            "decider": decider_time(on),
            "slower": slower_turns(off, on),
        },
        "speed": {
            "latency": latency, "rounds": rounds,
            "where_a_round_went": two_level(off_maps, on_maps, removable, "latency_ms"),
            "elsewhere": two_level(off_maps, on_maps, elsewhere, "latency_ms"),
            "run_means_ms": {"off": off_means, "on": on_means},
            "runs_needed": runs_needed(off_means, on_means, latency["delta"]),
            "faster": latency["decided"] and latency["high"] < 0,
            "slower": latency["decided"] and latency["low"] > 0,
            "fewer_rounds": rounds["decided"] and rounds["high"] < 0,
        },
        "latency": {"turn": {"off": turn_latency(off), "on": on_turn},
                    "case": {"off": case_latency(off_runs), "on": case_latency(on_runs)},
                    "turn_p50_spread_off_ms": spread(off_runs, "turn_p50_ms"), "turn_p90_spread_off_ms": spread(off_runs, "turn_p90_ms")},
        "paired_first_turns": {"off": paired_first_turns(off_maps), "on": paired_first_turns(on_maps)},
        "priming_use": priming_use(on),
        "arms": table,
        "next_lever": next_lever(table, calls, on_turn["p50_ms"]),
        "calls_per_turn_on": calls,
    }


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.0%}"


def _s(ms: float | None) -> str:
    return "—" if ms is None else f"{ms / 1000:.1f} s"


def _two(x: float | None) -> str:
    return "—" if x is None else f"{x:.2f}"


def _mark(ok: bool) -> str:
    return "✓" if ok else "✗"


def _interval(t: dict[str, Any], unit: str = "s") -> str:
    if not t["decided"]:
        return f"too few turns ({t['turns']}) to say"
    if unit == "s":
        return f"{t['delta'] / 1000:+.1f} s (95% {t['low'] / 1000:+.1f} to {t['high'] / 1000:+.1f})"
    return f"{t['delta']:+.2f} (95% {t['low']:+.2f} to {t['high']:+.2f})"


def headline(v: dict[str, Any]) -> str:
    q, sp, use = v["quality"]["status"], v["speed"], v["priming_use"]
    if q == "incomplete":
        return f"**No verdict: {', '.join(v['quality']['errored_runs'])} had errored cases, which are not comparable.**"
    if q == "degraded":
        return "**Priming made the agent worse on the behaviour cases; it should stay off.**"
    if use["alarm"]:
        return "**Priming kept quality, but it is paid for and not used: the model asks again for what it was given.**"
    if sp["faster"]:
        return "**Priming made the agent faster without making it worse.**"
    if sp["fewer_rounds"]:
        return ("**Priming kept quality and took tool rounds away; whether that made turns faster is inside the runs' own "
                "variation.**")
    return "**Priming kept quality but did not measurably change the agent's speed or its tool rounds.**"


def recommendation(v: dict[str, Any]) -> list[str]:
    q, sp, use, lever = v["quality"]["status"], v["speed"], v["priming_use"], v["next_lever"]
    if q == "incomplete":
        return ["**Recommendation:** rerun the errored runs before deciding anything."]
    out = []
    if q == "degraded":
        out.append("**Recommendation:** keep Priming off, and find what made the replies worse before trying again.")
    elif use["alarm"]:
        out.append("**Recommendation:** before turning Priming on, make it used: the model asks again for skills it was given "
                   "often enough that the round Priming was meant to save is still being spent.")
    elif sp["fewer_rounds"] or sp["faster"]:
        out.append(
            "**Recommendation:** Priming can be turned on (`HARNESS_PRIMING=1`): it kept quality and took tool rounds away. "
            + ("Its speed gain is measured." if sp["faster"] else
               "Its effect on latency is not yet separated from the provider's run-to-run drift"
               + (f"; about {sp['runs_needed']} runs a side would show a change of the size measured." if sp["runs_needed"] else "."))
        )
    else:
        out.append("**Recommendation:** Priming changed nothing measurable here; leaving it off costs nothing.")
    if q == "degraded":
        return out
    rec, cands = lever["recommended"], lever["candidates"]
    if not rec:
        out.append("**No arm is a lever:** none keeps skill selection within the Golden Set's noise of today's while deciding "
                   "faster, so the remaining time has to come from elsewhere.")
        return out
    c, thinking_off = cands[rec], cands.get("main-no-thinking")
    projection = ""
    if c["turn_saving_ms"] is not None:
        projection = (f" At {v['calls_per_turn_on']:.1f} model calls a turn and {c['faster_ms'] / 1000:.1f} s saved per decision, "
                      f"that is roughly {c['turn_saving_ms'] / 1000:.1f} s a turn, a turn p50 near {_s(c['projected_p50_ms'])}"
                      + (" — short of the 6 s #14 aimed at, on its own." if c["projected_p50_ms"] and c["projected_p50_ms"] > TARGET_P50_MS
                         else "."))
    out.append(
        f"**The next lever is `{rec}`:** it chooses skills within the Golden Set's noise of the main model with thinking on "
        "and decides faster." + projection
        + (f" Turning thinking off is not the lever: it loses {thinking_off['f1_gap'] * 100:.0f} points of skill F1."
           if thinking_off and not thinking_off["viable"] and rec != "main-no-thinking" else "")
        + " Evaluate it as the main model on the behaviour cases and the Golden Set, with the judge watching what it says as "
          "well as what it calls; adopting it is a separate decision."
    )
    return out


def render(v: dict[str, Any], out: Path) -> tuple[Path, Path]:
    q, c, sp, lat, use = v["quality"], v["claims"], v["speed"], v["latency"], v["priming_use"]
    settings = v["priming"] or {}
    fr, rounds, dec, slow = c["first_response"], c["rounds"], c["decider"], c["slower"]
    credit = q["first_action_credit"]
    lt, lc = lat["turn"], lat["case"]
    paired_off = ", ".join(map(str, v["paired_first_turns"]["off"])) or "—"
    paired_on = ", ".join(map(str, v["paired_first_turns"]["on"])) or "—"
    quality_line = {
        "held": (f"Every run with Priming on is within the noise of the runs with it off ({q['noise']['first_action']:.0%} of "
                 f"first-action accuracy, {q['noise']['judge']:.2f} of the judge's mean) and nothing leaked: quality held."
                 if q["noise"] else "Quality held."),
        "degraded": f"Outside the noise: {', '.join(q['runs_outside_noise']) or 'none'}; leaks with Priming on: {q['leaks']['on']}. "
                    "Quality did not hold.",
        "incomplete": "Some runs had errored cases, so the comparison is incomplete.",
    }[q["status"]]
    rounds_note = ""
    if rounds["turns"] and rounds["held"] and rounds["dropped_by_one_or_more"] < rounds["turns"]:
        rounds_note = ("The rounds claim holds on average: a turn's rounds also move with what the model decides to look up, "
                       "so some turns keep a round for other reasons. ")
    elif rounds["turns"] and not rounds["held"]:
        rounds_note = "The rounds claim does not hold: on average less than a round went away where a skill-only round existed. "
    went, rest = sp["where_a_round_went"], sp["elsewhere"]
    if went["decided"] and rest["decided"]:
        mechanism = ("saved no more than the other turns did, so these runs cannot tie a latency change to the round that "
                     "went." if went["delta"] >= rest["delta"] else
                     "saved more than the other turns, as that reasoning predicts.")
    else:
        mechanism = "are too few to compare with the rest."
    lines = [
        "# The Priming verdict",
        "",
        f"{len(v['off_runs'])} runs of the nineteen behaviour cases with Priming off and {len(v['on_runs'])} with it on, at "
        f"threshold {settings.get('threshold')}, margin {settings.get('margin')}, Decider {settings.get('decider')} — the "
        f"defaults #18 fitted. {headline(v)}",
        "",
        "## 1. Quality must not degrade",
        "",
        "| | Priming off | Priming on |",
        "|---|---|---|",
        f"| First-action accuracy | {_pct(q['first_action']['off'])} | {_pct(q['first_action']['on'])} |",
        f"| Judge mean | {_two(q['judge']['off'])} | {_two(q['judge']['on'])} |",
        f"| Leaks | {q['leaks']['off']} | {q['leaks']['on']} |",
        f"| Runs with errored cases | {sum(1 for n in q['errored_runs'] if n in v['off_runs'])} | "
        f"{sum(1 for n in q['errored_runs'] if n in v['on_runs'])} |",
        "",
        quality_line,
        "",
        f"First-action accuracy is not measured quite the same way on both sides: with Priming on, a primed skill counts as "
        f"the first move. Of the {credit['passes']} passes with Priming on, {credit['decided_by_priming']} rest on that credit — "
        "the model's own first response would not have matched. So that row mostly says whether the right skill got in first; "
        "the judge says what the model then did with it.",
        "",
        "## 2. The committed claims, turn by turn",
        "",
        "| Claim (#14) | Measured | Held |",
        "|---|---|---|",
        f"| On a primed turn the first response does not reload a primed skill | {fr['reloaded_a_primed_skill']} of "
        f"{fr['primed_turns']} primed turns did; {fr['loaded_a_skill_priming_missed']} loaded a skill Priming missed, the "
        f"fallback | {_mark(fr['held'])} |",
        "| Tool rounds drop by one where a skill-only round existed | "
        + ("no such turns" if rounds["mean_drop"] is None else
           f"mean drop {rounds['mean_drop']:.1f} over {rounds['turns']} such turns; {rounds['dropped_by_one_or_more']} dropped a full round")
        + f" | {_mark(rounds['held'])} |",
        f"| The Decider spends ≤ {DECIDER_BUDGET_MS / 1000:.1f} s at p95 | p95 {_s(dec['p95_ms'])}, p50 {_s(dec['p50_ms'])}, max "
        f"{_s(dec['max_ms'])} over {dec['asked']} asks | {_mark(dec['held'])} |",
        f"| No turn is slower with Priming on | {slow['slower_by_median']} of {slow['matched']} turns slower by median; "
        f"{len(slow['slower_in_every_run'])} slower in every run, where chance alone gives {slow['expected_by_chance']:.1f} "
        f"(as many or more by chance: p = {slow['chance_p']:.2f}) | {_mark(slow['held'])} |",
        "",
        rounds_note + f"The last claim is a weak test with {len(v['on_runs'])} runs with Priming on and {len(v['off_runs'])} off: "
        f"chance alone produces {slow['expected_by_chance']:.1f} turns slower in every run, so only a slowdown on many turns "
        "would show.",
    ]
    if slow["slower_in_every_run"]:
        lines += ["", "Turns slower in every run with Priming on:", "",
                  "| Case | Turn | Off (ms) | On (ms) | Decider (ms) | Rounds off | Rounds on | Primed | Fewer rounds, yet slower |",
                  "|---|---|---|---|---|---|---|---|---|"]
        lines += [f"| {t['case']} | {t['turn']} | {', '.join(map(str, t['off_ms']))} | {', '.join(map(str, t['on_ms']))} | "
                  f"{', '.join(map(str, t['decider_ms']))} | {', '.join(map(str, t['off_rounds']))} | {', '.join(map(str, t['on_rounds']))} | "
                  f"{'; '.join(', '.join(p) or '—' for p in t['primed'])} | {'yes' if t['fewer_rounds_yet_slower'] else 'no'} |"
                  for t in slow["slower_in_every_run"]]
        if any(t["fewer_rounds_yet_slower"] for t in slow["slower_in_every_run"]):
            lines += ["", "A turn with fewer rounds that is still slower spent its time elsewhere — in reasoning or in the "
                          "reply — which these metrics do not separate; the Decider's own time there is in the table."]
    lines += [
        "",
        "## 3. Speed and rounds",
        "",
        "Each turn with Priming on minus the same turn with it off, averaged over turns. The interval resamples the runs of "
        "each mode as well as the turns, because whole runs differ from one another.",
        "",
        "| | Change per turn | |",
        "|---|---|---|",
        f"| Turn latency | {_interval(sp['latency'])} | {'faster' if sp['faster'] else 'slower' if sp['slower'] else 'not established'} |",
        f"| Tool rounds | {_interval(sp['rounds'], unit='rounds')} | {'fewer' if sp['fewer_rounds'] else 'not established'} |",
        f"| Latency where a skill-only round existed and Priming primed | {_interval(went)} | |",
        f"| Latency on the other turns | {_interval(rest)} | |",
        "",
        "Mean turn latency per run: with Priming off " + (", ".join(_s(m) for m in sp["run_means_ms"]["off"]) or "—")
        + "; with it on " + (", ".join(_s(m) for m in sp["run_means_ms"]["on"]) or "—") + "."
        + (f" At that run-to-run spread, about {sp['runs_needed']} runs a side would separate a change of the size measured."
           if sp["runs_needed"] and not sp["faster"] else ""),
        "",
        "| | Priming off | Priming on |",
        "|---|---|---|",
        f"| Turn latency p50 / p90 | {_s(lt['off']['p50_ms'])} / {_s(lt['off']['p90_ms'])} | {_s(lt['on']['p50_ms'])} / {_s(lt['on']['p90_ms'])} |",
        f"| Case latency p50 / p90 (#14's baseline: {_s(SPEC_CASE_P50_MS)} / {_s(SPEC_CASE_P90_MS)}) | "
        f"{_s(lc['off']['p50_ms'])} / {_s(lc['off']['p90_ms'])} | {_s(lc['on']['p50_ms'])} / {_s(lc['on']['p90_ms'])} |",
        f"| First turns pairing `Skill` with a tool it informs, per run (#14: {SPEC_PAIRED_FIRST_TURNS} of 19) | {paired_off} | "
        f"{paired_on} |",
        f"| Turns primed | — | {use['primed']} of {use['turns']} ({_pct(use['share_primed'])}) |",
        f"| Primed turns asking again for a skill already in context | — | {use['primed_turns_asking_again']} "
        f"({_pct(use['asking_again_rate'])}) |",
        "",
        "Why the other turns were not primed: " + (", ".join(f"{reason} {n}" for reason, n in use["skip_reasons"].items()) or "—") + ".",
        "",
        f"#14 expected p90 to improve while p50 stayed near where it was. The runs with Priming off disagree by "
        f"{_s(lat['turn_p50_spread_off_ms'])} at turn p50 and {_s(lat['turn_p90_spread_off_ms'])} at turn p90, so pooled "
        "percentiles cannot confirm or refute that expectation; the paired change above is the measure, and it is "
        + ("below zero." if sp["faster"] else "not yet separated from zero.")
        + " #14 also reasoned that removing a round saves that round's time; here the turns that lost a skill-only round "
        + mechanism,
        "",
        f"The first-turn pairing with Priming off ran {paired_off} of 19 in these runs against #14's {SPEC_PAIRED_FIRST_TURNS}, "
        f"so part of that drop had happened before Priming; with Priming on it is {paired_on}.",
        "",
        "## 4. Recommendations",
        "",
        "Skill selection on the Golden Set (#17, development and held-out averaged):",
        "",
        "| Arm | Skill F1 | Skill recall | Decision p50 | Tool recall |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {arm} | {_pct(a['f1'])} | {_pct(a['recall'])} | {_s(a['p50_ms'])} | {_pct(a['tool_recall'])} |"
              for arm, a in v["arms"].items()]
    for paragraph in recommendation(v):
        lines += ["", paragraph]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    js = out.with_suffix(".json")
    js.write_text(json.dumps(v, indent=1), encoding="utf-8")
    return out, js


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.verdict", description=__doc__.split("\n\n")[0])
    parser.add_argument("--off", default=",".join(OFF_RUNS), help="behaviour-case reports with Priming off")
    parser.add_argument("--on", default=",".join(ON_RUNS), help="behaviour-case reports with Priming on at the defaults")
    args = parser.parse_args(argv)
    off_names, on_names = [n.strip() for n in args.off.split(",")], [n.strip() for n in args.on.split(",")]
    shipped = HarnessConfig()
    defaults = {"threshold": shipped.priming_threshold, "margin": shipped.priming_margin, "decider": shipped.decider_model}
    for run in load_runs(on_names, REPORTS_DIR):
        if run["priming"] != defaults:
            print(f"{run['name']} was not made at the configured defaults {defaults}", flush=True)
            return 2
    for run in load_runs(off_names, REPORTS_DIR):
        if run["priming"] is not None:
            print(f"{run['name']} was made with Priming on", flush=True)
            return 2
    md, _ = render(verdict(off_names, on_names, REPORTS_DIR), REPORTS_DIR / "priming-verdict.md")
    print(f"report: {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
