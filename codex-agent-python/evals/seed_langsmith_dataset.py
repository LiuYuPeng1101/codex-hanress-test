from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from langsmith import Client

DEFAULT_CASES = Path(__file__).with_name("cases.jsonl")
DEFAULT_DATASET = "codex-order-agent-seed"


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="把本地 Seed Case 导入 LangSmith Dataset")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    args = parser.parse_args()

    client = Client()
    cases = load_cases(Path(args.cases))

    try:
        dataset = client.read_dataset(dataset_name=args.dataset)
    except Exception:
        dataset = client.create_dataset(
            dataset_name=args.dataset,
            description=(
                "Codex 单 Agent 的人工 Golden/Seed Dataset。"
                "正式题库后续应继续吸收生产失败 Case、人工标注和合成变体。"
            ),
        )

    existing_ids = {
        str(example.metadata.get("case_id"))
        for example in client.list_examples(dataset_id=dataset.id)
        if example.metadata and example.metadata.get("case_id")
    }
    new_cases = [case for case in cases if case["id"] not in existing_ids]

    if not new_cases:
        print(f"Dataset {dataset.name} 已包含当前全部 Seed Case")
        return

    examples = [
        {
            "inputs": {
                "message": case["message"],
                "category": case["category"],
                "requires_fixture": case.get("requires_fixture"),
            },
            "outputs": {"expect": case["expect"]},
            "metadata": {
                "case_id": case["id"],
                "source": "seed-jsonl",
                "category": case["category"],
            },
        }
        for case in new_cases
    ]
    client.create_examples(dataset_id=dataset.id, examples=examples)
    print(f"Dataset {dataset.name} 新增 {len(examples)} 条 Seed Case")


if __name__ == "__main__":
    main()
