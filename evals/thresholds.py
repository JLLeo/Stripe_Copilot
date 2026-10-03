"""
Priming's threshold and margin, fitted from measured costs (#18).

Fitted on the Golden Set's development split, published on the held-out split.
The development numbers are shown only as the curve the values were read from;
every figure given as a result comes from the held-out cases, at the values the
configuration ships (`HarnessConfig`'s defaults), so what is reported is what
runs. Every sentence that states a conclusion is computed from the data, so the
report cannot say one thing while its tables say another.

The fit reads recorded data only. A Decider-only Golden Set run per split keeps
the probability for every skill the Decider was asked about, so no rule or
threshold needs another call:

1. **Calibration.** Does 0.7 mean the same thing for `billing` as for `terminal`?
   Reliability bins and the expected calibration error (ECE) per skill, then the
   deciding test under leave-one-case-out cross-validation: does a log-odds
   shift per skill — one parameter each, shrunk toward the shift every skill
   shares — predict held-back cases better than the shared shift alone? A shared
   shift changes no ranking and is the same as moving the threshold, which is
   fitted anyway, so only a difference between skills calls for a correction.
2. **The decision curve.** For each selection rule, threshold and margin: the
   Skill rounds saved and the seconds they took, against the primes that were
   wrong and the required skills that were missed. A round counts as saved when
   every required skill was primed on a case whose baseline first response (the
   main model with thinking on, from the four-arm run) loaded skills and called
   nothing a skill informs — #14's "a Skill load alone, or with only a local
   profile read", the rounds that buy nothing the customer can see. The
   asymmetry: a missed prime costs one round, the one Priming was meant to save;
   a wrong prime costs its body in tokens and some bias toward that area.
3. **Quality.** Rounds saved are worth nothing if the replies get worse. The
   nineteen behaviour cases run with Priming off (twice, to measure the noise)
   and on at candidate settings, each written to its own report
   (`EVAL_REPORT=<name> pytest -m eval`). A run qualifies when first-action
   accuracy and the judge's mean fall by no more than that noise, nothing leaks
   and no case errors.

The operating point (`operating_point`) is the curve's best point among the
settings whose behaviour run qualified: the most rounds saved, then the fewest
wrong primes, then the higher threshold, then the smaller margin.

    python -m evals.thresholds        # reads evals/reports/, writes priming-thresholds.md, its JSON and two SVGs
"""

from __future__ import annotations

import argparse
import html
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.harness import priming
from app.harness.context import estimate_tokens
from app.harness.core import HarnessConfig
from app.harness.skills import load_skills
from evals.golden import Labels, micro
from evals.runner import REPORTS_DIR

THRESHOLDS = tuple(round(0.30 + 0.05 * i, 2) for i in range(13))  # 0.30 … 0.90
MARGINS = tuple(round(0.05 * i, 2) for i in range(1, 9))  # 0.05 … 0.40
BINS = 10
SHRINK = 1.0  # the prior's standard deviation on a skill's own shift, in log-odds
CORRECTION_GAIN = 0.05  # eleven extra parameters on forty cases must cut held-back log-loss by this share to earn their place
CLIP = 1e-4
# About one standard error of a nineteen-case judge mean: per-case scores spread by ~0.95 in the runs with Priming off.
JUDGE_NOISE_FLOOR = 0.20
BEFORE_18 = (0.55, 0.15)  # the threshold and margin #16 shipped
PRODUCTION = "top two within the margin"
BEHAVIOUR_RUNS = ["behaviour-off-a", "behaviour-off-b", "behaviour-t045", "behaviour-t055", "behaviour-t065"]


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Turn:
    """One Golden Set case as the fit sees it."""

    id: str
    cell: str
    probabilities: dict[str, float]  # every skill the Decider was asked about; empty when it failed
    skills: Labels
    decider_ms: int
    baseline_round_ms: int | None  # the main model's first round when it bought nothing the customer could see


