"""
The Golden Set — which Skills a turn needs, decided four ways and measured (#17).

Eighty labelled turns in four cells of twenty: single- or multi-intent, on the
first turn of a Session or a later one. A multi-turn case carries a fixed prior
Working Memory — earlier customer messages, the agent's replies, and the skills
those turns brought in — so every arm decides the same turn from the same bytes
and none can drift into a different Session.

Each case labels two layers, for skills and for tools: what must be chosen, and
what is acceptable besides. A choice inside either layer never costs precision;
only a choice outside both does. A required entry may name alternatives —
`search_knowledge|research` — when either does the job.

Four arms decide every case (`arms_for`): the main model with thinking on
(today's decision-maker), the main model with thinking off, the sub-agent model,
and the Decider through the production Priming code at its configured threshold
and margin. The model arms get exactly the request a turn's first model call
gets with Priming off. Their skill decision is the `Skill` calls in that first
response, timed to its end. Their tool decision is the tools they call with the
instructions in hand: the first response's own tools when it called one a skill
informs (a pairing, counted as such), otherwise — when it only loaded skills or
read the profile — the next response, once those calls are answered. A tool no
skill informs (`UNINFORMED_TOOLS`) is never scored: reading the profile or
remembering a fact is free. The Decider is scored on skills alone.

Reported per arm and per cell: exact-set match, precision, recall and F1
(micro-averaged over the cell), first-action accuracy, and decision latency
p50/p90. No ranking metric: the decision is a set, executed in one parallel
round, and nothing consumes an order.

The cases are split forty development / forty held-out; a run covers one split
or both, and the report says which. Run on demand, never in the default suite:

    python -m evals.golden --split dev          # the four arms over the 40 development cases
    python -m evals.golden --check              # validate the case files only; no model calls
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from app import database
from app.harness import priming, prompt
from app.harness.decider import Decider
from app.harness.provider import Completion, CompletionRequest, drain
from app.harness.skills import (
    ALREADY_IN_CONTEXT,
    UNINFORMED_TOOLS,
    Skill,
    primed_message,
    skill_paired_with_tool,
    skills_in_context,
)
from app.harness.tools import ToolContext
from evals.runner import NAMED_ACTIONS, REPORTS_DIR, actions_of, resolve_customer

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
CELLS = ("single_intent_single_turn", "multi_intent_single_turn", "single_intent_multi_turn", "multi_intent_multi_turn")
SPLITS = ("dev", "test")
DECIDER = "decider"
_CUSTOMER = re.compile(r"\A(prospect|small|enterprise|seed:C\d{3})\Z")
_ACTION_TOOLS = {action: tool for tool, action in NAMED_ACTIONS.items()}  # clarify -> ask_customer, handoff -> request_handoff
_CASE_KEYS = {"id", "split", "customer", "working_memory", "message", "skills", "tools", "first_action", "note"}
_TURN_KEYS = {"customer", "agent", "skills"}
_READ_ONLY_TOOLS = {"get_my_profile", "list_products"}  # run for real in a follow-up; remember is answered without writing


class GoldenSetError(ValueError):
    """A case file is malformed, or a case's labels contradict themselves."""


# ---------------------------------------------------------------------------
# Cases and their labels
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SetScore:
    """One decision against one layer of labels."""

    chosen: int  # distinct names chosen
    correct: int  # of those, inside either layer
    required: int  # required entries
    found: int  # required entries satisfied by some choice

    @property
    def exact(self) -> bool:
        return self.found == self.required and self.correct == self.chosen


@dataclass(frozen=True)
class Labels:
    """Every required entry must be chosen — an entry is a tuple of alternatives, any one of which will do;
    acceptable names may be chosen at no cost; anything else chosen costs precision."""

    required: tuple[tuple[str, ...], ...] = ()
    acceptable: tuple[str, ...] = ()

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset(name for alternatives in self.required for name in alternatives) | frozenset(self.acceptable)

    def score(self, chosen: Iterable[str]) -> SetScore:
        picked = set(chosen)
        return SetScore(
            chosen=len(picked), correct=len(picked & self.allowed), required=len(self.required),
            found=sum(1 for alternatives in self.required if picked & set(alternatives)),
        )

    def show(self) -> str:
        required = ", ".join(" or ".join(alternatives) for alternatives in self.required) or "—"
        return required + (f" (+ {', '.join(self.acceptable)})" if self.acceptable else "")


