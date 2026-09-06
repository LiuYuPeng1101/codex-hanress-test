from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from evals.seed_langsmith_dataset import sync_cases

CASE = {"id": "a", "message": "new question", "category": "tool", "expect": {}}


def test_modified_seed_updates_existing_example_preserving_annotation():
    client = Mock()
    client.list_examples.return_value = [
        NS(
            id="id-a",
            inputs={},
            outputs={},
            metadata={"case_id": "a", "source": "seed-jsonl", "reviewer": "human"},
        )
    ]
    assert sync_cases(client, "dataset-a", [CASE]) == (0, 1)
    assert client.update_example.call_args.kwargs["metadata"]["reviewer"] == "human"
    client.create_example.assert_not_called()


def test_nonseed_example_is_not_overwritten():
    client = Mock()
    client.list_examples.return_value = [
        NS(id="id-a", inputs={}, outputs={}, metadata={"case_id": "a", "source": "production"})
    ]
    with pytest.raises(ValueError):
        sync_cases(client, "dataset", [CASE])
    client.update_example.assert_not_called()
