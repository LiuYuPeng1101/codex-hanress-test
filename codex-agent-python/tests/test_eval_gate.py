from types import SimpleNamespace as NS

import pytest

from evals.gate import REQUIRED_SCORES, summarize_results


def row(output=None, scores=None, error=None):
    return {
        "run": NS(outputs=output or {"execution_status": "completed"}, error=error),
        "evaluation_results": {"results": [NS(key=k, score=v) for k, v in (scores or {}).items()]},
    }


def test_complete_passing_results_open_gate():
    summary = summarize_results([row(scores=dict.fromkeys(REQUIRED_SCORES, 1))])
    assert summary.passed


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [row()],
        [row(error="failed")],
        [row({"skipped": True}, dict.fromkeys(REQUIRED_SCORES, 1))],
        [row(scores={"tool_policy": 1, "approval_policy": 1})],
        [row(scores=dict.fromkeys(REQUIRED_SCORES, None))],
        [row(scores=dict.fromkeys(REQUIRED_SCORES, 0))],
    ],
)
def test_empty_skipped_missing_or_failed_results_close_gate(rows):
    assert not summarize_results(rows).passed