@dataclass(frozen=True)
class PriorTurn:
    customer: str
    agent: str
    skills: tuple[str, ...] = ()  # what this earlier turn brought into context


@dataclass(frozen=True)
class GoldenCase:
    id: str
    cell: str
    split: str
    customer: str  # prospect | small | enterprise | seed:<id>, as in the behaviour cases
    message: str  # the turn being decided
    skills: Labels
    tools: Labels
    first_action: tuple[str, ...]  # any of these in the first response counts, in the behaviour cases' vocabulary
    working_memory: tuple[PriorTurn, ...] = ()  # the fixed prior Working Memory, oldest first
    note: str = ""  # why the labels are what they are, for whoever reviews them

    @property
    def in_context(self) -> frozenset[str]:
        return frozenset(skill for turn in self.working_memory for skill in turn.skills)


def load_golden(directory: Path = GOLDEN_DIR, *, skill_names: Iterable[str], tool_names: Iterable[str]) -> list[GoldenCase]:
    """Every case in `<directory>/<cell>.yaml`, in cell order, validated against the real skill and tool names.

    All problems are reported at once, so a case author fixes a file in one pass.
    """
    skills, tools = set(skill_names), set(tool_names) - {"Skill"}
    cases: list[GoldenCase] = []
    problems: list[str] = []
    seen: set[str] = set()
    for path in sorted(Path(directory).glob("*.yaml"), key=lambda p: CELLS.index(p.stem) if p.stem in CELLS else len(CELLS)):
        if path.stem not in CELLS:
            problems.append(f"{path.name}: not a cell; files are named after one of {', '.join(CELLS)}")
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if not isinstance(raw, list):
            problems.append(f"{path.name}: must be a list of cases")
            continue
        for i, entry in enumerate(raw):
            case_id = str(entry.get("id", "?")) if isinstance(entry, dict) else "?"
            where = f"{path.name}[{i}] {case_id}"
            if case_id in seen:
                problems.append(f"{where}: duplicate id")
            seen.add(case_id)
            try:
                cases.append(_parse_case(entry, path.stem, skills, tools))
            except GoldenSetError as exc:
                problems += [f"{where}: {p}" for p in exc.args[0]]
    if problems:
        raise GoldenSetError("\n".join(problems))
    return cases


def _parse_case(raw: Any, cell: str, skills: set[str], tools: set[str]) -> GoldenCase:
    problems: list[str] = []
    if not isinstance(raw, dict):
        raise GoldenSetError(["a case must be a mapping"])
    problems += [f"'{key}' is required" for key in ("id", "split", "customer", "message", "first_action") if not raw.get(key)]
    problems += [f"unknown key {key!r}" for key in sorted(set(raw) - _CASE_KEYS)]
    if raw.get("split") not in SPLITS:
        problems.append(f"split must be one of {', '.join(SPLITS)}")
    if not _CUSTOMER.match(str(raw.get("customer", ""))):
        problems.append("customer must be prospect, small, enterprise or seed:C<nnn>")

    prior: list[PriorTurn] = []
    for turn in raw.get("working_memory") or []:
        if not isinstance(turn, dict) or not turn.get("customer") or not turn.get("agent") or set(turn) - _TURN_KEYS:
            problems.append("each working_memory turn has 'customer', 'agent' and optionally 'skills', nothing else")
            continue
        loaded = tuple(str(s) for s in turn.get("skills") or [])
        problems += [f"working_memory names unknown skill {s!r}" for s in loaded if s not in skills]
        prior.append(PriorTurn(customer=str(turn["customer"]).strip(), agent=str(turn["agent"]).strip(), skills=loaded))
    multi_turn = cell.endswith("multi_turn")
    if multi_turn and not prior:
        problems.append("a multi-turn case needs a prior working_memory")
    if not multi_turn and prior:
        problems.append("a single-turn case has no prior working_memory")

    skill_labels = _labels(raw.get("skills"), "skills", skills, problems)
    tool_labels = _labels(raw.get("tools"), "tools", tools, problems)
    in_context = {s for turn in prior for s in turn.skills}
    problems += [f"skill {s!r} is already in context from the working_memory; it can be neither required nor acceptable"
                 for s in sorted(skill_labels.allowed & in_context)]
    if cell.startswith("single_intent") and len(skill_labels.required) > 1:
        problems.append("a single-intent case requires at most one skill")
    if cell.startswith("multi_intent") and len(skill_labels.required) < 2:
        problems.append("a multi-intent case requires at least two skills")

    first_action = tuple(str(a) for a in (raw.get("first_action") or []))
    for action in first_action:
        kind, _, name = action.partition(":")
        if action == "answer":
            continue
        if action in _ACTION_TOOLS:
            if _ACTION_TOOLS[action] not in tool_labels.allowed:
                problems.append(f"first action {action!r} needs {_ACTION_TOOLS[action]} in the tool labels")
        elif kind == "skill" and name:
            if name not in skill_labels.allowed:
                problems.append(f"first action {action!r} names a skill outside the skill labels")
        elif kind == "tool" and name:
            if name in NAMED_ACTIONS:
                problems.append(f"first action {action!r}: write {NAMED_ACTIONS[name]!r}")
            elif name not in tool_labels.allowed:
                problems.append(f"first action {action!r} names a tool outside the tool labels")
        else:
            problems.append(f"first action {action!r}: use answer, clarify, handoff, skill:<name> or tool:<name>")
    if problems:
        raise GoldenSetError(problems)
    return GoldenCase(
        id=str(raw["id"]), cell=cell, split=str(raw["split"]), customer=str(raw["customer"]),
        message=str(raw["message"]).strip(), skills=skill_labels, tools=tool_labels, first_action=first_action,
        working_memory=tuple(prior), note=" ".join(str(raw.get("note") or "").split()),
    )