def load_turns(decider_report: Path, baseline_report: Path) -> list[Turn]:
    """The Decider's answers from one Golden Set report, and the main model's first round from the four-arm run.

    A Decider failure stays in with no probabilities, so every rule primes nothing on it, as production would.
    """
    decider = json.loads(decider_report.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_report.read_text(encoding="utf-8"))
    rounds = {
        d["case_id"]: d["latency_ms"] for d in baseline["decisions"]
        if d["arm"] == "main-thinking" and d["error"] is None and d["skills"] and not d["paired"]
    }
    labels = {c["id"]: c for c in decider["cases"]}
    return [
        Turn(
            id=d["case_id"], cell=d["cell"], probabilities=d["probabilities"], decider_ms=d["latency_ms"],
            skills=Labels(required=tuple(tuple(a) for a in labels[d["case_id"]]["skills"]["required"]),
                          acceptable=tuple(labels[d["case_id"]]["skills"]["acceptable"])),
            baseline_round_ms=rounds.get(d["case_id"]),
        )
        for d in decider["decisions"] if d["arm"] == "decider"
    ]


# ---------------------------------------------------------------------------
# 1. Calibration
# ---------------------------------------------------------------------------
def pairs_by_skill(turns: list[Turn]) -> dict[str, list[tuple[str, float, int]]]:
    """(case, probability, outcome) per skill: 1 when the skill was required, 0 when outside both layers.
    A skill that was only acceptable says nothing about whether the probability was right, so it is left out."""
    out: dict[str, list[tuple[str, float, int]]] = {}
    for turn in turns:
        required = {n for alternatives in turn.skills.required for n in alternatives}
        for skill, p in turn.probabilities.items():
            if skill in required:
                out.setdefault(skill, []).append((turn.id, p, 1))
            elif skill not in turn.skills.allowed:
                out.setdefault(skill, []).append((turn.id, p, 0))
    return dict(sorted(out.items()))


