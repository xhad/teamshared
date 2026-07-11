"""Design-partner recall replay scoring.

Fixtures contain real queries plus expected text anchors, but no credentials or
raw tool transcripts. Keep private partner fixtures outside git under
``eval/private/`` and use the committed example as the schema contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_partner_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("partner eval fixture must contain a non-empty 'cases' list")
    for case in cases:
        if not isinstance(case, dict) or not case.get("name") or not case.get("query"):
            raise ValueError("every partner eval case requires name and query")
    return cases


def score_partner_case(
    case: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any]:
    contents = [str(record.get("content") or "").lower() for record in records]
    expected = [str(value).lower() for value in case.get("expected_text_any", [])]
    forbidden = [str(value).lower() for value in case.get("forbidden_text_any", [])]
    expected_hit = not expected or any(
        anchor in content for anchor in expected for content in contents
    )
    forbidden_hit = any(
        anchor in content for anchor in forbidden for content in contents
    )
    return {
        "name": str(case["name"]),
        "passed": expected_hit and not forbidden_hit,
        "expected_hit": expected_hit,
        "forbidden_hit": forbidden_hit,
        "returned": len(records),
        "writers": len(
            {str(record.get("agent")) for record in records if record.get("agent")}
        ),
    }


def summarize_partner_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for result in results if result["passed"])
    total = len(results)
    return {
        "case_count": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": passed / total if total else 0.0,
        "cases": results,
    }
