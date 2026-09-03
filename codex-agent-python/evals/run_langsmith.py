from __future__ import annotations

import argparse
import os

from langsmith import Client

from langsmith_evaluators import default_evaluators
from langsmith_target import LangSmithAgentTarget


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 LangSmith 单 Agent Experiment")
    parser.add_argument(
        "--dataset",
        default=os.getenv("LANGSMITH_EVAL_DATASET", "codex-order-agent-seed"),
    )
    parser.add_argument(
        "--experiment-prefix",
        default=os.getenv("LANGSMITH_EXPERIMENT_PREFIX", "order-agent"),
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=int(os.getenv("LANGSMITH_EVAL_MAX_CONCURRENCY", "2")),
    )
    args = parser.parse_args()

    # Agent 本身依旧是 Codex Harness。LangSmith 只拿到一个普通 target function。
    target = LangSmithAgentTarget.from_env()
    client = Client()
    results = client.evaluate(
        target,
        data=args.dataset,
        evaluators=default_evaluators(),
        experiment_prefix=args.experiment_prefix,
        max_concurrency=args.max_concurrency,
        metadata={
            "agent": "order-agent",
            "runtime": "codex-harness",
            "eval_type": "black-box-agent",
        },
    )
    print(results)


if __name__ == "__main__":
    main()
