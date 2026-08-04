"""Component tests for the UniversalChangelogParser (Feature 6).

Verifies the deterministic-first chain and the AI fallback that learns a
reusable rule:
1. learned_rule path: a persisted rule parses without calling AI and bumps
   rule_success_count.
2. AI fallback: when deterministic strategies fail, the AI agent is invoked;
   if it returns a deterministic_rule, the rule is persisted and the second
   parse skips the AI call entirely.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from progress.config.root import AnalysisConfig, CoreConfig
from progress.integrations.changelog.models import ChangelogTracker
from progress.integrations.changelog.parsers import ChangelogRule
from progress.integrations.changelog.tracker import (
    ChangelogStructureAnalysis,
    UniversalChangelogParser,
)

_MD = """# Changelog

## [1.2.0] - 2026-01-01

- feature a

## [1.1.0] - 2025-12-01

- feature b
"""

_IRREGULAR_HTML = """<html><body>
<div class="version">Release 9.9.9</div>
<div class="notes">big rewrite notes</div>
</body></html>
"""


def _tracker(*, parser_type: str = "auto", learned_rule: str | None = None) -> ChangelogTracker:
    row = ChangelogTracker(name="t", url="https://x", parser_type=parser_type, enabled=True)
    # learned_rule is a tortoise Field descriptor; bypass the descriptor via __dict__.
    object.__setattr__(row, "learned_rule", learned_rule)
    row.rule_success_count = 0
    # stub the async save() so the parser's `await tracker.save()` is a no-op
    save_mock: AsyncMock = AsyncMock()
    row.save = save_mock  # type: ignore[method-assign]
    # expose the mock for assertion via attribute on the row instance
    object.__setattr__(row, "_save_mock", save_mock)
    return row


async def test_built_in_markdown_strategy_matches_without_ai() -> None:
    parser = UniversalChangelogParser(cfg=None)
    row = _tracker(parser_type="auto")
    versions = await parser.parse(_MD, "https://x", row)
    assert [v.version for v in versions] == ["1.2.0", "1.1.0"]
    assert row.learned_rule is None
    save_mock: AsyncMock = object.__getattribute__(row, "_save_mock")
    save_mock.assert_not_awaited()  # no rule learned for built-in success


async def test_learned_rule_path_skips_ai_and_increments_count() -> None:
    rule = ChangelogRule(version_selector=None, version_pattern=r"\[(?P<version>\d+\.\d+\.\d+)\]")
    row = _tracker(learned_rule=rule.model_dump_json())
    parser = UniversalChangelogParser(cfg=None)
    versions = await parser.parse(_MD, "https://x", row)
    assert [v.version for v in versions] == ["1.2.0", "1.1.0"]
    assert row.rule_success_count == 1
    save_mock = object.__getattribute__(row, "_save_mock")
    save_mock.assert_awaited()  # rule success counter persisted


async def test_ai_fallback_persists_learned_rule_and_skips_ai_second_time() -> None:
    cfg = CoreConfig(analysis=AnalysisConfig(provider="x", model="m"))
    parser = UniversalChangelogParser(cfg=cfg)

    ai_output = ChangelogStructureAnalysis(
        deterministic_rule=ChangelogRule(
            version_selector="div.version",
            version_pattern=r"Release (?P<version>\d+\.\d+\.\d+)",
            body_selector="div.notes",
        ),
        versions=[],
    )
    with patch(
        "progress.integrations.changelog.tracker.run_extraction",
        new=AsyncMock(return_value=ai_output),
    ) as run_mock:
        row = _tracker(parser_type="html_generic")
        # First parse: html_generic strategy fails (no h1-h4 with version), AI runs,
        # learns the rule, persists it.
        versions = await parser.parse(_IRREGULAR_HTML, "https://x", row)
        assert run_mock.await_count == 1
        assert versions[0].version == "9.9.9"
        assert "big rewrite notes" in versions[0].description
        assert row.learned_rule is not None
        assert row.rule_success_count == 1

        # Second parse: learned_rule path now matches → AI is NOT called again.
        row2 = _tracker(learned_rule=row.learned_rule, parser_type="html_generic")
        versions2 = await parser.parse(_IRREGULAR_HTML, "https://x", row2)
        assert run_mock.await_count == 1  # unchanged
        assert versions2[0].version == "9.9.9"
        assert row2.rule_success_count == 1


async def test_ai_unavailable_returns_empty_when_no_deterministic_path() -> None:
    # cfg=None → build_model_string returns None → AI short-circuits to empty.
    parser = UniversalChangelogParser(cfg=None)
    row = _tracker(parser_type="html_generic")
    versions = await parser.parse(_IRREGULAR_HTML, "https://x", row)
    assert versions == []