def _labels(raw: Any, layer: str, known: set[str], problems: list[str]) -> Labels:
    raw = raw or {}
    if not isinstance(raw, dict) or set(raw) - {"required", "acceptable"}:
        problems.append(f"'{layer}' takes 'required' and 'acceptable' lists only")
        return Labels()
    required = tuple(tuple(n.strip() for n in str(entry).split("|")) for entry in raw.get("required") or [])
    acceptable = tuple(str(n).strip() for n in raw.get("acceptable") or [])
    for name in [n for alternatives in required for n in alternatives] + list(acceptable):
        if name not in known:
            problems.append(f"{layer} label names unknown {name!r}")
    named = [n for alternatives in required for n in alternatives]
    problems += [f"{layer}: {n!r} is required twice" for n in sorted({n for n in named if named.count(n) > 1})]
    problems += [f"{layer}: {n!r} is both required and acceptable" for n in sorted(set(named) & set(acceptable))]
    if layer == "tools":
        problems += [f"tools: {n!r} is informed by no skill and never scored; it cannot be required"
                     for n in sorted(set(named) & UNINFORMED_TOOLS)]
    return Labels(required=required, acceptable=acceptable)


# ---------------------------------------------------------------------------
# The arms, and one decision
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Arm:
    name: str
    model: str | None = None  # None: the Decider
    thinking: str = "disabled"


def arms_for(config: Any) -> list[Arm]:
    """The four decision-makers, all in front of the same final-answer model."""
    return [
        Arm("main-thinking", config.main_model, "enabled"),  # today
        Arm("main-no-thinking", config.main_model, "disabled"),
        Arm("sub-model", config.sub_model, config.thinking),  # as the research sub-agent runs it
        Arm(DECIDER),
    ]


@dataclass
class Decision:
    case_id: str
    arm: str
    cell: str
    split: str
    skills: list[str]  # the skills chosen, in the order chosen
    skill_score: SetScore
    first_actions: list[str]
    first_action_ok: bool
    latency_ms: int  # to the skill decision
    tools: list[str] | None = None  # the model arms only: chosen with the instructions in hand
    tool_score: SetScore | None = None
    tool_latency_ms: int | None = None  # to the tool decision: one response, or two when the first only loaded skills
    paired: bool | None = None  # the first response loaded a skill and called a tool it informs
    probabilities: dict[str, float] = field(default_factory=dict)  # the Decider only: every skill it was asked about
    skipped: str | None = None  # the Decider only: why nothing was primed
    error: str | None = None


