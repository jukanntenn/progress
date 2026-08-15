"""Component tests for the v2ex integration tracker (spec v2ex §4-10).

Drives the Integration Protocol boundary with pytest-httpserver (V2EX HTML) +
monkeypatched AI (``run_extraction`` / ``build_model_string``). Real SQLite +
real aiohttp session. Asserts observable behaviour only: ``RunResult`` shape,
``ReportSection`` payload, ``NotificationEvent`` contract, persisted water marks.
"""

from __future__ import annotations

from pathlib import Path
import re

import aiohttp
import pytest
from werkzeug.wrappers import Response

from progress.cli.reports.pipeline import (
    IntegrationReport,
    _commit_count_for,
    _report_type_for,
)
from progress.config.root import CoreConfig
from progress.db import close_db, init_db, set_config
from progress.errors import ProgressException
from progress.integrations.base import Components, ReportSection, RunResult
from progress.integrations.v2ex.config import V2exIntegrationConfig
from progress.integrations.v2ex.models import V2exTracker
from progress.integrations.v2ex.tracker import (
    V2exClassificationResult,
    V2exIntegration,
    V2exPostClassification,
    V2exPostSummary,
    V2exSummaryResult,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "v2ex"


# --- HTML fixtures -----------------------------------------------------------


def _cell(
    topic_id: int,
    title: str,
    *,
    node_slug: str = "jobs",
    node_name: str = "酷工作",
    replies: int = 0,
) -> str:
    last = "" if replies == 0 else ' • 最后回复来自 <strong><a href="/member/user_002">user_002</a></strong>'
    return (
        f'<div class="cell item"><table><tr>'
        f'<td><span class="item_title"><a href="/t/{topic_id}#reply{replies}" '
        f'id="topic-link-{topic_id}" class="topic-link">{title}</a></span>'
        f'<span class="topic_info"><a class="node" href="/go/{node_slug}">{node_name}</a> • '
        f'<strong><a href="/member/user_001">user_001</a></strong> • '
        f'<span title="2026-08-12 10:00:00 +08:00">x</span>{last}</span></td>'
        f'<td><a href="/t/{topic_id}#reply{replies}" class="count_livid">{replies}</a></td>'
        f"</tr></table></div>"
    )


def _tab_html(*cells: str) -> str:
    return f"<html><body>{''.join(cells)}</body></html>"


def _topic_html(body: str) -> str:
    return f'<html><body><div class="topic_content">{body}</div></body></html>'


def _classification(*verdicts: tuple[int, bool, int]) -> V2exClassificationResult:
    """Build a classify result: (index, interested, score) per input topic."""
    return V2exClassificationResult(
        posts=[
            V2exPostClassification(post_index=i, interested=intr, score=score, reason=f"reason-{i}")
            for i, intr, score in verdicts
        ]
    )


def _summary(*takeaways: tuple[int, str]) -> V2exSummaryResult:
    return V2exSummaryResult(posts=[V2exPostSummary(post_index=i, takeaway=t) for i, t in takeaways])


# --- fixtures + helpers ------------------------------------------------------


@pytest.fixture
async def db(tmp_state_home: str):
    await init_db(tmp_state_home)
    yield tmp_state_home
    await close_db()


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


def _patch_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("progress.integrations.v2ex.tracker.V2EX_REQUEST_MIN_DELAY", 0.0)
    monkeypatch.setattr("progress.integrations.v2ex.tracker.V2EX_REQUEST_MAX_DELAY", 0.0)


def _patch_ai(
    monkeypatch: pytest.MonkeyPatch,
    *,
    classify: V2exClassificationResult | None = None,
    summarize: V2exSummaryResult | None = None,
    classify_error: Exception | None = None,
    summarize_error: Exception | None = None,
) -> dict[str, int]:
    state: dict[str, int] = {"n": 0}
    monkeypatch.setattr("progress.integrations.v2ex.tracker.build_model_string", lambda _cfg: "stub:model")

    async def _run(_agent, _prompt, **_kw):
        state["n"] += 1
        if state["n"] == 1:
            if classify_error is not None:
                raise classify_error
            return classify
        if summarize_error is not None:
            raise summarize_error
        return summarize

    monkeypatch.setattr("progress.integrations.v2ex.tracker.run_extraction", _run)
    return state


async def _make(
    db: str,
    session: aiohttp.ClientSession,
    *,
    plugin_cfg: V2exIntegrationConfig | None = None,
) -> V2exIntegration:
    cfg = CoreConfig(state_home=db)
    if plugin_cfg is not None:
        await set_config("v2ex", plugin_cfg.model_dump(mode="json"))
    integration = V2exIntegration()
    await integration.setup(Components(cfg=cfg, session=session))
    return integration


def _configured(httpserver, *, base_url: str | None = None, **kw) -> V2exIntegrationConfig:
    return V2exIntegrationConfig(
        base_url=base_url or httpserver.url_for("").rstrip("/"),
        interest_profile="rust remote backend",
        tabs=kw.pop("tabs", ["jobs"]),
        max_summaries=kw.pop("max_summaries", 8),
    )


# --- setup / disable ---------------------------------------------------------


class TestSetup:
    async def test_disabled_when_profile_empty(
        self, db: str, session: aiohttp.ClientSession, monkeypatch, httpserver
    ) -> None:
        monkeypatch.setattr("progress.integrations.v2ex.tracker.build_model_string", lambda _cfg: "stub:model")
        integration = await _make(db, session, plugin_cfg=V2exIntegrationConfig(interest_profile=""))
        assert integration._client is None

    async def test_disabled_when_ai_unconfigured(
        self, db: str, session: aiohttp.ClientSession, monkeypatch, httpserver
    ) -> None:
        monkeypatch.setattr("progress.integrations.v2ex.tracker.build_model_string", lambda _cfg: None)
        integration = await _make(db, session, plugin_cfg=_configured(httpserver))
        assert integration._client is None

    async def test_disabled_when_no_session(self, db: str, monkeypatch, httpserver) -> None:
        monkeypatch.setattr("progress.integrations.v2ex.tracker.build_model_string", lambda _cfg: "stub:model")
        integration = V2exIntegration()
        await set_config("v2ex", _configured(httpserver).model_dump(mode="json"))
        await integration.setup(Components(cfg=CoreConfig(state_home=db), session=None))
        assert integration._client is None


class TestRunDegrade:
    async def test_client_none_returns_empty(
        self, db: str, session: aiohttp.ClientSession, monkeypatch, httpserver
    ) -> None:
        monkeypatch.setattr("progress.integrations.v2ex.tracker.build_model_string", lambda _cfg: "stub:model")
        integration = await _make(db, session, plugin_cfg=V2exIntegrationConfig(interest_profile=""))
        result = await integration.run()
        assert result.name == "v2ex"
        assert result.reports == []
        assert result.status == "success"


# --- sync --------------------------------------------------------------------


class TestSync:
    async def test_creates_rows_for_configured_tabs(
        self, db: str, session: aiohttp.ClientSession, monkeypatch, httpserver
    ) -> None:
        monkeypatch.setattr("progress.integrations.v2ex.tracker.build_model_string", lambda _cfg: "stub:model")
        integration = await _make(db, session, plugin_cfg=_configured(httpserver, tabs=["jobs", "creative"]))
        result = await integration.sync()
        assert result.created == 2
        sources = {t.source async for t in V2exTracker.all()}
        assert sources == {"tab:jobs", "tab:creative"}

    async def test_removes_rows_for_dropped_tabs(
        self, db: str, session: aiohttp.ClientSession, monkeypatch, httpserver
    ) -> None:
        monkeypatch.setattr("progress.integrations.v2ex.tracker.build_model_string", lambda _cfg: "stub:model")
        integration = await _make(db, session, plugin_cfg=_configured(httpserver, tabs=["jobs", "creative"]))
        await integration.sync()
        integration._plugin_cfg = _configured(httpserver, tabs=["creative"])
        result = await integration.sync()
        assert result.deleted == 1
        sources = {t.source async for t in V2exTracker.all()}
        assert sources == {"tab:creative"}


# --- run happy path ----------------------------------------------------------


class TestRunHappyPath:
    async def test_full_pipeline_selects_top_k_advances_water_mark(
        self,
        db: str,
        session: aiohttp.ClientSession,
        monkeypatch,
        httpserver,
    ) -> None:
        _patch_jitter(monkeypatch)
        _patch_ai(
            monkeypatch,
            classify=_classification((0, True, 9), (1, True, 8), (2, True, 7)),
            summarize=_summary((0, "takeaway-0"), (1, "takeaway-1")),
        )
        httpserver.expect_request("/").respond_with_data(
            _tab_html(_cell(100, "Rust backend"), _cell(101, "Go backend"), _cell(102, "Java backend"))
        )
        httpserver.expect_request("/t/100").respond_with_data(_topic_html("rust body"))
        httpserver.expect_request("/t/101").respond_with_data(_topic_html("go body"))

        integration = await _make(db, session, plugin_cfg=_configured(httpserver, max_summaries=2))
        result = await integration.run()

        assert result.status == "success"
        assert len(result.reports) == 1
        section = result.reports[0]
        assert section.payload["tab_title"] == "酷工作"
        assert section.payload["tab_url"].endswith("/?tab=jobs")
        posts = section.payload["posts"]
        assert [p["title"] for p in posts] == ["Rust backend", "Go backend"]  # score desc
        assert posts[0]["score"] == 9 and posts[1]["score"] == 8
        assert posts[0]["takeaway"] == "takeaway-0"
        assert posts[0]["reason"] == "reason-0"
        # water mark advanced to max of ALL new topics (102), not just winners
        tracker = await V2exTracker.get(source="tab:jobs")
        assert tracker.last_topic_id == 102
        assert tracker.last_check_time is not None

    async def test_classify_is_sharded_into_batches_and_merged(
        self,
        db: str,
        session: aiohttp.ClientSession,
        monkeypatch,
        httpserver,
    ) -> None:
        # Force tiny batches so a 5-topic input shards into multiple classify calls.
        monkeypatch.setattr("progress.integrations.v2ex.tracker.V2EX_CLASSIFY_BATCH_SIZE", 2)
        _patch_jitter(monkeypatch)
        calls = {"classify": 0, "summarize": 0}

        async def _run(_agent, prompt, **_kw):
            # "Title: topic <n>" carries a globally-unique score (10 - n) so the
            # cross-shard top-K is deterministic regardless of shard boundaries.
            if "interest profile" in prompt:
                calls["classify"] += 1
                pairs = re.findall(r"Index: (\d+)\n\s+Title: topic (\d+)", prompt)
                return V2exClassificationResult(
                    posts=[
                        V2exPostClassification(
                            post_index=int(idx), interested=True, score=10 - int(num), reason=f"r{num}"
                        )
                        for idx, num in pairs
                    ]
                )
            calls["summarize"] += 1
            size = prompt.count("Index:")
            return V2exSummaryResult(posts=[V2exPostSummary(post_index=i, takeaway=f"t{i}") for i in range(size)])

        monkeypatch.setattr("progress.integrations.v2ex.tracker.build_model_string", lambda _cfg: "stub:model")
        monkeypatch.setattr("progress.integrations.v2ex.tracker.run_extraction", _run)

        cells = [_cell(100 + i, f"topic {i}") for i in range(5)]
        httpserver.expect_request("/").respond_with_data(_tab_html(*cells))
        for i in range(5):
            httpserver.expect_request(f"/t/{100 + i}").respond_with_data(_topic_html(f"body {i}"))

        integration = await _make(db, session, plugin_cfg=_configured(httpserver, max_summaries=3))
        result = await integration.run()

        # 5 topics / batch=2 → 3 classify shards; 3 winners → 1 summarize call.
        assert calls == {"classify": 3, "summarize": 1}
        assert result.status == "success"
        # water mark covers ALL classified topics across every shard, not just winners.
        assert (await V2exTracker.get(source="tab:jobs")).last_topic_id == 104
        # global top-K across shards picked the 3 highest-scoring topics.
        posts = result.reports[0].payload["posts"]
        assert [p["title"] for p in posts] == ["topic 0", "topic 1", "topic 2"]

    async def test_non_topk_interested_post_not_fetched_nor_reported(
        self,
        db: str,
        session: aiohttp.ClientSession,
        monkeypatch,
        httpserver,
    ) -> None:
        _patch_jitter(monkeypatch)
        _patch_ai(
            monkeypatch,
            classify=_classification((0, True, 9), (1, True, 8), (2, True, 7)),
            summarize=_summary((0, "t0")),
        )
        httpserver.expect_request("/").respond_with_data(_tab_html(_cell(100, "A"), _cell(101, "B"), _cell(102, "C")))
        httpserver.expect_request("/t/100").respond_with_data(_topic_html("a body"))
        # /t/101 and /t/102 NOT registered → would 404 if fetched

        integration = await _make(db, session, plugin_cfg=_configured(httpserver, max_summaries=1))
        result = await integration.run()

        assert result.status == "success"
        assert len(result.reports[0].payload["posts"]) == 1
        assert result.reports[0].payload["posts"][0]["title"] == "A"
        # water mark still covers all new topics
        assert (await V2exTracker.get(source="tab:jobs")).last_topic_id == 102

    async def test_first_run_no_water_mark_processes_all(
        self,
        db: str,
        session: aiohttp.ClientSession,
        monkeypatch,
        httpserver,
    ) -> None:
        _patch_jitter(monkeypatch)
        _patch_ai(
            monkeypatch,
            classify=_classification((0, True, 9), (1, False, 0)),
            summarize=_summary((0, "t0")),
        )
        httpserver.expect_request("/").respond_with_data(_tab_html(_cell(50, "X"), _cell(51, "Y")))
        httpserver.expect_request("/t/50").respond_with_data(_topic_html("x body"))

        integration = await _make(db, session, plugin_cfg=_configured(httpserver, max_summaries=3))
        result = await integration.run()

        assert len(result.reports[0].payload["posts"]) == 1
        assert (await V2exTracker.get(source="tab:jobs")).last_topic_id == 51


class TestRunIncremental:
    async def test_water_mark_filters_old_topics(
        self,
        db: str,
        session: aiohttp.ClientSession,
        monkeypatch,
        httpserver,
    ) -> None:
        _patch_jitter(monkeypatch)
        _patch_ai(
            monkeypatch,
            classify=_classification((0, True, 9)),
            summarize=_summary((0, "t0")),
        )
        await V2exTracker.create(source="tab:jobs", last_topic_id=100)
        httpserver.expect_request("/").respond_with_data(_tab_html(_cell(100, "OLD"), _cell(101, "NEW")))
        httpserver.expect_request("/t/101").respond_with_data(_topic_html("new body"))

        integration = await _make(db, session, plugin_cfg=_configured(httpserver))
        result = await integration.run()

        assert result.status == "success"
        assert len(result.reports[0].payload["posts"]) == 1
        assert result.reports[0].payload["posts"][0]["title"] == "NEW"
        assert (await V2exTracker.get(source="tab:jobs")).last_topic_id == 101


class TestRunZeroNew:
    async def test_zero_new_skips_ai_and_stamps_check_time(
        self,
        db: str,
        session: aiohttp.ClientSession,
        monkeypatch,
        httpserver,
    ) -> None:
        _patch_jitter(monkeypatch)
        state = _patch_ai(monkeypatch)  # AI must NOT be called
        await V2exTracker.create(source="tab:jobs", last_topic_id=200)
        httpserver.expect_request("/").respond_with_data(_tab_html(_cell(100, "old"), _cell(150, "older")))

        integration = await _make(db, session, plugin_cfg=_configured(httpserver))
        result = await integration.run()

        assert result.status == "success"
        assert result.reports == []
        assert state["n"] == 0
        tracker = await V2exTracker.get(source="tab:jobs")
        assert tracker.last_topic_id == 200  # unchanged
        assert tracker.last_check_time is not None


# --- AI / body failure -------------------------------------------------------


class TestClassifyFailure:
    async def test_classify_failure_skips_round_and_keeps_water_mark(
        self,
        db: str,
        session: aiohttp.ClientSession,
        monkeypatch,
        httpserver,
    ) -> None:
        _patch_jitter(monkeypatch)
        _patch_ai(monkeypatch, classify_error=ProgressException("ai down"))
        httpserver.expect_request("/").respond_with_data(_tab_html(_cell(100, "A"), _cell(101, "B")))

        integration = await _make(db, session, plugin_cfg=_configured(httpserver))
        result = await integration.run()

        assert result.status == "partial"
        assert result.reports == []
        assert result.errors  # classify failure recorded
        # no V2exTracker row created → water mark not advanced
        assert await V2exTracker.filter(source="tab:jobs").count() == 0


class TestSummarizeFailure:
    async def test_summarize_failure_degrades_takeaway_to_reason(
        self,
        db: str,
        session: aiohttp.ClientSession,
        monkeypatch,
        httpserver,
    ) -> None:
        _patch_jitter(monkeypatch)
        _patch_ai(
            monkeypatch,
            classify=_classification((0, True, 9)),
            summarize_error=ProgressException("ai down"),
        )
        httpserver.expect_request("/").respond_with_data(_tab_html(_cell(100, "A")))
        httpserver.expect_request("/t/100").respond_with_data(_topic_html("body"))

        integration = await _make(db, session, plugin_cfg=_configured(httpserver))
        result = await integration.run()

        assert len(result.reports) == 1
        post = result.reports[0].payload["posts"][0]
        assert post["takeaway"] == post["reason"] == "reason-0"
        # water mark still advanced (classify succeeded)
        assert (await V2exTracker.get(source="tab:jobs")).last_topic_id == 100


class TestBodyFetchFailure:
    async def test_body_failure_post_keeps_report_with_degraded_takeaway(
        self,
        db: str,
        session: aiohttp.ClientSession,
        monkeypatch,
        httpserver,
    ) -> None:
        _patch_jitter(monkeypatch)
        _patch_ai(
            monkeypatch,
            classify=_classification((0, True, 9), (1, True, 8)),
            summarize=_summary((0, "t1")),  # body for 100 failed → summarize batch = [101] only (index 0)
        )
        httpserver.expect_request("/").respond_with_data(_tab_html(_cell(100, "A"), _cell(101, "B")))

        httpserver.expect_request("/t/100").respond_with_handler(lambda req: Response("ban", status=403))
        httpserver.expect_request("/t/101").respond_with_data(_topic_html("b body"))

        integration = await _make(db, session, plugin_cfg=_configured(httpserver, max_summaries=2))
        result = await integration.run()

        assert result.status == "partial"  # one body error
        assert len(result.reports) == 1
        posts = {p["title"]: p for p in result.reports[0].payload["posts"]}
        assert posts["A"]["takeaway"] == "reason-0"  # body failed → degrade to reason
        assert posts["B"]["takeaway"] == "t1"


# --- build_notification ------------------------------------------------------


class TestBuildNotification:
    async def test_no_reports_returns_empty(
        self, db: str, session: aiohttp.ClientSession, monkeypatch, httpserver
    ) -> None:
        monkeypatch.setattr("progress.integrations.v2ex.tracker.build_model_string", lambda _cfg: "stub:model")
        integration = await _make(db, session, plugin_cfg=_configured(httpserver))
        events = await integration.build_notification(result=RunResult(name="v2ex"), reports=[])
        assert events == []

    async def test_aggregated_event_contract(
        self,
        db: str,
        session: aiohttp.ClientSession,
        monkeypatch,
        httpserver,
    ) -> None:
        _patch_jitter(monkeypatch)
        _patch_ai(
            monkeypatch,
            classify=_classification((0, True, 9), (1, True, 8)),
            summarize=_summary((0, "t0"), (1, "t1")),
        )
        httpserver.expect_request("/").respond_with_data(_tab_html(_cell(100, "A"), _cell(101, "B")))
        httpserver.expect_request("/t/100").respond_with_data(_topic_html("a"))
        httpserver.expect_request("/t/101").respond_with_data(_topic_html("b"))

        integration = await _make(db, session, plugin_cfg=_configured(httpserver, max_summaries=2))
        run_result = await integration.run()
        reports = [
            IntegrationReport(
                integration_name="v2ex",
                report_type="v2ex",
                report_id=1,
                title="V2EX Digest",
                summary="two picks",
                markpost_url="https://mp/1",
                total_batches=1,
            )
        ]
        events = await integration.build_notification(result=run_result, reports=reports)

        assert len(events) == 1
        event = events[0]
        assert event.kind == "v2ex"
        assert event.title == "V2EX Digest"
        assert event.summary == "two picks"
        assert event.markpost_url == "https://mp/1"
        assert event.data["selected_count"] == 2
        tab = event.data["tabs"][0]
        assert tab["tab_title"] == "酷工作"
        assert tab["count"] == 2
        top = event.data["top_posts"]
        assert len(top) == 2
        # high-density one-liner contract: bare titles (score/replies stay
        # internal), no takeaway/reason (they stay in the report); payload
        # order equals the report's section order (score, then replies).
        assert set(top[0]) == {"title", "url"}
        assert [p["title"] for p in top] == ["A", "B"]


# --- pipeline touchpoints ----------------------------------------------------


class TestPipelineCommitCount:
    def test_commit_count_for_v2ex_sums_posts(self) -> None:
        sections = [
            ReportSection(title="jobs", payload={"posts": [{"t": 1}, {"t": 2}, {"t": 3}]}),
            ReportSection(title="creative", payload={"posts": [{"t": 4}, {"t": 5}]}),
        ]
        assert _commit_count_for("v2ex", "v2ex", sections) == 5

    def test_report_type_map_has_v2ex(self) -> None:
        assert _report_type_for("v2ex") == "v2ex"
