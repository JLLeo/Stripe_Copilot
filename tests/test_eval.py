"""
The evaluation suite — `pytest -m eval`, against the real provider.

Excluded by default. Each case is one customer-viewpoint session from
`evals/cases/`: the agent's first action must match, nothing may leak, and a
judge on the sub-agent model scores every reply against the case's rubric.
The report is written to `evals/reports/latest.md` (and `.json`) when the run
ends and summarised in the terminal.
"""

from __future__ import annotations

import os

import pytest

from evals import runner
from evals.runner import Case, load_cases

pytestmark = pytest.mark.eval

CASES = load_cases()
MIN_JUDGE_SCORE = float(os.environ.get("EVAL_MIN_JUDGE_SCORE", "0"))  # 0: the score is reported, not asserted


@pytest.fixture(scope="module")
def evaluation(request):
    """One real harness for the whole module; the report is written when the module is done."""
    from dotenv import load_dotenv
    from fastapi.testclient import TestClient

    from app import database, main
    from app.harness.core import Harness, HarnessConfig
    from app.harness.deepseek import DeepSeekProvider

    load_dotenv()
    if not os.environ.get("DEEPSEEK_API_KEY") or not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("the evaluation suite needs DEEPSEEK_API_KEY and OPENAI_API_KEY (see .env.example)")
    config = HarnessConfig.from_env()
    recorder = runner.Recorder(DeepSeekProvider.from_env())
    previous = main.app.state.harness
    main.app.state.harness = Harness.build(provider=recorder, config=config)
    results: list[runner.CaseResult] = []
    with TestClient(main.app) as client:
        yield {"client": client, "recorder": recorder, "config": config, "results": results}
    main.app.state.harness = previous
    database.close_connection()
    if results:
        md, _ = runner.write_report(
            results, runner.REPORTS_DIR / "latest.md", model=config.main_model, judge_model=config.sub_model, defined=len(CASES),
        )
        request.config._eval_summary = (runner.summarise(results, len(CASES)), md)


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_case(evaluation, case: Case):
    result = runner.run_case(
        evaluation["client"], evaluation["recorder"], case,
        main_model=evaluation["config"].main_model, judge_model=evaluation["config"].sub_model,
    )
    evaluation["results"].append(result)
    assert result.error is None, result.error
    assert result.leak_free, f"internal material or a placeholder reached the customer: {result.leaks}"
    assert result.first_action_ok, f"expected one of {case.first_action} first, the agent did {result.first_actions}"
    assert result.within_ok, f"expected {case.within_turn} in the first turn and {case.within_session} in the session"
    assert result.handoff_ok, f"expected a handoff to {case.handoff_team!r}, got {result.handoff_team!r}"
    assert result.refusal_ok, f"expected the agent to decline; the judge read the reply as {result.refused!r}: {result.judge_reason}"
    if MIN_JUDGE_SCORE and result.judge_score is not None:
        assert result.judge_score >= MIN_JUDGE_SCORE, f"judge scored {result.judge_score}: {result.judge_reason}"