def working_memory_messages(case: GoldenCase, skills: dict[str, Skill]) -> list[dict[str, Any]]:
    """The fixed prior Working Memory, as the harness stores it with Priming on: a turn's skills as a primed
    `system` message before its customer message, the agent's reply as plain text. No tool call is fabricated,
    so no reasoning is invented and the bytes are valid — and identical — for every arm."""
    out: list[dict[str, Any]] = []
    for turn in case.working_memory:
        if turn.skills:
            out.append(primed_message(list(turn.skills), skills))
        out.append({"role": "user", "content": turn.customer})
        out.append({"role": "assistant", "content": turn.agent})
    return out


def turn_messages(case: GoldenCase, harness: Any, customer_id: str | None) -> list[dict[str, Any]]:
    """The request a turn's first model call gets with Priming off — static prompt, customer block, Working Memory, message."""
    profile = database.get_customer(customer_id) if customer_id else None
    usage = database.get_customer_product_usage(customer_id) if profile else []
    block = prompt.customer_block(profile, usage, [])  # a golden run starts from an empty runtime database: no memory
    return prompt.assemble_messages(harness.static_prompt, block, working_memory_messages(case, harness.skills), case.message)


def decide(case: GoldenCase, arm: Arm, *, harness: Any, decider: Decider) -> Decision:
    """One arm's decision on one case. A failure is recorded on the decision, never raised."""
    try:
        customer_id = resolve_customer(case.customer)
        if arm.model is None:
            return _decide_by_decider(case, arm, harness, decider, customer_id)
        return _decide_by_model(case, arm, harness, customer_id)
    except Exception as exc:  # noqa: BLE001 — one failed call must not lose the rest of a long run
        return Decision(
            case_id=case.id, arm=arm.name, cell=case.cell, split=case.split, skills=[], skill_score=case.skills.score([]),
            first_actions=[], first_action_ok=False, latency_ms=0, error=f"{type(exc).__name__}: {exc}"[:300],
        )


def _decide_by_model(case: GoldenCase, arm: Arm, harness: Any, customer_id: str | None) -> Decision:
    messages = turn_messages(case, harness, customer_id)
    request = CompletionRequest(
        model=arm.model or "", messages=messages, tools=harness.tools.definitions(),
        max_tokens=harness.config.max_tokens, thinking=arm.thinking,
    )
    started = time.perf_counter()
    first, _ = drain(harness.provider.complete(request))
    latency = _ms(started)
    names = [c.name for c in first.tool_calls]
    loaded = _loaded_skills(first)
    tools = _unique(n for n in names if n != "Skill")
    tool_latency = latency
    if names and all(n == "Skill" or n in UNINFORMED_TOOLS for n in names):
        # Nothing a skill informs was chosen yet: those tools come once these calls are answered.
        follow = [*messages, first.to_message(), *_answers(first, case, harness, customer_id)]
        second, _ = drain(harness.provider.complete(replace(request, messages=follow)))
        tools = _unique([*tools, *(c.name for c in second.tool_calls if c.name != "Skill")])
        tool_latency = _ms(started)
    actions = actions_of(first)
    return Decision(
        case_id=case.id, arm=arm.name, cell=case.cell, split=case.split, skills=loaded, skill_score=case.skills.score(loaded),
        first_actions=actions, first_action_ok=any(a in actions for a in case.first_action), latency_ms=latency,
        tools=tools, tool_score=case.tools.score(t for t in tools if t not in UNINFORMED_TOOLS), tool_latency_ms=tool_latency,
        paired=skill_paired_with_tool(names),
    )


def _decide_by_decider(case: GoldenCase, arm: Arm, harness: Any, decider: Decider, customer_id: str | None) -> Decision:
    prior = working_memory_messages(case, harness.skills)
    primed = priming.prime(
        decider, replace(harness.config, priming=True), harness.skills, customer_id=customer_id, message=case.message,
        working_memory=prior, in_context=skills_in_context(prior, harness.skills),
    )
    chosen = list(primed.skills)
    actions = [f"skill:{s}" for s in chosen]
    # Priming nothing leaves the turn to the model — right when the case's first action needs no skill.
    ok = any(a in case.first_action for a in actions) if chosen else any(not a.startswith("skill:") for a in case.first_action)
    return Decision(
        case_id=case.id, arm=arm.name, cell=case.cell, split=case.split, skills=chosen, skill_score=case.skills.score(chosen),
        first_actions=actions, first_action_ok=ok, latency_ms=primed.decider_ms,
        probabilities=dict(primed.probabilities), skipped=primed.skipped,
    )


