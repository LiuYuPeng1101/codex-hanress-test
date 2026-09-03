from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CASES_PATH = Path(__file__).parents[1] / "evals" / "cases.jsonl"


def _load_cases() -> list[dict[str, Any]]:
    lines = CASES_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_eval_cases_have_unique_ids_and_valid_expectations() -> None:
    cases = _load_cases()
    assert len(cases) >= 20

    case_ids = [case["id"] for case in cases]
    assert len(case_ids) == len(set(case_ids))

    for case in cases:
        assert case["id"]
        assert case["category"]
        assert case["message"]

        expect = case["expect"]
        assert isinstance(expect.get("required_tools", {}), dict)
        assert isinstance(expect.get("forbidden_tools", []), list)
        assert isinstance(expect.get("approval_required", False), bool)

        for tool_name, minimum_count in expect.get("required_tools", {}).items():
            assert isinstance(tool_name, str)
            assert tool_name
            assert isinstance(minimum_count, int)
            assert minimum_count >= 1
