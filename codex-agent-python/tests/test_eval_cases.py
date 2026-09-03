import json
from pathlib import Path


CASES_PATH = Path(__file__).parents[1] / "evals" / "cases.jsonl"


def test_eval_cases_have_unique_ids_and_valid_expectations() -> None:
    cases = [
        json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(cases) >= 20
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))

    for case in cases:
        assert isinstance(case["id"], str) and case["id"]
        assert isinstance(case["category"], str) and case["category"]
        assert isinstance(case["message"], str) and case["message"]
        expect = case["expect"]
        assert isinstance(expect.get("required_tools", {}), dict)
        assert isinstance(expect.get("forbidden_tools", []), list)
        assert isinstance(expect.get("approval_required", False), bool)

        for tool_name, minimum_count in expect.get("required_tools", {}).items():
            assert isinstance(tool_name, str) and tool_name
            assert isinstance(minimum_count, int) and minimum_count >= 1
