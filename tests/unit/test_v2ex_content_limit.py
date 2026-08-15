"""Unit tests for the v2ex dynamic original-content cap.

:func:`progress.integrations.v2ex.fetcher.v2ex_content_limit` bounds the
worst-case AI input (max_summaries posts at the cap) inside a 120K-token
budget while never regressing below the old fixed 4K limit.
"""

from __future__ import annotations

from progress.integrations.v2ex.fetcher import (
    V2EX_AI_TOKEN_BUDGET,
    V2EX_MIN_CONTENT_LIMIT,
    v2ex_content_limit,
)


class TestV2exContentLimit:
    def test_default_post_count_yields_budget_share(self) -> None:
        # default max_summaries = 8 → 120_000 / 8
        assert v2ex_content_limit(8) == 15_000

    def test_max_post_count_still_above_old_fixed_limit(self) -> None:
        assert v2ex_content_limit(20) == 6_000
        assert v2ex_content_limit(20) >= 4_000

    def test_small_post_count_gets_full_budget(self) -> None:
        assert v2ex_content_limit(1) == V2EX_AI_TOKEN_BUDGET

    def test_never_below_floor_even_for_zero_posts(self) -> None:
        assert v2ex_content_limit(0) == V2EX_AI_TOKEN_BUDGET
        assert v2ex_content_limit(1000) == V2EX_MIN_CONTENT_LIMIT
