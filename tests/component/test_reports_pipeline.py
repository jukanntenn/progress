"""Component tests for the reports pipeline (spec 09, 15).

Real SQLite tmp file. Mocks the MarkPost service via unittest.mock.
Tests each stage (collect_outcome → render_sections → render_aggregated →
generate_title_summary → inject_summary → persist → publish_batches) and the
orchestrating ``run`` function.

Per the new spec 09:
- ``collect_outcome`` returns one ``ReportContext`` per integration that
  produced reports (not a single context).
- ``inject_summary`` prepends the AI summary to ``aggregated`` before persist.
- ``BATCH_MARGIN = 0.8`` effective limit; oversize stub for WebUI back-link.
- Batch rows: >1 URL → ``Batch`` rows; ==1 URL → ``Report.markpost_url``.
- Each batch dispatches one ``ReportEvent`` (collected into ``ReportOutcome.events``).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from markpost import MarkpostError
from pydantic import SecretStr
import pytest

from progress.cli.notifications.events import ReportEvent
from progress.cli.outcome import RunOutcome
from progress.cli.reports.markpost import MarkpostClient, split_batches
from progress.cli.reports.pipeline import (
    BATCH_MARGIN,
    ReportContext,
    Section,
    collect_outcome,
    inject_summary,
    publish_batches,
    render_aggregated,
    render_sections,
    run,
)
from progress.config.root import CoreConfig, MarkpostConfig, WebConfig
from progress.db import close_db, init_db
from progress.db.models.batch import Batch
from progress.db.models.report import Report
from progress.errors import ProgressException
from progress.integrations.base import ReportSection, RunResult
from progress.utils.i18n import set_locale


@pytest.fixture
async def db(tmp_state_home: str):
    await init_db(tmp_state_home)
    yield
    await close_db()


def _make_outcome_with_reports() -> RunOutcome:
    outcome = RunOutcome()
    result = RunResult(name="repo", status="success")
    result.reports.append(
        ReportSection(
            title="vitejs/vite",
            content="# Vite\n\nbody",
            payload={
                "repo_name": "vitejs/vite",
                "repo_web_url": "https://github.com/vitejs/vite",
                "branch": "main",
                "commit_count": 1,
                "commits": [{"subject": "fix: thing", "body": ""}],
                "analysis_summary": "",
                "analysis_detail": "",
                "status": "success",
                "truncated": False,
                "original_diff_length": 0,
                "analyzed_diff_length": 0,
                "releases_truncated": False,
                "releases_total_available": 0,
                "releases": None,
            },
        )
    )
    outcome.add("repo", result)
    return outcome


class TestCollectOutcome:
    def test_returns_one_context_per_integration(self) -> None:
        outcome = _make_outcome_with_reports()
        contexts = collect_outcome(outcome, generation_time="test")
        assert len(contexts) == 1
        assert contexts[0].integration_name == "repo"
        assert "vitejs/vite" in contexts[0].repo_statuses
        assert contexts[0].repo_statuses["vitejs/vite"] == "success"

    def test_empty_outcome(self) -> None:
        outcome = RunOutcome()
        contexts = collect_outcome(outcome, generation_time="test")
        assert contexts == []

    def test_skips_integrations_without_reports(self) -> None:
        outcome = RunOutcome()
        outcome.add("repo", RunResult(name="repo", reports=[]))
        outcome.add("changelog", RunResult(name="changelog", status="success"))
        contexts = collect_outcome(outcome, generation_time="test")
        assert contexts == []


class TestRenderSections:
    def test_renders_each_section(self) -> None:
        outcome = _make_outcome_with_reports()
        ctx = collect_outcome(outcome, generation_time="test")[0]
        sections = render_sections(ctx)
        assert len(sections) == 1
        assert sections[0].integration_name == "repo"
        assert "vitejs/vite" in sections[0].content

    def test_skips_empty_reports(self) -> None:
        outcome = RunOutcome()
        outcome.add("repo", RunResult(name="repo", status="success", reports=[]))
        contexts = collect_outcome(outcome, generation_time="test")
        assert contexts == []

    def test_discovery_section_uses_repo_new_template(self) -> None:
        """A ``report_type=repo_new`` section renders via its own template, not
        ``repo_report.j2`` — the discovery payload has no ``commit_count``, so
        routing it through the per-repo template raised ``UndefinedError``
        (the acceptance-log failure)."""
        outcome = RunOutcome()
        result = RunResult(name="repo", status="success")
        result.reports.append(
            ReportSection(
                title="Discovered repos under bytedance",
                content="",
                payload={
                    "report_type": "repo_new",
                    "owner": "bytedance",
                    "new_repos": [
                        {
                            "name": "bytedance/UniVR",
                            "url": "https://github.com/bytedance/UniVR",
                            "description": "A unified framework.",
                            "readme_summary": "AI summary",
                            "readme_detail": "AI detail",
                            "discovered_at": "2026-08-16",
                        }
                    ],
                },
            )
        )
        outcome.add("repo", result)
        ctx = collect_outcome(outcome, generation_time="test")[0]
        sections = render_sections(ctx)
        assert len(sections) == 1
        rendered = sections[0].content
        assert "bytedance" in rendered
        assert "bytedance/UniVR" in rendered
        assert "AI summary" in rendered
        assert "commit_count" not in rendered

    def test_missing_payload_key_degrades_gracefully(self) -> None:
        """StrictUndefined + a payload missing a template key must degrade, not
        crash: the section falls back to its raw ``content``, a
        ``section_render_failed`` business event is recorded, and the exception
        is reported to Bugsink. Guards the silent-empty-section bug class (an
        unwired v2ex report payload field shipped blank blocks to prod)."""
        outcome = RunOutcome()
        result = RunResult(name="repo", status="success")
        result.reports.append(
            ReportSection(
                title="vitejs/vite",
                content="# Vite\n\nbody",
                payload={
                    "repo_name": "vitejs/vite",
                    "repo_web_url": "https://github.com/vitejs/vite",
                    # commit_count / status / truncated / ... intentionally absent
                    "commits": [],
                },
            )
        )
        outcome.add("repo", result)
        ctx = collect_outcome(outcome, generation_time="test")[0]
        with (
            patch("progress.cli.reports.pipeline.record_business_event") as record_event,
            patch("progress.cli.reports.pipeline.sentry_sdk.capture_exception") as capture,
        ):
            sections = render_sections(ctx)
        assert len(sections) == 1
        assert sections[0].content == "# Vite\n\nbody"
        events = [c.args[0] for c in record_event.call_args_list]
        assert "progress.report.section_render_failed" in events
        capture.assert_called_once()


class TestRenderAggregated:
    def test_empty_returns_empty(self) -> None:
        ctx = ReportContext(outcome=RunOutcome(), integration_name="repo", report_type="repo_update")
        assert render_aggregated(ctx) == ""

    def test_includes_all_sections(self) -> None:
        outcome = _make_outcome_with_reports()
        ctx = collect_outcome(outcome, generation_time="test")[0]
        render_sections(ctx)
        out = render_aggregated(ctx)
        assert "vitejs/vite" in out

    def test_repo_new_excludes_indicator(self) -> None:
        """Feature 3: repo_new aggregated output has no status indicator."""
        ctx = ReportContext(
            outcome=RunOutcome(),
            integration_name="repo",
            report_type="repo_new",
            rendered_sections=[
                Section(
                    integration_name="repo",
                    content="### [repo1](url)\ndescription",
                    title="repo1",
                    status="success",
                ),
            ],
            repo_statuses={"repo1": "success"},
            generation_time="test",
        )
        out = render_aggregated(ctx)
        assert "✅" not in out
        assert "❌" not in out
        assert "➖" not in out
        assert "Repository details" not in out
        assert "仓库明细" not in out

    def test_repo_new_excludes_owner_heading(self) -> None:
        """Feature 3: repo_new section heading removed (owner implicit in repo name)."""
        ctx = ReportContext(
            outcome=RunOutcome(),
            integration_name="repo",
            report_type="repo_new",
            rendered_sections=[
                Section(
                    integration_name="repo",
                    content="### [microsoft/vscode](url)\ndescription",
                    title="microsoft/vscode",
                    status="success",
                ),
            ],
            repo_statuses={"microsoft/vscode": "success"},
            generation_time="test",
        )
        out = render_aggregated(ctx)
        assert "Discovered repositor" not in out
        assert "下发现的仓库" not in out

    def test_repo_update_retains_indicator(self) -> None:
        """Feature 3 regression: repo_update still shows status indicator."""
        ctx = ReportContext(
            outcome=RunOutcome(),
            integration_name="repo",
            report_type="repo_update",
            rendered_sections=[
                Section(
                    integration_name="repo",
                    content="# Vite\n\nbody",
                    title="vitejs/vite",
                    status="success",
                ),
            ],
            repo_statuses={"vitejs/vite": "success"},
            generation_time="test",
        )
        out = render_aggregated(ctx)
        assert "✅" in out
        assert "Repository details" in out

    def test_repo_new_multi_owner_preserves_all_repos(self) -> None:
        """Feature 3: removing heading does not drop repos from different owners."""
        ctx = ReportContext(
            outcome=RunOutcome(),
            integration_name="repo",
            report_type="repo_new",
            rendered_sections=[
                Section(
                    integration_name="repo",
                    content="### [microsoft/vscode](url)\ndesc1",
                    title="microsoft/vscode",
                    status="success",
                ),
                Section(
                    integration_name="repo",
                    content="### [google/guava](url2)\ndesc2",
                    title="google/guava",
                    status="success",
                ),
            ],
            repo_statuses={
                "microsoft/vscode": "success",
                "google/guava": "success",
            },
            generation_time="test",
        )
        out = render_aggregated(ctx)
        assert "microsoft/vscode" in out
        assert "google/guava" in out

    def test_release_br_spacing_multiple_releases(self) -> None:
        """Feature 4: <br> appears before 2nd and 3rd release, not before 1st."""
        releases = [
            {"name": "v1.0", "tag": "v1.0", "notes_html": "", "ai_summary": "", "ai_detail": ""},
            {"name": "v2.0", "tag": "v2.0", "notes_html": "", "ai_summary": "", "ai_detail": ""},
            {"name": "v3.0", "tag": "v3.0", "notes_html": "", "ai_summary": "", "ai_detail": ""},
        ]
        ctx = ReportContext(
            outcome=RunOutcome(),
            integration_name="repo",
            report_type="repo_update",
            rendered_sections=[
                Section(
                    integration_name="repo",
                    content="",
                    title="vitejs/vite",
                    status="success",
                ),
            ],
            sections_input=[
                ReportSection(
                    title="vitejs/vite",
                    content="",
                    payload={
                        "repo_name": "vitejs/vite",
                        "repo_web_url": "https://github.com/vitejs/vite",
                        "status": "success",
                        "releases": releases,
                        "releases_truncated": False,
                        "commit_count": 0,
                        "branch": "main",
                        "commits": [],
                        "analysis_summary": "",
                        "analysis_detail": "",
                    },
                ),
            ],
            repo_statuses={"vitejs/vite": "success"},
            generation_time="test",
        )
        render_sections(ctx)
        out = render_aggregated(ctx)
        # Count <br> tags: should be exactly 2 (before 2nd and 3rd release)
        assert out.count("<br>") == 2

    def test_release_br_spacing_single_release(self) -> None:
        """Feature 4: single release produces no <br> spacing."""
        ctx = ReportContext(
            outcome=RunOutcome(),
            integration_name="repo",
            report_type="repo_update",
            rendered_sections=[
                Section(
                    integration_name="repo",
                    content="",
                    title="vitejs/vite",
                    status="success",
                ),
            ],
            sections_input=[
                ReportSection(
                    title="vitejs/vite",
                    content="",
                    payload={
                        "repo_name": "vitejs/vite",
                        "repo_web_url": "https://github.com/vitejs/vite",
                        "status": "success",
                        "releases": [
                            {"name": "v1.0", "tag": "v1.0", "notes_html": "", "ai_summary": "", "ai_detail": ""},
                        ],
                        "releases_truncated": False,
                        "commit_count": 0,
                        "branch": "main",
                        "commits": [],
                        "analysis_summary": "",
                        "analysis_detail": "",
                    },
                ),
            ],
            repo_statuses={"vitejs/vite": "success"},
            generation_time="test",
        )
        render_sections(ctx)
        out = render_aggregated(ctx)
        assert "<br>" not in out

    def test_release_truncation_i18n_chinese(self) -> None:
        """Feature 4: truncated release message shows total and is translated to Chinese."""

        set_locale("zh-hans")
        try:
            ctx = ReportContext(
                outcome=RunOutcome(),
                integration_name="repo",
                report_type="repo_update",
                rendered_sections=[
                    Section(
                        integration_name="repo",
                        content="",
                        title="vitejs/vite",
                        status="success",
                    ),
                ],
                sections_input=[
                    ReportSection(
                        title="vitejs/vite",
                        content="",
                        payload={
                            "repo_name": "vitejs/vite",
                            "repo_web_url": "https://github.com/vitejs/vite",
                            "status": "success",
                            "releases": [
                                {"name": "v1.0", "tag": "v1.0", "notes_html": "", "ai_summary": "", "ai_detail": ""},
                            ],
                            "releases_truncated": True,
                            "releases_total_available": 5,
                            "commit_count": 0,
                            "branch": "main",
                            "commits": [],
                            "analysis_summary": "",
                            "analysis_detail": "",
                        },
                    ),
                ],
                repo_statuses={"vitejs/vite": "success"},
                generation_time="test",
            )
            render_sections(ctx)
            out = render_aggregated(ctx)
            assert "自上次追踪以来共有 5 个新版本" in out
            assert "仅展示最新 1 个" in out
            assert "More releases exist" not in out
        finally:
            set_locale("en")

    """Spec 09 — restored summary prepend."""

    def test_summary_prepended(self) -> None:
        result = inject_summary("body", "Overview text")
        assert result == "Overview text\n\nbody"

    def test_empty_summary_no_prepend(self) -> None:
        assert inject_summary("body", "") == "body"

    def test_whitespace_only_summary_no_prepend(self) -> None:
        assert inject_summary("body", "   \n  ") == "body"


class TestSplitBatches:
    def test_empty_returns_empty(self) -> None:
        assert split_batches("", 100) == []

    def test_small_content_single_batch(self) -> None:
        assert split_batches("hello", 100) == ["hello"]

    def test_max_size_zero_returns_single(self) -> None:
        assert split_batches("hello", 0) == ["hello"]

    def test_splits_on_separator(self) -> None:
        content = "part1\n---\npart2"
        batches = split_batches(content, 6)
        assert len(batches) == 2

    def test_oversized_section_emitted_alone(self) -> None:
        big = "x" * 100
        content = f"{big}\n---\nsmall"
        batches = split_batches(content, 50)
        assert len(batches) == 2


class TestMarkpostClient:
    @patch("progress.cli.reports.markpost.AsyncMarkpost")
    async def test_upload_success(self, mock_cls: AsyncMock, tmp_state_home: str) -> None:
        mock_client = AsyncMock()
        mock_client.create_post = AsyncMock(return_value=SimpleNamespace(id="p-abc123"))
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        cfg = MarkpostConfig(enabled=True, url=SecretStr("https://markpost.cc/mpk-key"))
        client = MarkpostClient(cfg)
        published = await client.upload("body", title="t")

        assert published == "https://markpost.cc/p-abc123"
        mock_client.create_post.assert_awaited_once_with("t", "body")

    async def test_missing_url_raises(self, tmp_state_home: str) -> None:
        cfg = MarkpostConfig(enabled=True, url=SecretStr(""))
        with pytest.raises(Exception, match="markpost url"):
            MarkpostClient(cfg)

    @patch("progress.cli.reports.markpost.AsyncMarkpost")
    async def test_upload_network_error(self, mock_cls: AsyncMock, tmp_state_home: str) -> None:

        mock_client = AsyncMock()
        mock_client.create_post = AsyncMock(side_effect=MarkpostError("connection failed"))
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        cfg = MarkpostConfig(enabled=True, url=SecretStr("https://markpost.cc/mpk-key"))
        client = MarkpostClient(cfg)
        with pytest.raises(Exception, match="markpost upload failed"):
            await client.upload("body", title="t")


class TestPublishBatches:
    @patch("progress.cli.reports.pipeline.MarkpostClient")
    async def test_single_url_writes_markpost_url_directly(
        self,
        mock_client_cls: AsyncMock,
        db: None,
        tmp_state_home: str,
    ) -> None:
        mock_instance = AsyncMock()
        mock_instance.upload = AsyncMock(return_value="https://markpost.cc/p-5")
        mock_instance.max_batch_size = 1_000_000
        mock_client_cls.return_value = mock_instance

        markpost_cfg = MarkpostConfig(
            enabled=True, url=SecretStr("https://markpost.cc/mpk-key"), max_batch_size=1_000_000
        )
        web_cfg = WebConfig()
        outcome = _make_outcome_with_reports()
        ctx = collect_outcome(outcome, generation_time="test")[0]
        render_sections(ctx)
        aggregated = render_aggregated(ctx)
        report = await Report.create(
            report_type="repo_update",
            title="t",
            commit_hash="",
            commit_count=1,
            content=aggregated,
        )
        urls = await publish_batches(report.id, aggregated, "summary", "title", ctx, markpost_cfg, web_cfg)
        assert len(urls) == 1
        rows = await Batch.filter(report_id=report.id).all()
        assert len(rows) == 0
        refreshed = await Report.get(id=report.id)
        assert refreshed.markpost_url is not None
        assert refreshed.markpost_url.endswith("/p-5")

    async def test_batch_margin_applied(self) -> None:
        assert BATCH_MARGIN == 0.9


def _make_outcome_with_many_repos(n: int = 6) -> RunOutcome:
    """Outcome with ``n`` repos whose rendered sections force a multi-batch split."""
    outcome = RunOutcome()
    result = RunResult(name="repo", status="success")
    for i in range(n):
        result.reports.append(
            ReportSection(
                title=f"owner{i}/repo{i}",
                content=f"# repo{i}\n\n{'x' * 500}\n\n## sub heading",
                payload={
                    "repo_name": f"owner{i}/repo{i}",
                    "repo_web_url": f"https://github.com/owner{i}/repo{i}",
                    "branch": "main",
                    "commit_count": 1,
                    "commits": [{"subject": "fix: thing", "body": ""}],
                    "analysis_summary": "",
                    "analysis_detail": "",
                    "releases": None,
                },
            )
        )
    outcome.add("repo", result)
    return outcome


class TestOversizeBatchDegradation:
    """Regression for the silent batch-drop bug (2026-08-02 incident).

    A batch that exceeds ``max_batch_size`` must never be silently dropped: with
    ``web.base_url`` set it degrades to a WebUI back-link stub; without it the
    batch is still recorded (empty URL) and the outcome is marked partial. In
    both cases the DB keeps a ``Batch`` row for every seq and the full content
    lives in ``Report.content``.
    """

    @patch("progress.cli.reports.pipeline.MarkpostClient")
    async def test_oversize_degrades_to_stub_when_web_base_url_set(
        self,
        mock_client_cls: AsyncMock,
        db: None,
        tmp_state_home: str,
    ) -> None:
        mock_instance = AsyncMock()
        mock_instance.upload = AsyncMock(side_effect=lambda body, title: f"https://markpost.cc/p-{title[-1:]}")
        mock_instance.max_batch_size = 300
        mock_client_cls.return_value = mock_instance

        outcome = _make_outcome_with_many_repos(6)
        cfg = CoreConfig(
            state_home=tmp_state_home,
            markpost=MarkpostConfig(enabled=True, url=SecretStr("https://markpost.cc/mpk-key")),
            web=WebConfig(base_url="https://progress.example.com"),
        )
        report_outcome = await run(outcome, cfg)

        assert report_outcome.status == "success"
        assert len(report_outcome.report_ids) == 1
        report_id = report_outcome.report_ids[0]

        batches = await Batch.filter(report_id=report_id).order_by("seq")
        assert len(batches) >= 2, "expected a multi-batch split"
        for row in batches:
            assert row.markpost_url, f"batch seq={row.seq} dropped (empty url); should have stub-degraded"

        uploaded_bodies = [call.args[0] for call in mock_instance.upload.call_args_list]
        assert any("View the complete report in the WebUI" in b for b in uploaded_bodies), (
            "expected at least one oversize batch to degrade to a WebUI stub"
        )

        full = await Report.get(id=report_id)
        assert full.content and len(full.content.encode("utf-8")) > 300

    @patch("progress.cli.reports.pipeline.MarkpostClient")
    async def test_oversize_records_empty_batch_and_marks_partial_without_web_base_url(
        self,
        mock_client_cls: AsyncMock,
        db: None,
        tmp_state_home: str,
    ) -> None:
        mock_instance = AsyncMock()
        mock_instance.upload = AsyncMock(return_value="https://markpost.cc/p-ok")
        mock_instance.max_batch_size = 300
        mock_client_cls.return_value = mock_instance

        outcome = _make_outcome_with_many_repos(6)
        cfg = CoreConfig(
            state_home=tmp_state_home,
            markpost=MarkpostConfig(enabled=True, url=SecretStr("https://markpost.cc/mpk-key")),
            web=WebConfig(),
        )
        report_outcome = await run(outcome, cfg)

        assert report_outcome.status == "partial"
        assert report_outcome.errors, "expected an error recorded for the unresolvable oversize batch"
        report_id = report_outcome.report_ids[0]

        batches = await Batch.filter(report_id=report_id).order_by("seq")
        assert len(batches) >= 2, "expected a multi-batch split"
        urls = [row.markpost_url for row in batches]
        assert "" in urls, "expected at least one empty-url batch row (no web.base_url to stub)"
        assert len(urls) == len(batches), "every seq must keep a DB row even when it cannot upload"


class TestRunEndToEnd:
    async def test_run_persists_aggregated_report(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:
        outcome = _make_outcome_with_reports()
        cfg = CoreConfig(state_home=tmp_state_home)
        report_outcome = await run(outcome, cfg)
        assert report_outcome.status == "success"
        assert len(report_outcome.report_ids) == 1
        rows = await Report.filter(report_type="repo_update").all()
        assert len(rows) == 1
        assert rows[0].content

    @patch("progress.cli.reports.pipeline.MarkpostClient")
    async def test_run_emits_report_events_when_markpost_enabled(
        self,
        mock_client_cls: AsyncMock,
        db: None,
        tmp_state_home: str,
    ) -> None:
        mock_instance = AsyncMock()
        mock_instance.upload = AsyncMock(return_value="https://markpost.cc/p-1")
        mock_instance.max_batch_size = 1_048_576
        mock_client_cls.return_value = mock_instance

        outcome = _make_outcome_with_reports()
        cfg = CoreConfig(
            state_home=tmp_state_home,
            markpost=MarkpostConfig(enabled=True, url=SecretStr("https://markpost.cc/mpk-key")),
        )
        report_outcome = await run(outcome, cfg)
        assert len(report_outcome.events) >= 1
        assert all(isinstance(e, ReportEvent) for e in report_outcome.events)

    async def test_run_empty_outcome_succeeds(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:
        outcome = RunOutcome()
        cfg = CoreConfig(state_home=tmp_state_home)
        report_outcome = await run(outcome, cfg)
        assert report_outcome.status == "success"
        assert report_outcome.report_ids == []

    @patch("progress.cli.reports.pipeline.MarkpostClient")
    async def test_run_markpost_failure_does_not_block(
        self,
        mock_client_cls: AsyncMock,
        db: None,
        tmp_state_home: str,
    ) -> None:

        mock_instance = AsyncMock()
        mock_instance.upload = AsyncMock(side_effect=ProgressException("network error"))
        mock_instance.max_batch_size = 1_048_576
        mock_client_cls.return_value = mock_instance

        outcome = _make_outcome_with_reports()
        cfg = CoreConfig(
            state_home=tmp_state_home,
            markpost=MarkpostConfig(enabled=True, url=SecretStr("https://markpost.cc/mpk-key")),
        )
        report_outcome = await run(outcome, cfg)
        assert len(report_outcome.report_ids) == 1

    @patch("progress.cli.reports.pipeline.MarkpostClient")
    async def test_markpost_summary_grid_includes_skipped_repos(
        self,
        mock_client_cls: AsyncMock,
        db: None,
        tmp_state_home: str,
    ) -> None:
        """Regression: the ✅/❌/➖ summary grid uploaded to MarkPost must list
        every repo in the run (including skipped/➖ ones), matching what gets
        persisted to the DB. Previously the per-batch upload rebuilt
        ``repo_statuses`` from only the rendered sections (which exclude
        skipped), so MarkPost showed ``➖ 0`` and dropped the skipped repos
        while the DB copy kept them."""
        mock_instance = AsyncMock()
        mock_instance.upload = AsyncMock(return_value="https://markpost.cc/p-1")
        mock_instance.max_batch_size = 1_048_576
        mock_client_cls.return_value = mock_instance

        # Two repos: one with commits (success), one skipped (no changes).
        outcome = RunOutcome()
        result = RunResult(name="repo", status="success")
        result.reports.append(
            ReportSection(
                title="ok/repo",
                content="# ok\n\nbody",
                payload={
                    "report_type": "repo_update",
                    "repo_name": "ok/repo",
                    "repo_web_url": "https://github.com/ok/repo",
                    "branch": "main",
                    "commit_count": 1,
                    "commits": [{"subject": "fix: thing", "body": ""}],
                    "analysis_summary": "",
                    "analysis_detail": "",
                    "truncated": False,
                    "original_diff_length": 0,
                    "analyzed_diff_length": 0,
                    "releases": None,
                    "status": "success",
                },
            )
        )
        result.reports.append(
            ReportSection(
                title="skipped/repo",
                content="",
                payload={
                    "report_type": "repo_update",
                    "status": "skipped",
                    "repo_name": "skipped/repo",
                    "repo_web_url": "https://github.com/skipped/repo",
                    "branch": "main",
                    "commit_count": 0,
                    "commits": [],
                    "analysis_summary": "",
                    "analysis_detail": "",
                    "truncated": False,
                    "original_diff_length": 0,
                    "analyzed_diff_length": 0,
                    "releases": None,
                },
            )
        )
        outcome.add("repo", result)
        cfg = CoreConfig(
            state_home=tmp_state_home,
            markpost=MarkpostConfig(enabled=True, url=SecretStr("https://markpost.cc/mpk-key")),
        )
        await run(outcome, cfg)

        # The MarkPost upload body must contain BOTH repos in the summary grid.
        uploaded_body = mock_instance.upload.call_args.args[0]
        assert "ok/repo" in uploaded_body
        assert "skipped/repo" in uploaded_body
        # And the grid count reflects the skipped repo (➖ 1, not ➖ 0).
        assert "➖ 1" in uploaded_body
