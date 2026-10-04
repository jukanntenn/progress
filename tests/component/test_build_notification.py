"""Component tests for integration ``build_notification`` hooks (spec 06/10).

These tests verify the per-integration notification aggregation contract:
each integration authors its own aggregated :class:`NotificationEvent`(s) from
its ``RunResult`` plus the pipeline's :class:`IntegrationReport` list, and the
resulting count matches the business rule (one per report type — repo emits up
to two, the others exactly one). This is the core guarantee that prevents the
notification-count explosion regression.
"""

from __future__ import annotations

import pytest

from progress.cli.notifications.events import NotificationEvent
from progress.cli.reports.pipeline import IntegrationReport
from progress.integrations.base import ReportSection, RunResult
from progress.integrations.changelog.tracker import ChangelogIntegration, version_level
from progress.integrations.feed.tracker import FeedIntegration
from progress.integrations.proposal.tracker import ProposalIntegration
from progress.integrations.repo.tracker import RepoIntegration


def _report(*, integration: str, report_type: str, **kwargs) -> IntegrationReport:
    return IntegrationReport(
        integration_name=integration,
        report_type=report_type,
        report_id=1,
        title=kwargs.get("title", "T"),
        summary=kwargs.get("summary", "S"),
        markpost_url=kwargs.get("markpost_url", "https://markpost.example/r/1"),
        total_batches=kwargs.get("total_batches", 1),
    )


class TestProposalBuildNotification:
    async def test_one_notification_aggregating_all_kinds(self) -> None:
        integration = ProposalIntegration()
        result = RunResult(name="proposal")
        result.reports = [
            ReportSection(
                title="EIP",
                payload={
                    "kind": "eip",
                    "tracker_url": "https://github.com/ethereum/EIPs",
                    "reports": [
                        {
                            "file_path": "EIPS/eip-1.md",
                            "number": 1,
                            "title": "T1",
                            "old_status": "",
                            "new_status": "Draft",
                            "file_url": "https://eips/1",
                        },
                        {
                            "file_path": "EIPS/eip-2.md",
                            "number": 2,
                            "title": "T2",
                            "old_status": "Draft",
                            "new_status": "Review",
                            "file_url": "https://eips/2",
                        },
                    ],
                },
            ),
            ReportSection(
                title="ERC",
                payload={
                    "kind": "erc",
                    "tracker_url": "https://github.com/ethereum/ercs",
                    "reports": [
                        {
                            "file_path": "ERCS/erc-8.md",
                            "number": 8,
                            "title": "T8",
                            "old_status": "",
                            "new_status": "Idea",
                            "file_url": "https://eips/8",
                        }
                    ],
                },
            ),
        ]
        reports = [_report(integration="proposal", report_type="proposal")]

        events = await integration.build_notification(result=result, reports=reports)

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, NotificationEvent)
        assert event.kind == "proposal"
        assert event.markpost_url == "https://markpost.example/r/1"
        assert event.data["filenames"] == ["eip-1.md", "eip-2.md", "erc-8.md"]
        assert event.data["total"] == 3
        assert event.data["more_count"] == 0
        proposals = event.data["proposals"]
        assert len(proposals) == 3
        assert proposals[0] == {
            "kind": "EIP",
            "number": "1",
            "title": "T1",
            "old_status": "",
            "new_status": "Draft",
            "file_url": "https://eips/1",
            "file_name": "eip-1.md",
        }
        assert proposals[1]["old_status"] == "Draft"
        assert proposals[1]["new_status"] == "Review"

    async def test_more_count_when_over_five_files(self) -> None:
        integration = ProposalIntegration()
        result = RunResult(name="proposal")
        result.reports = [
            ReportSection(
                title="EIP",
                payload={
                    "kind": "eip",
                    "reports": [{"file_path": f"EIPS/eip-{i}.md"} for i in range(7)],
                },
            )
        ]
        events = await integration.build_notification(
            result=result,
            reports=[_report(integration="proposal", report_type="proposal")],
        )
        assert len(events) == 1
        assert len(events[0].data["filenames"]) == 5
        assert events[0].data["more_count"] == 2

    async def test_no_notification_when_no_reports(self) -> None:
        integration = ProposalIntegration()
        events = await integration.build_notification(result=RunResult(name="proposal"), reports=[])
        assert events == []


class TestChangelogBuildNotification:
    async def test_one_notification_aggregating_all_trackers(self) -> None:
        integration = ChangelogIntegration()
        result = RunResult(name="changelog")
        result.reports = [
            ReportSection(
                title="uTools",
                payload={
                    "name": "uTools",
                    "url": "https://u.tools",
                    "new_entries": [{"version": "6.2.0", "description": "x"}],
                },
            ),
            ReportSection(
                title="Claude Code",
                payload={
                    "name": "Claude Code",
                    "url": "https://claude.com",
                    "new_entries": [{"version": "2.1.0", "description": "y"}],
                },
            ),
        ]
        events = await integration.build_notification(
            result=result,
            reports=[_report(integration="changelog", report_type="changelog")],
        )
        assert len(events) == 1
        event = events[0]
        assert event.kind == "changelog"
        entries = event.data["entries"]
        assert len(entries) == 2
        assert entries[0] == {"name": "uTools", "version": "6.2.0", "url": "https://u.tools", "level": "MINOR"}
        assert entries[1] == {"name": "Claude Code", "version": "2.1.0", "url": "https://claude.com", "level": "MINOR"}

    async def test_no_notification_when_no_reports(self) -> None:
        integration = ChangelogIntegration()
        events = await integration.build_notification(result=RunResult(name="changelog"), reports=[])
        assert events == []


