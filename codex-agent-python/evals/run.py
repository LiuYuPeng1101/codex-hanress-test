"""Local smoke runner using the same target and deterministic contracts as LangSmith."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from evals.langsmith_evaluators import (
    approval_evaluator,
    response_contract_evaluator,
    tool_policy_evaluator,
)
from evals.langsmith_target import LangSmithAgentTarget


def main() -> int:
    parser = argparse.ArgumentParser(description="运行单 Agent 黑盒 smoke Evals")
    parser.add_argument("--cases", default=str(Path(__file__).with_name("cases.jsonl")))
    parser.add_argument("--base-url", default=os.getenv("EVAL_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    secret = os.getenv("EVAL_API_SHARED_SECRET")
    if not secret:
        parser.error("缺少专用测试环境的 EVAL_API_SHARED_SECRET")
    target = LangSmithAgentTarget(
        base_url=args.base_url, api_secret=secret, timeout_seconds=args.timeout
    )
    cases = [json.loads(line) for line in Path(args.cases).read_text().splitlines() if line.strip()]
    passed = failed = skipped = 0
    for case in cases:
        try:
            output = target(case)
            if output.get("skipped"):
                status = "SKIPPED"
                skipped += 1
            else:
                scores = [
                    e(case, output, {"expect": case["expect"]})["score"]
                    for e in (
                        tool_policy_evaluator,
                        approval_evaluator,
                        response_contract_evaluator,
                    )
                ]
                if all(score == 1 for score in scores):
                    status = "PASSED"
                    passed += 1
                else:
                    status = "FAILED"
                    failed += 1
        except Exception:
            # Raw HTTP/provider exceptions may contain test data or credentials.
            status = "ERROR"
            failed += 1
        print(f"[{status}] {case['id']}")
    print(f"total={len(cases)} passed={passed} failed={failed} skipped={skipped}")
    return 0 if cases and not failed and not skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
