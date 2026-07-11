from __future__ import annotations

import json

import pytest

from teamshared.memory.partner_eval import (
    load_partner_cases,
    score_partner_case,
    summarize_partner_results,
)


def test_partner_case_requires_expected_anchor_and_rejects_forbidden() -> None:
    case = {
        "name": "database decision",
        "query": "database",
        "expected_text_any": ["pgvector"],
        "forbidden_text_any": ["pinecone is selected"],
    }
    passing = score_partner_case(
        case, [{"content": "We selected pgvector.", "agent": "cursor"}]
    )
    failing = score_partner_case(
        case,
        [{"content": "pgvector was considered; Pinecone is selected.", "agent": "hermes"}],
    )

    assert passing["passed"] is True
    assert failing["passed"] is False
    assert failing["forbidden_hit"] is True


def test_partner_result_summary() -> None:
    report = summarize_partner_results(
        [{"passed": True}, {"passed": False}, {"passed": True}]
    )
    assert report["pass_rate"] == pytest.approx(2 / 3)
    assert report["failed"] == 1


def test_load_partner_cases_validates_schema(tmp_path) -> None:
    fixture = tmp_path / "cases.json"
    fixture.write_text(json.dumps({"cases": [{"name": "x", "query": "y"}]}))
    assert load_partner_cases(fixture)[0]["name"] == "x"

    fixture.write_text(json.dumps({"cases": []}))
    with pytest.raises(ValueError, match="non-empty"):
        load_partner_cases(fixture)