class TestRepoBuildNotification:
    async def test_two_notifications_for_update_and_discovery(self) -> None:
        integration = RepoIntegration()
        result = RunResult(name="repo")
        result.reports = [
            ReportSection(
                title="django/django",
                payload={
                    "repo_name": "django/django",
                    "repo_web_url": "https://github.com/django/django",
                    "commit_count": 5,
                    "report_type": "repo_update",
                },
            ),
            ReportSection(
                title="Discovered repos under alice",
                payload={
                    "report_type": "repo_new",
                    "owner": "alice",
                    "new_repos": [
                        {"name": "alice/new1", "url": "https://github.com/alice/new1"},
                        {"name": "alice/new2", "url": "https://github.com/alice/new2"},
                    ],
                },
            ),
        ]
        reports = [
            _report(integration="repo", report_type="repo_update"),
            _report(integration="repo", report_type="repo_new"),
        ]
        events = await integration.build_notification(result=result, reports=reports)

        assert len(events) == 2
        kinds = {e.kind for e in events}
        assert kinds == {"repo_update", "discovered_repo"}

        update = next(e for e in events if e.kind == "repo_update")
        assert update.data["total_commits"] == 5
        assert update.data["total_repos"] == 1
        assert update.data["repo_urls"] == {"django/django": "https://github.com/django/django"}

        discovery = next(e for e in events if e.kind == "discovered_repo")
        assert len(discovery.data["repos"]) == 2

    async def test_only_update_when_no_discovery(self) -> None:
        integration = RepoIntegration()
        result = RunResult(name="repo")
        result.reports = [
            ReportSection(
                title="django/django",
                payload={"repo_name": "django/django", "commit_count": 3, "report_type": "repo_update"},
            )
        ]
        events = await integration.build_notification(
            result=result,
            reports=[_report(integration="repo", report_type="repo_update")],
        )
        assert len(events) == 1
        assert events[0].kind == "repo_update"

    async def test_repos_with_updates_counts_commit_or_release(self) -> None:
        # repos_with_updates = repos with commit_count>0 OR a non-empty releases
        # list. A repo with neither (success but no new data) is not counted.
        integration = RepoIntegration()
        result = RunResult(name="repo")
        result.reports = [
            ReportSection(
                title="a/with-commits",
                payload={
                    "repo_name": "a/with-commits",
                    "commit_count": 5,
                    "releases": [],
                    "report_type": "repo_update",
                    "status": "success",
                },
            ),
            ReportSection(
                title="b/with-release",
                payload={
                    "repo_name": "b/with-release",
                    "commit_count": 0,
                    "releases": [{"tag": "v2"}],
                    "report_type": "repo_update",
                    "status": "success",
                },
            ),
            ReportSection(
                title="c/nothing-new",
                payload={
                    "repo_name": "c/nothing-new",
                    "commit_count": 0,
                    "releases": [],
                    "report_type": "repo_update",
                    "status": "success",
                },
            ),
        ]
        events = await integration.build_notification(
            result=result,
            reports=[_report(integration="repo", report_type="repo_update")],
        )
        update = next(e for e in events if e.kind == "repo_update")
        assert update.data["repos_with_updates"] == 2

    async def test_no_notification_when_no_reports(self) -> None:
        integration = RepoIntegration()
        events = await integration.build_notification(result=RunResult(name="repo"), reports=[])
        assert events == []


class TestFeedBuildNotification:
    async def test_one_notification_aggregating_feeds_with_site_url(self) -> None:
        integration = FeedIntegration()
        result = RunResult(name="feed")
        result.reports = [
            ReportSection(
                title="Hacker News",
                payload={
                    "feed_title": "Hacker News",
                    "site_url": "https://news.ycombinator.com",
                    "entries": [{"id": 1}, {"id": 2}],
                },
            ),
            ReportSection(
                title="Lobsters",
                payload={"feed_title": "Lobsters", "site_url": "https://lobste.rs", "entries": [{"id": 3}]},
            ),
        ]
        events = await integration.build_notification(
            result=result,
            reports=[_report(integration="feed", report_type="feed")],
        )
        assert len(events) == 1
        event = events[0]
        assert event.kind == "feed"
        feeds = event.data["feeds"]
        assert len(feeds) == 2
        assert feeds[0] == {"title": "Hacker News", "entry_count": 2, "url": "https://news.ycombinator.com"}
        assert feeds[1] == {"title": "Lobsters", "entry_count": 1, "url": "https://lobste.rs"}

    async def test_no_notification_when_no_reports(self) -> None:
        integration = FeedIntegration()
        events = await integration.build_notification(result=RunResult(name="feed"), reports=[])
        assert events == []


class TestVersionLevel:
    """``version_level`` classifies a semver-ish string into MAJOR/MINOR/PATCH."""

    @pytest.mark.parametrize(
        "version, expected",
        [
            ("1.0.0", "MAJOR"),
            ("0.1.0", "MINOR"),
            ("0.0.1", "PATCH"),
            ("1.2.0", "MINOR"),
            ("1.2.3", "PATCH"),
            ("v2.0.0", "MAJOR"),
            ("V3.1.0", "MINOR"),
            ("10.20.30", "PATCH"),
        ],
    )
    def test_semver_strings(self, version: str, expected: str) -> None:
        assert version_level(version) == expected

    @pytest.mark.parametrize(
        "version",
        ["", "latest", "2024-01-01", "v1.2", "1", "build-42"],
    )
    def test_non_semver_returns_empty(self, version: str) -> None:
        # Non X.Y.Z schemes return "" so the badge is omitted, not guessed.
        assert version_level(version) == ""
