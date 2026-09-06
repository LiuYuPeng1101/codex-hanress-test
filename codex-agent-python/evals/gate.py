"""Offline experiment release gate; no LangSmith dependency or remote side effects."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

REQUIRED_SCORES = frozenset({"tool_policy", "approval_policy", "response_contract"})


@dataclass(frozen=True)
class GateSummary:
    total: int
    failed: int
    skipped: int

    @property
    def passed(self) -> bool:
        return self.total > 0 and self.failed == 0 and self.skipped == 0


def summarize_results(rows: Iterable[Mapping[str, Any]]) -> GateSummary:
    total = failed = skipped = 0
    for row in rows:
        total += 1
        run = row.get("run")
        output = getattr(run, "outputs", None) or {}
        if output.get("skipped"):
            skipped += 1
            continue
        feedback = row.get("evaluation_results", {}).get("results", [])
        scores = {entry.key: entry.score for entry in feedback}
        if (
            run is None
            or getattr(run, "error", None)
            or output.get("execution_status") != "completed"
            or any(scores.get(key) != 1 for key in REQUIRED_SCORES)
        ):
            failed += 1
    return GateSummary(total, failed, skipped)
