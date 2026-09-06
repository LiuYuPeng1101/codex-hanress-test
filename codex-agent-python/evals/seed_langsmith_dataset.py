from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from langsmith import Client
from langsmith.utils import LangSmithNotFoundError

DEFAULT_CASES = Path(__file__).with_name("cases.jsonl")
DEFAULT_DATASET = "codex-order-agent-seed"


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
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
    except LangSmithNotFoundError:
        dataset = client.create_dataset(
            dataset_name=args.dataset,
            description=(
                "Codex 单 Agent 的人工 Golden/Seed Dataset。"
                "正式题库后续应继续吸收生产失败 Case、人工标注和合成变体。"
            ),
        )

    added, updated = sync_cases(client, dataset.id, cases)
    print(f"Dataset {dataset.name}: added={added} updated={updated}")


def sync_cases(client, dataset_id, cases):
    """Update only seed-owned examples; preserve human annotations and other datasets."""
    existing = {}
    for example in client.list_examples(dataset_id=dataset_id):
        metadata = example.metadata or {}
        case_id = metadata.get("case_id")
        if case_id:
            if case_id in existing:
                raise ValueError(f"Duplicate remote case_id: {case_id}")
            existing[case_id] = example
    ids = [case["id"] for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate seed case IDs")
    added = updated = 0
    for case in cases:
        inputs = {
            "message": case["message"],
            "category": case["category"],
            "requires_fixture": case.get("requires_fixture"),
        }
        outputs = {"expect": case["expect"]}
        metadata = {"case_id": case["id"], "source": "seed-jsonl", "category": case["category"]}
        previous = existing.get(case["id"])
        if previous is None:
            client.create_example(
                dataset_id=dataset_id, inputs=inputs, outputs=outputs, metadata=metadata
            )
            added += 1
        elif previous.inputs != inputs or previous.outputs != outputs:
            if (previous.metadata or {}).get("source") != "seed-jsonl":
                raise ValueError(f"Refusing to overwrite a non-seed example: {case['id']}")
            client.update_example(
                previous.id,
                inputs=inputs,
                outputs=outputs,
                metadata={**(previous.metadata or {}), **metadata},
            )
            updated += 1
    return added, updated


if __name__ == "__main__":
    main()
