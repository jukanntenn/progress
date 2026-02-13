from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from ...config import ChangelogTrackerConfig, Config
from .models import ChangelogTracker
from ...errors import ChangelogParseError
from ...utils import get_now
from .changelog_parsers import (
    HTMLChineseVersionParser,
    MarkdownHeadingParser,
    VersionEntry,
)

logger = logging.getLogger(__name__)


ChangelogStatus = Literal[
    "success",
    "failed",
    "no_new_version",
    "skipped",
]


@dataclass(frozen=True)
class ChangelogCheckResult:
    name: str
    url: str
    parser_type: str
    status: ChangelogStatus
    latest_version: str | None = None
    new_entries: list[VersionEntry] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class ChangelogCheckAllResult:
    results: list[ChangelogCheckResult]

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts


class ChangelogTrackerManager:
    def __init__(self, cfg: Config):
        self._cfg = cfg

    @classmethod
    def from_config(cls, cfg: Config) -> "ChangelogTrackerManager":
        return cls(cfg=cfg)

    def sync(self, trackers: list[ChangelogTrackerConfig]) -> dict[str, int]:
        desired_urls = {str(t.url) for t in trackers}
        existing = list(ChangelogTracker.select())

        created = 0
        updated = 0
        deleted = 0

        for t in trackers:
            url = str(t.url)
            tracker = (
                ChangelogTracker.select().where(ChangelogTracker.url == url).first()
            )
            if tracker is None:
                ChangelogTracker.create(
                    name=t.name,
                    url=url,
                    parser_type=t.parser_type,
                    enabled=t.enabled,
                    last_seen_version=None,
                    last_check_time=None,
                )
                created += 1
                continue

            changed = False
            if tracker.name != t.name:
                tracker.name = t.name
                changed = True
            if tracker.parser_type != t.parser_type:
                tracker.parser_type = t.parser_type
                changed = True
            if tracker.enabled != t.enabled:
                tracker.enabled = t.enabled
                changed = True
            if changed:
                tracker.save()
                updated += 1

        for tr in existing:
            if tr.url not in desired_urls:
                tr.delete_instance()
                deleted += 1

        return {
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "total": len(trackers),
        }

    def check(self, tracker: ChangelogTracker) -> ChangelogCheckResult:
        if not tracker.enabled:
            return ChangelogCheckResult(
                name=tracker.name,
                url=tracker.url,
                parser_type=tracker.parser_type,
                status="skipped",
            )

        now = get_now(self._cfg.get_timezone())
        try:
            parser = self._build_parser(tracker.parser_type)
            content = parser.fetch(tracker.url)
            entries = parser.parse(content)
            if not entries:
                raise ChangelogParseError("No version entries found")

            latest_version = entries[0].version
            new_entries, warning = self._detect_new_entries(
                entries, last_seen_version=tracker.last_seen_version
            )

            if not new_entries:
                tracker.last_check_time = now
                tracker.save()
                return ChangelogCheckResult(
                    name=tracker.name,
                    url=tracker.url,
                    parser_type=tracker.parser_type,
                    status="no_new_version",
                    latest_version=latest_version,
                )

            tracker.last_seen_version = new_entries[0].version
            tracker.last_check_time = now
            tracker.save()
            return ChangelogCheckResult(
                name=tracker.name,
                url=tracker.url,
                parser_type=tracker.parser_type,
                status="success",
                latest_version=latest_version,
                new_entries=new_entries,
                error=warning,
            )
        except Exception as e:
            logger.warning(f"Changelog check failed for {tracker.name}: {e}")
            tracker.last_check_time = now
            tracker.save()
            return ChangelogCheckResult(
                name=tracker.name,
                url=tracker.url,
                parser_type=tracker.parser_type,
                status="failed",
                error=str(e),
            )

    def check_all(self) -> ChangelogCheckAllResult:
        results: list[ChangelogCheckResult] = []

        for cfg_tracker in self._cfg.changelog_trackers:
            tracker = (
                ChangelogTracker.select()
                .where(ChangelogTracker.url == str(cfg_tracker.url))
                .first()
            )
            if tracker is None:
                results.append(
                    ChangelogCheckResult(
                        name=cfg_tracker.name,
                        url=str(cfg_tracker.url),
                        parser_type=str(cfg_tracker.parser_type),
                        status="failed",
                        error="Tracker missing from database; run sync() first",
                    )
                )
                continue

            results.append(self.check(tracker))

        return ChangelogCheckAllResult(results=results)

    @staticmethod
    def _build_parser(parser_type: str):
        if parser_type == "markdown_heading":
            return MarkdownHeadingParser()
        if parser_type == "html_chinese_version":
            return HTMLChineseVersionParser()
        raise ValueError(f"Unknown parser_type: {parser_type}")

    @staticmethod
    def _detect_new_entries(
        entries: list[VersionEntry],
        last_seen_version: str | None,
    ) -> tuple[list[VersionEntry], str | None]:
        if not entries:
            return [], None

        if last_seen_version is None:
            return [entries[0]], None

        for idx, entry in enumerate(entries):
            if entry.version == last_seen_version:
                return entries[:idx], None

        return (
            [entries[0]],
            "Stored last_seen_version was not found in changelog; notified latest only",
        )