def _skill_name(call: Any) -> str:
    try:
        return str(json.loads(call.arguments).get("name"))
    except (TypeError, ValueError, AttributeError):
        return "?"


def _loaded_skills(completion: Completion) -> list[str]:
    return _unique(_skill_name(c) for c in completion.tool_calls if c.name == "Skill")


def _answers(completion: Completion, case: GoldenCase, harness: Any, customer_id: str | None) -> list[dict[str, Any]]:
    """What the harness would answer each call with: a skill's body, or the short note when it is already in
    context; a profile or catalogue read, run for real; `remember`, acknowledged without writing, so no arm leaves
    a fact behind that a later case's Decider state would read."""
    in_context = set(case.in_context)
    ctx = ToolContext(session_id=f"golden-{case.id}", customer_id=customer_id)
    out = []
    for call in completion.tool_calls:
        if call.name == "Skill":
            name = _skill_name(call)
            if name in in_context:
                content = ALREADY_IN_CONTEXT.format(name=name)
            elif name in harness.skills:
                content = harness.skills[name].body
                in_context.add(name)
            else:
                content = f"No skill named {name!r}. Available skills: {', '.join(harness.skills)}."
        elif call.name in _READ_ONLY_TOOLS:
            content = harness.tools.dispatch(call.name, call.arguments, ctx).content
        else:
            content = "Noted."
        out.append({"role": "tool", "tool_call_id": call.id, "content": content})
    return out


def _unique(names: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(names))


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def run(
    cases: list[GoldenCase], arms: list[Arm], *, harness: Any, decider: Decider,
    progress: Callable[[GoldenCase, list[Decision]], None] | None = None,
) -> list[Decision]:
    """Every arm on every case, one case at a time so no arm's latency is measured under another's load."""
    decisions: list[Decision] = []
    for case in cases:
        made = [decide(case, arm, harness=harness, decider=decider) for arm in arms]
        decisions += made
        if progress:
            progress(case, made)
    return decisions


# ---------------------------------------------------------------------------
# Aggregation and the report
# ---------------------------------------------------------------------------
def percentile(values: list[int], q: float) -> int | None:
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _layer(scores: list[SetScore]) -> dict[str, float | None]:
    """Micro-averaged over the decisions: a decision that chose nothing adds nothing to precision's denominator."""
    chosen, correct = sum(s.chosen for s in scores), sum(s.correct for s in scores)
    required, found = sum(s.required for s in scores), sum(s.found for s in scores)
    precision = correct / chosen if chosen else None
    recall = found / required if required else None
    if recall == 0:
        f1 = 0.0  # nothing required was found, whether or not anything was chosen
    elif precision is None or recall is None:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {"exact": sum(s.exact for s in scores) / len(scores) if scores else None,
            "precision": precision, "recall": recall, "f1": f1}


def stats(decisions: list[Decision]) -> dict[str, Any]:
    ok = [d for d in decisions if d.error is None]
    out: dict[str, Any] = {"cases": len(decisions), "errors": len(decisions) - len(ok)}
    out.update(_layer([d.skill_score for d in ok]))
    out["first_action"] = sum(d.first_action_ok for d in ok) / len(ok) if ok else None
    out["p50_ms"] = percentile([d.latency_ms for d in ok], 0.5)
    out["p90_ms"] = percentile([d.latency_ms for d in ok], 0.9)
    with_tools = [d for d in ok if d.tool_score is not None]
    if with_tools:
        out["tools"] = {
            **_layer([d.tool_score for d in with_tools if d.tool_score is not None]),
            "paired": sum(1 for d in with_tools if d.paired),
            "p50_ms": percentile([d.tool_latency_ms or 0 for d in with_tools], 0.5),
            "p90_ms": percentile([d.tool_latency_ms or 0 for d in with_tools], 0.9),
        }
    return out


