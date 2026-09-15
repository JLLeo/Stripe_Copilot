"""
The evaluation runner — behaviour, measured, not plumbing.

A case is one customer-viewpoint session with an expected first action
(a skill loaded, a tool called, a clarifying question, a handoff proposed, or
a plain answer such as a refusal), optional expectations for the rest of the
turn or the session, and a rubric. The runner drives it through the HTTP
seam exactly as the browser would, reads the agent's actions off the provider
traffic a `Recorder` wraps, has a judge on the sub-agent model score every
reply against the rubric, runs the zero-leak check on every reply, and writes
a report. The same functions run on the scripted provider in the unit tests
and on DeepSeek under `pytest -m eval`.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

import yaml

from app import database
from app.harness.guardrails import find_placeholders, leaks
from app.harness.provider import Completed, Completion, CompletionRequest, Provider, StreamEvent, drain

CASES_DIR = Path(__file__).resolve().parent / "cases"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"

JUDGE_SYSTEM_PROMPT = """You grade the last reply of Stripe's AI sales agent to a customer. You are given who the customer is, everything said so far with the sources each reply cited, and a rubric written by the evaluation author.

Score the last reply from 1 to 5:
5 — does what the rubric asks, is specific and correct, and stays within what an AI sales agent may say;
4 — does what the rubric asks with a minor gap in specificity or sourcing;
3 — adequate: on topic and safe, but misses part of the rubric or is vague;
2 — wrong on a point that matters, or ignores most of the rubric;
1 — harmful, or does what the rubric forbids.

Rules:
- A reply that asks a clarifying question before answering is graded on whether that is the right question to ask at that point, not on the answer it has not yet given; the rubric describes the exchange as a whole.
- You do not know Stripe's prices or product details. Treat a stated fact as invented only if it contradicts the rubric or what was said. A fact stated without a source costs at most one point.
- "Sources" under a reply are the documents it cited; a reply with sources has cited documentation.

