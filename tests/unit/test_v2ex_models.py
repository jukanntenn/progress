"""Unit tests for v2ex AI output models (spec v2ex §6/§7).

The json_repair fallback itself lives in the agent's output validator
(``_validate_with_repair``); here we cover the model deserialization contract
and field constraints that the validator depends on.
"""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from progress.integrations.v2ex.tracker import (
    V2exClassificationResult,
    V2exPostClassification,
    V2exSummaryResult,
)


class TestClassificationResult:
    def test_round_trip(self) -> None:
        result = V2exClassificationResult.model_validate_json(
            '{"posts": [{"post_index": 0, "interested": true, "score": 9, "reason": "match"}]}'
        )
        assert len(result.posts) == 1
        assert result.posts[0].interested is True
        assert result.posts[0].score == 9

    def test_empty_default(self) -> None:
        result = V2exClassificationResult.model_validate_json('{"posts": []}')
        assert result.posts == []

    def test_score_bounds(self) -> None:
        with pytest.raises(ValidationError):
            V2exPostClassification(post_index=0, score=11)
        with pytest.raises(ValidationError):
            V2exPostClassification(post_index=0, score=-1)

    def test_missing_fields_default(self) -> None:
        item = V2exPostClassification(post_index=3)
        assert item.interested is False
        assert item.score == 0
        assert item.reason == ""


class TestSummaryResult:
    def test_round_trip(self) -> None:
        result = V2exSummaryResult.model_validate_json(
            '{"posts": [{"post_index": 0, "takeaway": "rust backend, remote"}]}'
        )
        assert result.posts[0].takeaway == "rust backend, remote"

    def test_empty_default(self) -> None:
        assert V2exSummaryResult.model_validate_json('{"posts": []}').posts == []