def summarise(decisions: list[Decision]) -> dict[str, dict[str, dict[str, Any]]]:
    """arm -> "all" or a cell -> the numbers."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for arm in _unique(d.arm for d in decisions):
        mine = [d for d in decisions if d.arm == arm]
        out[arm] = {"all": stats(mine)}
        for cell in CELLS:
            in_cell = [d for d in mine if d.cell == cell]
            if in_cell:
                out[arm][cell] = stats(in_cell)
    return out


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def _num(value: int | None) -> str:
    return "—" if value is None else f"{value:,}"


def _split_line(split: str, cases: list[GoldenCase]) -> str:
    if split == "all":
        return f"both splits — development and held-out, {len(cases)} cases"
    return f"the {'development' if split == 'dev' else 'held-out'} split ({split}), {len(cases)} cases"


def write_report(
    decisions: list[Decision], cases: list[GoldenCase], md_path: Path, *, split: str, arms: list[Arm], config: Any,
) -> tuple[Path, Path]:
    """The markdown report and its JSON twin; returns both paths."""
    summary = summarise(decisions)
    by_case = {(d.case_id, d.arm): d for d in decisions}
    md_path.parent.mkdir(parents=True, exist_ok=True)
    described = ", ".join(f"`{a.name}` = {a.model} thinking {a.thinking}" if a.model else
                          f"`{a.name}` = {config.decider_model} at threshold {config.priming_threshold}, margin "
                          f"{config.priming_margin}, timeout {config.decider_timeout_seconds} s" for a in arms)
    lines = [
        "# Golden Set report",
        "",
        f"Run: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · covers {_split_line(split, cases)}",
        "",
        f"Arms: {described}.",
        "",
        "Skill selection is the `Skill` calls of a model arm's first response, or the skills the Decider primed. "
        "Precision and recall are micro-averaged; a choice among a case's acceptable skills costs nothing. "
        "Latency is to the skill decision.",
        "",
        "## Skill selection",
        "",
        "| Arm | Cell | Cases | Exact | Precision | Recall | F1 | First action | p50 ms | p90 ms | Errors |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for arm in summary:
        for scope, s in summary[arm].items():
            lines.append(
                f"| {arm} | {scope} | {s['cases']} | {_pct(s['exact'])} | {_pct(s['precision'])} | {_pct(s['recall'])} | "
                f"{_pct(s['f1'])} | {_pct(s['first_action'])} | {_num(s['p50_ms'])} | {_num(s['p90_ms'])} | {s['errors']} |"
            )
    lines += [
        "",
        "## Tool selection (model arms)",
        "",
        "The tools a model arm calls with the instructions in hand: its first response's tools when it called one a "
        "skill informs — *paired* counts those that also loaded a skill, so chose a tool before reading its "
        "instructions — otherwise the next response, once those calls are answered. Tools no skill informs "
        "(profile, catalogue, remember) are not scored. Latency is to that decision.",
        "",
        "| Arm | Cell | Exact | Precision | Recall | F1 | Paired | p50 ms | p90 ms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm in summary:
        for scope, s in summary[arm].items():
            if "tools" in s:
                t = s["tools"]
                lines.append(
                    f"| {arm} | {scope} | {_pct(t['exact'])} | {_pct(t['precision'])} | {_pct(t['recall'])} | {_pct(t['f1'])} | "
                    f"{t['paired']} | {_num(t['p50_ms'])} | {_num(t['p90_ms'])} |"
                )
    arm_names = [a.name for a in arms]
    lines += [
        "",
        "## Decisions by case",
        "",
        "Each arm's skills, ✓ when the set is exact. The Decider shows why it primed nothing.",
        "",
        "| Case | Cell | Split | Required skills (+ acceptable) | " + " | ".join(arm_names) + " |",
        "|---|---|---|---|" + "---|" * len(arm_names),
    ]
    for case in cases:
        cells = []
        for name in arm_names:
            d = by_case.get((case.id, name))
            if d is None:
                cells.append("—")
            elif d.error:
                cells.append("error")
            else:
                shown = ", ".join(d.skills) or (f"— ({d.skipped})" if d.skipped else "—")
                cells.append(shown + (" ✓" if d.skill_score.exact else ""))
        lines.append(f"| {case.id} | {case.cell} | {case.split} | {case.skills.show()} | " + " | ".join(cells) + " |")
    errors = [d for d in decisions if d.error]
    if errors:
        lines += ["", "## Errors", ""] + [f"- {d.case_id} / {d.arm}: {d.error}" for d in errors]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path = md_path.with_suffix(".json")
    json_path.write_text(json.dumps({
        "split": split,
        "arms": [asdict(a) for a in arms],
        "decider": {"model": config.decider_model, "threshold": config.priming_threshold,
                    "margin": config.priming_margin, "timeout_seconds": config.decider_timeout_seconds},
        "summary": summary,
        "cases": [{"id": c.id, "cell": c.cell, "split": c.split, "skills": asdict(c.skills), "tools": asdict(c.tools),
                   "first_action": list(c.first_action), "in_context": sorted(c.in_context)} for c in cases],
        "decisions": [asdict(d) for d in decisions],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return md_path, json_path


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.golden", description=__doc__.split("\n\n")[0])
    parser.add_argument("--split", choices=(*SPLITS, "all"), default="dev")
    parser.add_argument("--arms", help="comma-separated arm names; default all four")
    parser.add_argument("--limit", type=int, help="the first N cases of the split, for a quick look")
    parser.add_argument("--check", action="store_true", help="validate the case files and exit; no model calls")
    args = parser.parse_args(argv)

    # A run starts from an empty runtime database, so no arm sees Customer Memory another did not.
    os.environ["RUNTIME_DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="golden-")) / "runtime.db")
    database.close_connection()
    database.init_db()

    from dotenv import load_dotenv

    from app.harness.core import Harness, HarnessConfig
    from app.harness.decider import API_KEY_ENV, SKIP_PRIMING_OFF, NullDecider, TypeSafeDecider
    from app.harness.scripted import ScriptedProvider

    load_dotenv()
    config = HarnessConfig.from_env()
    if args.check:
        harness = Harness.build(ScriptedProvider(), config, decider=NullDecider(SKIP_PRIMING_OFF))
        try:
            cases = load_golden(skill_names=harness.skills, tool_names=harness.tools.names())
        except GoldenSetError as exc:
            print(exc, file=sys.stderr)
            return 1
        finally:
            harness.close()
        for cell in CELLS:
            mine = [c for c in cases if c.cell == cell]
            print(f"{cell}: {len(mine)} cases ({sum(c.split == 'dev' for c in mine)} dev, {sum(c.split == 'test' for c in mine)} test)")
        return 0

    from app.harness.deepseek import DeepSeekProvider

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("the Golden Set needs DEEPSEEK_API_KEY (see .env.example)", file=sys.stderr)
        return 2
    arms = arms_for(config)
    if args.arms:
        wanted = {a.strip() for a in args.arms.split(",")}
        unknown = wanted - {a.name for a in arms}
        if unknown:
            print(f"unknown arm(s) {', '.join(sorted(unknown))}; the arms are {', '.join(a.name for a in arms)}", file=sys.stderr)
            return 2
        arms = [a for a in arms if a.name in wanted]
    if any(a.name == DECIDER for a in arms) and not os.environ.get(API_KEY_ENV):
        print(f"the decider arm needs {API_KEY_ENV}; set it, or leave the arm out with --arms", file=sys.stderr)
        return 2
    harness = Harness.build(DeepSeekProvider.from_env(), config, decider=NullDecider(SKIP_PRIMING_OFF))
    decider: Decider = (
        TypeSafeDecider.from_env(model=config.decider_model, timeout=config.decider_timeout_seconds)
        if any(a.name == DECIDER for a in arms) else NullDecider(SKIP_PRIMING_OFF)
    )
    try:
        cases = [c for c in load_golden(skill_names=harness.skills, tool_names=harness.tools.names())
                 if args.split == "all" or c.split == args.split][: args.limit]

        def progress(case: GoldenCase, made: list[Decision]) -> None:
            shown = "  ".join(f"{d.arm}={','.join(d.skills) or '-'}{'!' if d.error else ''}({d.latency_ms}ms)" for d in made)
            print(f"{case.id}: {shown}", flush=True)

        decisions = run(cases, arms, harness=harness, decider=decider, progress=progress)
        md, _ = write_report(decisions, cases, REPORTS_DIR / f"golden-{args.split}.md", split=args.split, arms=arms, config=config)
        print(f"report: {md}")
        return 0
    finally:
        harness.close()
        decider.close()


if __name__ == "__main__":
    raise SystemExit(main())