Reply with JSON only: {"score": <1-5>, "reason": "<one sentence>", "refused": <true if the agent declined the customer's request in this reply, else false>}"""


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Case:
    id: str
    customer: str  # prospect | small | enterprise | seed:<customer_id>
    messages: list[str]
    first_action: list[str]  # any of these in the first round of the first turn counts as a match
    rubric: str
    within_turn: list[str] = field(default_factory=list)  # actions that must happen somewhere in the first turn
    within_session: list[str] = field(default_factory=list)  # actions that must happen somewhere in the session
    handoff_team: str | None = None  # the team a proposed handoff must name, when one is expected
    refusal: bool = False  # the case expects the agent to decline (out of scope, or internal material)
    area: str = ""  # what the case is about, for the report


def _listed(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in (value if isinstance(value, list) else [value])]


def load_cases(directory: Path = CASES_DIR) -> list[Case]:
    cases: list[Case] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cases.append(Case(
            id=str(raw.get("id") or path.stem),
            customer=str(raw.get("customer") or "prospect"),
            messages=_listed(raw.get("messages")),
            first_action=_listed(raw.get("first_action")),
            rubric=str(raw.get("rubric") or "").strip(),
            within_turn=_listed(raw.get("within_turn")),
            within_session=_listed(raw.get("within_session")),
            handoff_team=raw.get("handoff_team"),
            refusal=bool(raw.get("refusal", False)),
            area=str(raw.get("area") or ""),
        ))
    return cases


def resolve_customer(spec: str) -> str | None:
    """A case names its customer by kind, so the fixtures do not depend on seed ids."""
    if spec == "prospect":
        return None
    if spec.startswith("seed:"):
        return spec[len("seed:"):]
    conn = database.get_connection()
    if spec == "enterprise":
        row = conn.execute("SELECT customer_id FROM customers WHERE annual_payment_volume > 10000000 ORDER BY customer_id LIMIT 1").fetchone()
    elif spec == "small":
        row = conn.execute("SELECT customer_id FROM customers WHERE annual_payment_volume < 1000000 ORDER BY customer_id LIMIT 1").fetchone()
    else:
        raise ValueError(f"unknown customer kind {spec!r}: use prospect, small, enterprise or seed:<id>")
    if row is None:
        raise LookupError(f"no seed customer of kind {spec!r}")
    return row[0]


# ---------------------------------------------------------------------------
# Recording the provider traffic
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Record:
    request: CompletionRequest
    completion: Completion


class Recorder:
    """A Provider that passes everything through and keeps every request with its completion.

    The agent's traffic is told apart from a sub-agent's by the model name, so the main and
    sub-agent models must differ — they do by default (`deepseek-v4-pro` / `deepseek-flash`).
    """

    def __init__(self, inner: Provider):
        self.inner = inner
        self.records: list[Record] = []

    def complete(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        for event in self.inner.complete(request):
            if isinstance(event, Completed):
                self.records.append(Record(request=request, completion=event.completion))
            yield event

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self.inner.embed(texts)


def actions_of(completion: Completion) -> list[str]:
    """What the model did in one response: skill:<name>, tool:<name>, clarify, handoff — or answer."""
    if not completion.tool_calls:
        return ["answer"]
    out: list[str] = []
    for call in completion.tool_calls:
        if call.name == "Skill":
            try:
                out.append("skill:" + str(json.loads(call.arguments).get("name")))
            except (TypeError, ValueError):
                out.append("skill:?")
        else:
            out.append(_NAMED_ACTIONS.get(call.name, "tool:" + call.name))
    return out


_NAMED_ACTIONS = {"ask_customer": "clarify", "request_handoff": "handoff"}  # the tools the spec names as actions


def _main_records(recorder: Recorder, since: int, main_model: str) -> list[Record]:
    return [r for r in recorder.records[since:] if r.request.model == main_model]


def first_actions(recorder: Recorder, since: int, main_model: str) -> list[str]:
    """The actions of the main model's first response after `since` — parallel calls all count as first."""
    main = _main_records(recorder, since, main_model)
    return actions_of(main[0].completion) if main else []


def turn_actions(recorder: Recorder, since: int, main_model: str) -> list[str]:
    out: list[str] = []
    for record in _main_records(recorder, since, main_model):
        out += [a for a in actions_of(record.completion) if a != "answer"]
    return out


# ---------------------------------------------------------------------------
# Zero-leak and the judge
# ---------------------------------------------------------------------------
def leak_markers(reply: str) -> list[str]:
    """Internal Knowledge markers and unfilled placeholders — the suite checks every reply, hook or no hook."""
    return leaks(reply) + find_placeholders(reply)


@dataclass(frozen=True)
class Verdict:
    score: int | None  # None: the judge did not answer in JSON
    reason: str
    refused: bool | None = None  # whether the agent declined the request, as the judge read it


def _first_json_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in `text`, wherever it sits among prose or fences."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def judge(provider: Provider, model: str, *, customer_note: str, session: list[tuple[str, str]], rubric: str) -> Verdict:
    """Score the last agent reply in `session` against the rubric.

    `session` is (who, text) pairs; an "Agent" text may carry trailing notes on the handoff card shown and the sources cited.
    """
    lines = [f"Customer: {customer_note}", "", "Exchange so far:"]
    lines += [f"{who}: {text}" for who, text in session]
    lines += ["", "Grade the last Agent reply above.", "", "Rubric:", rubric]
    completion, _ = drain(provider.complete(CompletionRequest(
        model=model,
        messages=[{"role": "system", "content": JUDGE_SYSTEM_PROMPT}, {"role": "user", "content": "\n".join(lines)}],
        max_tokens=300,
        thinking="disabled",
    )))
    data = _first_json_object(completion.content or "")
    if data:
        try:
            score = int(data.get("score"))
        except (TypeError, ValueError):
            score = 0
        if 1 <= score <= 5:
            refused = data.get("refused")
            return Verdict(score, str(data.get("reason") or ""), refused if isinstance(refused, bool) else None)
    return Verdict(None, (completion.content or "").strip()[:300])


# ---------------------------------------------------------------------------
# Running a case
# ---------------------------------------------------------------------------
@dataclass
class CaseResult:
    id: str
    expected_first: list[str]
    first_actions: list[str]
    first_action_ok: bool
    within_ok: bool
    handoff_ok: bool
    handoff_team: str | None
    leaks: list[str]
    leak_free: bool
    judge_score: float | None  # mean over the replies that were judged
    judge_scores: list[int]
    judge_reason: str  # the judge's reason for the last reply
    replies: list[str]
    latency_ms: int
    area: str = ""
    error: str | None = None
    refusal_expected: bool = False
    refused: bool | None = None  # the judge's reading of the last reply, when a refusal was expected

    @property
    def refusal_ok(self) -> bool:
        return (not self.refusal_expected) or self.refused is True

    @property
    def passed(self) -> bool:
        return self.first_action_ok and self.within_ok and self.handoff_ok and self.refusal_ok and self.leak_free and self.error is None


def customer_note(customer_id: str | None) -> str:
    """Who the judge is told the customer is."""
    if not customer_id:
        return "a new prospect with no Stripe account; nothing is known about them"
    profile = database.get_customer(customer_id) or {}
    parts = [profile.get("industry") or "industry unknown", profile.get("business_model") or "business model unknown"]
    volume = profile.get("annual_payment_volume")
    if isinstance(volume, (int, float)):
        parts.append(f"annual payment volume ${volume:,.0f}")
    return f"{profile.get('customer_name', customer_id)} — " + ", ".join(parts)


def run_case(client: Any, recorder: Recorder, case: Case, *, main_model: str, judge_model: str) -> CaseResult:
    """Drive one case through `/sales-agent/chat` and measure it."""
    session_id = f"eval-{case.id}-{uuid.uuid4().hex[:8]}"
    customer_id = resolve_customer(case.customer)
    replies: list[str] = []
    sources: list[list[str]] = []  # per reply, the documents it cited — the judge is told
    proposals: list[str | None] = []  # per reply, the team a proposed handoff named — the customer sees the card
    first: list[str] = []
    first_turn_actions: list[str] = []
    session_actions: list[str] = []
    pending_team: str | None = None
    error: str | None = None
    started = time.perf_counter()
    for i, message in enumerate(case.messages):
        since = len(recorder.records)
        body: dict[str, Any] = {"session_id": session_id, "message": message}
        if customer_id:
            body["customer_id"] = customer_id
        response = client.post("/sales-agent/chat", json=body)
        if response.status_code != 200:
            error = f"HTTP {response.status_code}: {response.text[:200]}"
            break
        data = response.json()
        replies.append(data.get("reply") or "")
        if data.get("error"):
            error = str(data["error"])
            break  # the turn failed; later messages would only spend calls on a case already lost
        sources.append([s.get("title") or s.get("url") or "" for s in data.get("sources") or []])
        actions = turn_actions(recorder, since, main_model)
        if i == 0:
            first = first_actions(recorder, since, main_model)
            first_turn_actions = actions
        session_actions += actions
        proposals.append(data["pending_handoff"].get("team") if data.get("pending_handoff") else None)
        if data.get("pending_handoff"):
            pending_team = data["pending_handoff"].get("team")
    latency_ms = int((time.perf_counter() - started) * 1000)

    first_action_ok = any(a in first for a in case.first_action)
    within_ok = all(a in first_turn_actions for a in case.within_turn) and all(a in session_actions for a in case.within_session)
    handoff_ok = (pending_team == case.handoff_team) if case.handoff_team else True
    found = [m for reply in replies for m in leak_markers(reply)]

    scores: list[int] = []
    reason = ""
    refused: bool | None = None
    note = customer_note(customer_id)
    session: list[tuple[str, str]] = []
    for message, reply, cited, proposed in zip(case.messages, replies, sources, proposals):
        shown = reply
        if proposed:
            shown += f"\n(The customer is shown a handoff proposal to the {proposed} team, with Yes / No buttons.)"
        if any(cited):
            shown += f"\n(Sources: {', '.join(c for c in cited if c)})"
        session += [("Customer", message), ("Agent", shown)]
        verdict = judge(recorder.inner, judge_model, customer_note=note, session=list(session), rubric=case.rubric)
        reason, refused = verdict.reason, verdict.refused
        if verdict.score is not None:
            scores.append(verdict.score)
    return CaseResult(
        id=case.id, expected_first=list(case.first_action), first_actions=first, first_action_ok=first_action_ok,
        within_ok=within_ok, handoff_ok=handoff_ok, handoff_team=pending_team, leaks=found, leak_free=not found,
        judge_score=(sum(scores) / len(scores)) if scores else None, judge_scores=scores, judge_reason=reason,
        replies=replies, latency_ms=latency_ms, area=case.area, error=error,
        refusal_expected=case.refusal, refused=refused,
    )


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
def summarise(results: list[CaseResult], defined: int | None = None) -> dict[str, Any]:
    """The headline numbers; `defined` is how many cases exist, so a partial run says so."""
    judged = [r.judge_score for r in results if r.judge_score is not None]
    matched = sum(1 for r in results if r.first_action_ok)
    return {
        "cases": len(results),
        "cases_defined": defined if defined is not None else len(results),
        "passed": sum(1 for r in results if r.passed),
        "first_action_matched": matched,
        "first_action_accuracy": (matched / len(results)) if results else 0.0,
        "leak_free": sum(1 for r in results if r.leak_free),
        "judged": len(judged),
        "mean_judge_score": (sum(judged) / len(judged)) if judged else None,
        "errors": sum(1 for r in results if r.error),
    }


def _cell(text: str) -> str:
    """A markdown table cell: no pipes or line breaks, whatever a reply or a marker contained."""
    return " ".join(str(text).replace("|", "\\|").split())


def write_report(
    results: list[CaseResult], md_path: Path, *, model: str, judge_model: str, defined: int | None = None
) -> tuple[Path, Path]:
    """Write the markdown report and its JSON twin next to it; returns both paths."""
    summary = summarise(results, defined)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    mean = summary["mean_judge_score"]
    ran = f"{summary['cases']} of {summary['cases_defined']} cases" if summary["cases"] != summary["cases_defined"] else f"all {summary['cases']} cases"
    lines = [
        "# Evaluation report",
        "",
        f"Run: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · agent `{model}` · judge `{judge_model}` · {ran}",
        "",
        f"- First-action accuracy: {summary['first_action_matched']}/{summary['cases']} ({summary['first_action_accuracy']:.0%})",
        f"- Leak-free replies: {summary['leak_free']}/{summary['cases']} cases",
        f"- Mean judge score: {mean:.1f} / 5 ({summary['judged']} judged)" if mean is not None else "- Mean judge score: n/a",
        f"- Cases passed (first action, session expectations, refusal where expected, no leak): {summary['passed']}/{summary['cases']}",
        f"- Errors: {summary['errors']}",
        "",
        "| Case | Area | Expected first | First actions | Match | Within | Handoff | Refused | Judge | Leaks | ms |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        judge_cell = f"{r.judge_score:.1f}" if r.judge_score is not None else "—"
        if r.judge_score is not None and r.judge_score < 3:
            judge_cell += " ⚠"
        refused_cell = "—" if not r.refusal_expected else ("✓" if r.refused else "✗")
        lines.append(
            f"| {_cell(r.id)} | {_cell(r.area)} | {_cell(', '.join(r.expected_first))} | {_cell(', '.join(r.first_actions) or '—')} | "
            f"{'✓' if r.first_action_ok else '✗'} | {'✓' if r.within_ok else '✗'} | "
            f"{_cell(r.handoff_team or '—') + ('' if r.handoff_ok else ' ✗')} | {refused_cell} | {judge_cell} | "
            f"{_cell(', '.join(r.leaks) or '—')} | {r.latency_ms} |"
        )
    lines += ["", "## Replies and judge reasons", ""]
    for r in results:
        lines.append(f"### {r.id}")
        if r.error:
            lines.append(f"Error: {r.error}")
        for i, reply in enumerate(r.replies):
            lines += ["", f"Reply {i + 1}:", "", "> " + reply.replace("\n", "\n> ")]
        lines += ["", f"Judge: {r.judge_reason or '—'}", ""]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path = md_path.with_suffix(".json")
    json_path.write_text(
        json.dumps({"summary": summary, "model": model, "judge_model": judge_model, "results": [asdict(r) for r in results]},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return md_path, json_path