def reliability(pairs: list[tuple[str, float, int]], bins: int = BINS) -> list[dict[str, float]]:
    """Per probability bin: how many, the mean probability, and how often the skill was in fact required."""
    rows = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        inside = [(p, y) for _, p, y in pairs if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if inside:
            rows.append({"lo": lo, "hi": hi, "n": len(inside), "mean_p": sum(p for p, _ in inside) / len(inside),
                         "observed": sum(y for _, y in inside) / len(inside)})
    return rows


def ece(pairs: list[tuple[str, float, int]], bins: int = BINS) -> float:
    total = len(pairs)
    return sum(r["n"] / total * abs(r["mean_p"] - r["observed"]) for r in reliability(pairs, bins)) if total else 0.0


def _logit(p: float) -> float:
    p = min(max(p, CLIP), 1 - CLIP)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def fit_shift(pairs: list[tuple[str, float, int]], shrink: float = SHRINK, centre: float = 0.0) -> float:
    """The one parameter: a shift in log-odds maximising the likelihood under a normal prior at `centre`.

    Newton's method with each step capped at one unit of log-odds, so a skill whose every outcome went one
    way converges instead of oscillating; the objective is strictly concave, so the cap only slows it down.
    """
    b = centre
    for _ in range(200):
        grad, hess = -(b - centre) / shrink ** 2, -1 / shrink ** 2
        for _, p, y in pairs:
            q = _sigmoid(_logit(p) + b)
            grad += y - q
            hess -= q * (1 - q)
        step = max(-1.0, min(1.0, grad / hess))
        b -= step
        if abs(step) < 1e-9:
            break
    return b


def _loss(p: float, y: int) -> float:
    p = min(max(p, CLIP), 1 - CLIP)
    return -math.log(p if y else 1 - p)


def cross_validated(by_skill: dict[str, list[tuple[str, float, int]]]) -> dict[str, float]:
    """Mean log-loss, each case predicted by shifts fitted without it: raw; one shared shift; a shift per skill,
    shrunk toward that shared shift, so the per-skill model nests the shared one and the comparison isolates
    what differs between skills."""
    pooled = [q for pairs in by_skill.values() for q in pairs]
    shared_without = {case: fit_shift([q for q in pooled if q[0] != case]) for case in {q[0] for q in pooled}}
    raw = shared = per_skill = 0.0
    for pairs in by_skill.values():
        for case_id, p, y in pairs:
            centre = shared_without[case_id]
            own = fit_shift([q for q in pairs if q[0] != case_id], centre=centre)
            raw += _loss(p, y)
            shared += _loss(_sigmoid(_logit(p) + centre), y)
            per_skill += _loss(_sigmoid(_logit(p) + own), y)
    n = len(pooled)
    return {"pairs": n, "raw": raw / n if n else 0.0, "shared_shift": shared / n if n else 0.0,
            "per_skill_shift": per_skill / n if n else 0.0}


def calibration(turns: list[Turn]) -> dict[str, Any]:
    by_skill = pairs_by_skill(turns)
    pooled = [q for pairs in by_skill.values() for q in pairs]
    shared = fit_shift(pooled)
    cv = cross_validated(by_skill)
    gain = (cv["shared_shift"] - cv["per_skill_shift"]) / cv["shared_shift"] if cv["shared_shift"] else 0.0
    return {
        "pooled": {"pairs": len(pooled), "ece": ece(pooled), "bins": reliability(pooled), "shared_shift": shared},
        "skills": {
            skill: {"pairs": len(pairs), "required": sum(y for _, _, y in pairs), "ece": ece(pairs),
                    "shift": fit_shift(pairs, centre=shared)}
            for skill, pairs in by_skill.items()
        },
        "cross_validated": cv,
        "gain": gain,
        "correction_called_for": gain >= CORRECTION_GAIN,
    }


# ---------------------------------------------------------------------------
# 2. Rules and the decision curve
# ---------------------------------------------------------------------------
Choose = Callable[[dict[str, float], float, float], tuple[list[str], str | None]]


@dataclass(frozen=True)
class Rule:
    name: str
    choose: Choose
    margins: tuple[float, ...]  # (0.0,) for a rule without a margin


def _top_one_when_clear(probabilities: dict[str, float], threshold: float, margin: float) -> tuple[list[str], str | None]:
    """The rule #16 shipped: three or more above the threshold prime the top one only if it leads the third by the margin."""
    order = priming.ranked(probabilities)
    above = [name for name, p in order if p >= threshold]
    if not above:
        return [], priming.SKIP_BELOW_THRESHOLD
    if len(above) <= priming.MAX_PRIMED:
        return above, None
    return ([order[0][0]], None) if order[0][1] - order[2][1] >= margin else ([], "flat")


def _top_two(probabilities: dict[str, float], threshold: float, margin: float) -> tuple[list[str], str | None]:
    """No margin at all: the two most probable above the threshold."""
    above = [name for name, p in priming.ranked(probabilities) if p >= threshold]
    return (above[: priming.MAX_PRIMED], None) if above else ([], priming.SKIP_BELOW_THRESHOLD)


RULES = {r.name: r for r in (
    Rule("top one when clear (#16)", _top_one_when_clear, MARGINS),
    Rule(PRODUCTION, priming.choose, MARGINS),
    Rule("top two", _top_two, (0.0,)),
)}


def evaluate(turns: list[Turn], choose: Choose, threshold: float, margin: float, body_tokens: dict[str, int]) -> dict[str, Any]:
    """One point on the curve."""
    scores, saved, saved_ms, wrong, wrong_tokens = [], 0, 0, 0, 0
    for turn in turns:
        chosen, _ = choose(turn.probabilities, threshold, margin)
        score = turn.skills.score(chosen)
        scores.append(score)
        outside = [s for s in chosen if s not in turn.skills.allowed]
        wrong += len(outside)
        wrong_tokens += sum(body_tokens[s] for s in outside)
        if score.required and score.found == score.required and turn.baseline_round_ms is not None:
            saved += 1
            saved_ms += turn.baseline_round_ms
    layer = micro(scores)
    return {
        "threshold": threshold, "margin": margin, "cases": len(turns),
        "exact": layer["exact"], "precision": layer["precision"], "recall": layer["recall"],
        # Only a round that bought nothing, on a turn that needs a skill, can be saved by priming one.
        "rounds_saved": saved, "rounds_to_save": sum(1 for t in turns if t.baseline_round_ms is not None and t.skills.required),
        "seconds_saved": saved_ms / 1000, "decider_seconds": sum(t.decider_ms for t in turns) / 1000,
        "wrong_primes": wrong, "wrong_prime_tokens": wrong_tokens, "missed": sum(s.required - s.found for s in scores),
    }


def curve(turns: list[Turn], body_tokens: dict[str, int]) -> dict[str, list[dict[str, Any]]]:
    """Every rule at every threshold, and at every margin of a rule that has one."""
    return {name: [evaluate(turns, rule.choose, t, m, body_tokens) for m in rule.margins for t in THRESHOLDS]
            for name, rule in RULES.items()}


def _rank(point: dict[str, Any]) -> tuple:
    return point["rounds_saved"], -point["wrong_primes"], point["threshold"], -point["margin"]


def best(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Most rounds saved; then fewest wrong primes; then the higher threshold, which primes less; then the smaller margin."""
    return max(points, key=_rank)


def best_per_threshold(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For a rule with a margin, the best margin at each threshold: the curve worth drawing."""
    return [best([p for p in points if p["threshold"] == t]) for t in THRESHOLDS]


def plateau_margins(points: list[dict[str, Any]], threshold: float) -> list[float]:
    """The margins that do exactly as well as the best one at `threshold`."""
    here = [p for p in points if p["threshold"] == threshold]
    if not here:
        return []
    top = best(here)
    return [p["margin"] for p in here
            if (p["rounds_saved"], p["wrong_primes"], p["missed"]) == (top["rounds_saved"], top["wrong_primes"], top["missed"])]


# ---------------------------------------------------------------------------
# 3. Quality on the behaviour cases
# ---------------------------------------------------------------------------
def behaviour(names: list[str], reports: Path = REPORTS_DIR) -> list[dict[str, Any]]:
    """The behaviour-case reports written by `EVAL_REPORT=<name> pytest -m eval`, in the order given; missing ones are skipped."""
    rows = []
    for name in names:
        path = reports / f"{name}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        s, settings = data["summary"], data.get("priming")
        rows.append({
            "name": name, "priming": settings,
            "threshold": settings["threshold"] if settings else None, "margin": settings["margin"] if settings else None,
            "cases": s["cases"], "errors": s["errors"], "first_action": s["first_action_accuracy"],
            "judge": s["mean_judge_score"], "leak_free": s["leak_free"], "turns": s["turns"], "primed_turns": s["primed_turns"],
            "tool_rounds": s["tool_rounds"], "p50_ms": s["turn_p50_ms"], "p90_ms": s["turn_p90_ms"],
            "redundant_skill_calls": s["redundant_skill_calls"],
        })
    return rows


def quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Each run with Priming on against the runs with it off, which also set the noise.

    The noise is the spread between the runs with Priming off, never below one case of first-action accuracy
    or `JUDGE_NOISE_FLOOR` of the judge's mean. A run is within noise when neither number falls by more than
    that, nothing leaked and no case errored (an errored case is not a comparable case). Rounds and latency
    are reported against the same baseline; they are what Priming is for, not a test it must pass.
    """
    off = [r for r in rows if r["priming"] is None and r["judge"] is not None]
    if not off:
        return {"baseline": None, "noise": None, "runs": []}

    def mean(key: str) -> float:
        return sum(r[key] for r in off) / len(off)

    def spread(key: str) -> float:
        return max(r[key] for r in off) - min(r[key] for r in off)

    keys = ("judge", "first_action", "tool_rounds", "p50_ms", "p90_ms")
    cases = max(r["cases"] for r in off)
    baseline = {k: mean(k) for k in keys} | {"runs": len(off)}
    noise = {"judge": max(JUDGE_NOISE_FLOOR, spread("judge")), "first_action": max(1 / cases, spread("first_action")),
             "p50_ms": spread("p50_ms"), "p90_ms": spread("p90_ms")}
    runs = []
    for r in rows:
        if r["priming"] is None or r["judge"] is None:
            continue
        delta = {f"d_{k}": r[k] - baseline[k] for k in keys}
        complete = r["errors"] == 0 and r["leak_free"] == r["cases"]
        runs.append({**r, **delta, "complete": complete,
                     "within_noise": complete and delta["d_judge"] >= -noise["judge"] and delta["d_first_action"] >= -noise["first_action"]})
    return {"baseline": baseline, "noise": noise, "runs": runs}


def operating_point(points: list[dict[str, Any]], checked: dict[str, Any]) -> dict[str, Any] | None:
    """The curve's best point among the (threshold, margin) settings whose behaviour run kept quality within noise."""
    qualified = {(r["threshold"], r["margin"]) for r in checked["runs"] if r["within_noise"]}
    candidates = [p for p in points if (p["threshold"], p["margin"]) in qualified]
    return best(candidates) if candidates else None


# ---------------------------------------------------------------------------
# The fit
# ---------------------------------------------------------------------------
def fit(dev: list[Turn], dev_before: list[Turn] | None, held_out: list[Turn], held_out_before: list[Turn] | None,
        rows: list[dict[str, Any]], config: HarnessConfig, body_tokens: dict[str, int]) -> dict[str, Any]:
    """Everything the report states, computed. `*_before` are the same splits as the Decider answered them before
    #18 told it when the customer is a new prospect."""
    fitted = curve(dev, body_tokens)
    production, old = RULES[PRODUCTION], RULES["top one when clear (#16)"]
    shipped = (config.priming_threshold, config.priming_margin)
    checked = quality(rows)
    choice = operating_point(fitted[PRODUCTION], checked)
    run = {(r["threshold"], r["margin"]) for r in checked["runs"]}

    def at(turns: list[Turn] | None, rule: Rule, setting: tuple[float, float]) -> dict[str, Any] | None:
        return evaluate(turns, rule.choose, *setting, body_tokens) if turns else None

    return {
        "fitting_split": "dev", "published_split": "test",
        "shipped": {"threshold": shipped[0], "margin": shipped[1], "rule": PRODUCTION},
        "calibration": calibration(dev),
        "curve": fitted,
        "behaviour_rows": rows,
        "quality": checked,
        "choice": choice,
        "shipped_is_choice": bool(choice) and (choice["threshold"], choice["margin"]) == shipped,
        "plateau_margins": plateau_margins(fitted[PRODUCTION], shipped[0]),
        # Settings never run on the behaviour cases that would rank above the choice: only these could change it.
        "outranking_unrun": [{"threshold": p["threshold"], "margin": p["margin"]} for p in fitted[PRODUCTION]
                             if choice and (p["threshold"], p["margin"]) not in run and _rank(p) > _rank(choice)],
        "held_out": {
            "shipped": at(held_out, production, shipped),
            "rule_before_18": at(held_out, old, BEFORE_18),
            "state_before_18": at(held_out_before, production, shipped),
            "before_18": at(held_out_before, old, BEFORE_18),
        },
        "development": {
            "shipped": at(dev, production, shipped),
            "rule_before_18": at(dev, old, BEFORE_18),
            "state_before_18": at(dev_before, production, shipped),
        },
    }


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
def _svg_chart(path: Path, title: str, x_label: str, y_label: str, series: dict[str, list[tuple[float, float]]],
               x_range: tuple[float, float], y_range: tuple[float, float], diagonal: bool = False,
               marks: list[float] | None = None) -> None:
    """A small dependency-free line chart, readable on GitHub."""
    w, h, left, bottom, top, right = 720, 340, 56, 44, 34, 290  # the legend's labels are long
    pw, ph = w - left - right, h - top - bottom
    (x0, x1), (y0, y1) = x_range, y_range
    x1, y1 = (x1 if x1 > x0 else x0 + 1), (y1 if y1 > y0 else y0 + 1)
    esc = html.escape

    def px(x: float) -> float:
        return left + (x - x0) / (x1 - x0) * pw

    def py(y: float) -> float:
        return top + ph - (y - y0) / (y1 - y0) * ph

    colours = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" font-family="sans-serif" font-size="11">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{left}" y="18" font-size="13" font-weight="bold">{esc(title)}</text>',
        f'<line x1="{left}" y1="{top + ph}" x2="{left + pw}" y2="{top + ph}" stroke="#333"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + ph}" stroke="#333"/>',
        f'<text x="{left + pw / 2}" y="{h - 8}" text-anchor="middle">{esc(x_label)}</text>',
        f'<text x="14" y="{top + ph / 2}" text-anchor="middle" transform="rotate(-90 14 {top + ph / 2})">{esc(y_label)}</text>',
    ]
    for i in range(6):
        xv, yv = x0 + (x1 - x0) * i / 5, y0 + (y1 - y0) * i / 5
        parts += [
            f'<text x="{px(xv)}" y="{top + ph + 16}" text-anchor="middle">{xv:.2f}</text>',
            f'<text x="{left - 6}" y="{py(yv) + 4}" text-anchor="end">{yv:.2g}</text>',
            f'<line x1="{left}" y1="{py(yv)}" x2="{left + pw}" y2="{py(yv)}" stroke="#eee"/>',
        ]
    if diagonal:
        parts.append(f'<line x1="{px(x0)}" y1="{py(y0)}" x2="{px(x1)}" y2="{py(y1)}" stroke="#999" stroke-dasharray="4 3"/>')
    for x in marks or []:
        parts.append(f'<line x1="{px(x)}" y1="{top}" x2="{px(x)}" y2="{top + ph}" stroke="#555" stroke-dasharray="2 3"/>')
    for i, (name, points) in enumerate(series.items()):
        colour = colours[i % len(colours)]
        coords = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in points)
        parts.append(f'<polyline points="{coords}" fill="none" stroke="{colour}" stroke-width="2"/>')
        parts += [f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="2.5" fill="{colour}"/>' for x, y in points]
        parts.append(f'<rect x="{left + pw + 12}" y="{top + 16 * i}" width="10" height="10" fill="{colour}"/>')
        parts.append(f'<text x="{left + pw + 26}" y="{top + 16 * i + 9}">{esc(name)}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.0%}"


def _s(ms: float | None) -> str:
    return "—" if ms is None else f"{ms / 1000:.1f} s"


def _calibration_lines(cal: dict[str, Any], reliability_svg: Path) -> list[str]:
    shared = cal["pooled"]["shared_shift"]
    cv = cal["cross_validated"]
    lines = [
        "### 1. Calibration",
        "",
        f"Pooled over skills: {cal['pooled']['pairs']} (case, skill) pairs, ECE {cal['pooled']['ece']:.3f}. One log-odds "
        f"shift shared by every skill fits at {shared:+.2f}"
        + (" — the Decider is over-confident overall." if shared < 0 else " — the Decider is under-confident overall." if shared > 0 else ".")
        + f" Leave-one-case-out log-loss: raw {cv['raw']:.3f}; the shared shift {cv['shared_shift']:.3f}; a shift per skill "
        f"around it {cv['per_skill_shift']:.3f} ({cal['gain']:+.1%} on the shared one). A shared shift changes no ranking — it "
        "is the same as moving the threshold, which is fitted below — so only the per-skill gain matters. "
        + (f"It reaches the {CORRECTION_GAIN:.0%} a per-skill parameter must earn: skills differ beyond chance, and a per-skill "
           "correction is called for. **This fit does not apply one**; the curve below uses raw probabilities and should not "
           "be relied on until it does."
           if cal["correction_called_for"] else
           f"It falls short of the {CORRECTION_GAIN:.0%} a per-skill parameter must earn, so the per-skill shifts in the "
           "table are what this many cases look like by chance: a probability is taken to mean the same for every skill, "
           "and no correction is applied."),
        "",
        f"![Reliability]({reliability_svg.name})",
        "",
        "| Skill | Pairs | Required | ECE | Its own shift (log-odds, around the shared one) |",
        "|---|---|---|---|---|",
    ]
    return lines + [f"| {s} | {v['pairs']} | {v['required']} | {v['ece']:.3f} | {v['shift']:+.2f} |" for s, v in cal["skills"].items()]


def _quality_lines(result: dict[str, Any]) -> list[str]:
    checked = result["quality"]
    if not result["behaviour_rows"]:
        return ["No behaviour-case runs were found in evals/reports/."]
    verdicts = {r["name"]: r for r in checked["runs"]}
    lines = [
        "| Run | Priming | First action | Judge mean | Leak-free | Errors | Turns primed | Tool rounds | Turn p50 | Turn p90 | Within noise |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in result["behaviour_rows"]:
        v = verdicts.get(r["name"])
        judge = "—" if r["judge"] is None else f"{r['judge']:.2f}" + (f" ({v['d_judge']:+.2f})" if v else "")
        rounds = f"{r['tool_rounds']}" + (f" ({v['d_tool_rounds']:+.0f})" if v else "")
        p50 = _s(r["p50_ms"]) + (f" ({v['d_p50_ms'] / 1000:+.1f})" if v else "")
        p90 = _s(r["p90_ms"]) + (f" ({v['d_p90_ms'] / 1000:+.1f})" if v else "")
        within = "baseline" if r["priming"] is None else ("✓" if v and v["within_noise"] else "✗")
        setting = "off" if r["priming"] is None else f"{r['threshold']} / {r['margin']}"
        lines.append(
            f"| {r['name']} | {setting} | {_pct(r['first_action'])} | {judge} | {r['leak_free']}/{r['cases']} | {r['errors']} | "
            f"{r['primed_turns']}/{r['turns']} | {rounds} | {p50} | {p90} | {within} |"
        )
    b, n = checked["baseline"], checked["noise"]
    if b:
        lines += ["", (
            f"Changes are against the mean of the {b['runs']} runs with Priming off. Noise: {n['first_action']:.0%} of first-action "
            f"accuracy and {n['judge']:.2f} of the judge's mean — their spread, or one case and {JUDGE_NOISE_FLOOR:.2f} (about one "
            f"standard error of a nineteen-case mean) if they agreed more closely. Between those two runs turn p50 moved "
            f"{_s(n['p50_ms'])} and turn p90 {_s(n['p90_ms'])}, so latency differences smaller than that say nothing. A skill "
            "Priming put in counts as a first action, so first-action accuracy here says whether the right skill got in first; "
            "the judge says what the model then did with it."
        )]
    return lines


def _choice_lines(result: dict[str, Any]) -> list[str]:
    checked, choice, shipped = result["quality"], result["choice"], result["shipped"]
    within = sorted((r["threshold"], r["margin"]) for r in checked["runs"] if r["within_noise"])
    outside = sorted((r["threshold"], r["margin"]) for r in checked["runs"] if not r["within_noise"])
    lines = [(
        "Quality within noise at " + (", ".join(f"{t} / {m}" for t, m in within) or "no setting that was run")
        + (f"; outside it at {', '.join(f'{t} / {m}' for t, m in outside)}" if outside else "") + ". "
        + (f"Among those, the curve's best point is threshold {choice['threshold']}, margin {choice['margin']}: "
           f"{choice['rounds_saved']} of {choice['rounds_to_save']} Skill rounds saved on the development split, with "
           f"{choice['wrong_primes']} wrong primes and {choice['missed']} missed."
           if choice else "No setting qualified, so the curve offers nothing to ship.")
        + (" **These are the shipped values.**" if result["shipped_is_choice"] else
           f" **The shipped values ({shipped['threshold']} / {shipped['margin']}) are not this point.**")
    )]
    if choice:
        unrun = result["outranking_unrun"]
        lines += ["", (
            "No setting without a behaviour run ranks above this point on the curve, so running more could not change the "
            "choice: every other threshold saves fewer rounds, or as many with more wrong primes."
            if not unrun else
            "Settings without a behaviour run that rank above this point on the curve, so the choice is open until they are "
            "run: " + ", ".join(f"{u['threshold']} / {u['margin']}" for u in unrun) + "."
        )]
    if result["plateau_margins"]:
        lines += ["", (
            f"The margin is read off the same curve. At threshold {shipped['threshold']}, margins "
            f"{', '.join(f'{m:.2f}' for m in result['plateau_margins'])} do equally well on the development split; the smallest "
            "primes a second skill least often, so it is the one the behaviour runs used."
        )]
    return lines


def _effect_lines(result: dict[str, Any]) -> list[str]:
    held, dev = result["held_out"], result["development"]
    lines = [(
        f"**The rule.** At the shipped values the production rule saves {dev['shipped']['rounds_saved']} rounds on the "
        f"development split and {held['shipped']['rounds_saved']} held out; the rule before #18 saves "
        f"{dev['rule_before_18']['rounds_saved']} and {held['rule_before_18']['rounds_saved']}."
    )]
    if dev["state_before_18"] and held["state_before_18"]:
        lines += ["", (
            f"**The state.** Told when the customer is a new prospect, the Decider saves {dev['shipped']['rounds_saved']} rounds "
            f"on the development split against {dev['state_before_18']['rounds_saved']} without it, and "
            f"{held['shipped']['rounds_saved']} held out against {held['state_before_18']['rounds_saved']}."
        )]
    return lines


def render(result: dict[str, Any], out: Path) -> tuple[Path, Path]:
    """The report, its JSON and two charts, from `fit()`'s result."""
    cal, fitted, held, dev, shipped = (result[k] for k in ("calibration", "curve", "held_out", "development", "shipped"))
    out.parent.mkdir(parents=True, exist_ok=True)
    reliability_svg, curve_svg = out.with_name(out.stem + "-reliability.svg"), out.with_name(out.stem + "-curve.svg")
    _svg_chart(reliability_svg, "Reliability, development split, all skills", "Decider probability", "share required",
               {"observed": [(r["mean_p"], r["observed"]) for r in cal["pooled"]["bins"]]}, (0, 1), (0, 1), diagonal=True)
    drawn = {name: (best_per_threshold(points) if len(RULES[name].margins) > 1 else points) for name, points in fitted.items()}
    _svg_chart(curve_svg, "Decision curve, development split", "threshold", "Skill rounds saved",
               {name: [(p["threshold"], p["rounds_saved"]) for p in pts] for name, pts in drawn.items()}
               | {f"wrong primes ({PRODUCTION})": [(p["threshold"], p["wrong_primes"]) for p in drawn[PRODUCTION]]},
               (THRESHOLDS[0], THRESHOLDS[-1]), (0, max(p["rounds_to_save"] for p in fitted[PRODUCTION])),
               marks=[shipped["threshold"]])

    labels = {
        "shipped": "Shipped values",
        "rule_before_18": f"Same answers, the rule before #18 (top one when clear, {BEFORE_18[0]} / {BEFORE_18[1]})",
        "state_before_18": "Shipped values, the Decider's state before #18 (not told when the customer is a new prospect)",
        "before_18": "Before #18: that rule and that state",
    }
    lines = [
        "# Priming thresholds",
        "",
        f"Fitted on the Golden Set's **development split** ({dev['shipped']['cases']} cases), which is used for nothing else. "
        f"Published on the **held-out split** ({held['shipped']['cases']} cases), at the values the configuration ships: "
        f"threshold **{shipped['threshold']}**, margin **{shipped['margin']}**, rule *{PRODUCTION}*.",
        "",
        "## Results (held-out split)",
        "",
        "| | Exact set | Precision | Recall | Skill rounds saved | Seconds saved | Decider time | Wrong primes | Missed |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key, label in labels.items():
        p = held[key]
        if p is not None:
            lines.append(
                f"| {label} | {_pct(p['exact'])} | {_pct(p['precision'])} | {_pct(p['recall'])} | "
                f"{p['rounds_saved']} of {p['rounds_to_save']} | {p['seconds_saved']:.0f} s | {p['decider_seconds']:.0f} s | "
                f"{p['wrong_primes']} ({p['wrong_prime_tokens']:,} tokens) | {p['missed']} |"
            )
    lines += [
        "",
        "A round counts as saved when every required skill was primed on a case whose baseline first response loaded skills "
        "and called nothing a skill informs; its seconds are that round's measured duration. The Decider's time is spent on "
        "every turn, saved or not. A missed prime costs the round Priming was meant to save; a wrong prime costs its body in "
        "tokens and some bias toward that area — which is what the quality check in step 3 is for.",
        "",
        *_effect_lines(result),
        "",
        "## How the values were chosen (development split)",
        "",
        *_calibration_lines(cal, reliability_svg),
        "",
        "### 2. The decision curve",
        "",
        f"![Decision curve]({curve_svg.name})",
        "",
        "Each rule at its best margin per threshold:",
        "",
        "| Rule | Threshold | Margin | Rounds saved | Seconds saved | Wrong primes | Missed | Exact |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, pts in drawn.items():
        lines += [f"| {name} | {p['threshold']:.2f} | {p['margin']:.2f} | {p['rounds_saved']} of {p['rounds_to_save']} | "
                  f"{p['seconds_saved']:.0f} s | {p['wrong_primes']} | {p['missed']} | {_pct(p['exact'])} |" for p in pts]
    lines += ["", "### 3. Quality on the behaviour cases", "", *_quality_lines(result), "", "### 4. The choice", "",
              *_choice_lines(result)]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path = out.with_suffix(".json")
    json_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return out, json_path


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------
def load_all(reports: Path = REPORTS_DIR, behaviour_names: list[str] | None = None) -> dict[str, Any]:
    """The fit's inputs as the repository keeps them; the before-#18 snapshots are optional."""
    def optional(name: str, split: str) -> list[Turn] | None:
        path = reports / f"{name}.json"
        return load_turns(path, reports / f"golden-{split}.json") if path.exists() else None

    return {
        "dev": load_turns(reports / "golden-decider-dev.json", reports / "golden-dev.json"),
        "dev_before": optional("golden-decider-dev-before-18", "dev"),
        "held_out": load_turns(reports / "golden-decider-test.json", reports / "golden-test.json"),
        "held_out_before": optional("golden-decider-test-before-18", "test"),
        "rows": behaviour(behaviour_names or BEHAVIOUR_RUNS, reports),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.thresholds", description=__doc__.split("\n\n")[0])
    parser.add_argument("--behaviour", default=",".join(BEHAVIOUR_RUNS),
                        help="behaviour-case reports to compare, in order; the ones with Priming off set the noise")
    args = parser.parse_args(argv)
    config = HarnessConfig()
    body_tokens = {name: estimate_tokens(s.body) for name, s in load_skills(config.skills_dir).items()}
    inputs = load_all(behaviour_names=[n.strip() for n in args.behaviour.split(",") if n.strip()])
    result = fit(inputs["dev"], inputs["dev_before"], inputs["held_out"], inputs["held_out_before"], inputs["rows"],
                 config, body_tokens)
    md, _ = render(result, REPORTS_DIR / "priming-thresholds.md")
    print(f"report: {md}")
    if not result["shipped_is_choice"]:
        print("the shipped values are not the fit's choice; see the report's last section")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
