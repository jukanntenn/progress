import fnmatch
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ...ai.analyzers.claude_code import ClaudeCodeAnalyzer
from ...config import Config, ProposalTrackerConfig
from .models import EIP, PEP, DjangoDEP, ProposalEvent, ProposalTracker, RustRFC
from ...enums import ProposalEventType
from ...errors import AnalysisException, GitException, ProposalParseError
from ...github import GitClient, sanitize_repo_name
from ...utils import get_now, run_command

logger = logging.getLogger(__name__)

TRACKER_REPO_URLS = {
    "rust_rfc": "https://github.com/rust-lang/rfcs",
    "eip": "https://github.com/ethereum/EIPs",
    "pep": "https://github.com/python/peps",
    "django_dep": "https://github.com/django/deps",
}


@dataclass(frozen=True)
class ProposalEventReport:
    tracker_type: str
    proposal_number: int
    title: str
    event_type: str
    old_status: str | None
    new_status: str | None
    commit_hash: str
    detected_at: datetime
    analysis_summary: str | None
    analysis_detail: str | None
    file_path: str
    file_url: str


@dataclass(frozen=True)
class ProposalCheckAllResult:
    events: list[ProposalEventReport]
    tracker_statuses: dict[str, str]

    def get_status_count(self) -> tuple[int, int, int]:
        success = sum(1 for s in self.tracker_statuses.values() if s == "success")
        failed = sum(1 for s in self.tracker_statuses.values() if s == "failed")
        skipped = sum(1 for s in self.tracker_statuses.values() if s == "skipped")
        return success, failed, skipped


@dataclass(frozen=True)
class InitialCheckResult:
    reports: list[ProposalEventReport]
    matched_files: int
    parsed_files: int


class ProposalTrackerManager:
    def __init__(self, analyzer: ClaudeCodeAnalyzer, cfg: Config):
        self.analyzer = analyzer
        self.cfg = cfg
        self.git = GitClient(timeout=cfg.github.git_timeout)

    def sync(self, trackers: list[ProposalTrackerConfig]) -> dict:
        desired: set[tuple[str, str, str, str, str]] = set()
        for t in trackers:
            desired.add(
                (
                    t.type,
                    t.repo_url,
                    t.branch,
                    t.proposal_dir,
                    t.file_pattern,
                )
            )

        existing = list(ProposalTracker.select())

        created = 0
        updated = 0
        deleted = 0

        for t in trackers:
            key = (t.type, t.repo_url, t.branch, t.proposal_dir, t.file_pattern)
            tracker = (
                ProposalTracker.select()
                .where(
                    (ProposalTracker.tracker_type == t.type)
                    & (ProposalTracker.repo_url == t.repo_url)
                    & (ProposalTracker.branch == t.branch)
                    & (ProposalTracker.proposal_dir == t.proposal_dir)
                    & (ProposalTracker.file_pattern == t.file_pattern)
                )
                .first()
            )
            if tracker is None:
                ProposalTracker.create(
                    tracker_type=t.type,
                    repo_url=t.repo_url,
                    branch=t.branch,
                    enabled=t.enabled,
                    proposal_dir=t.proposal_dir,
                    file_pattern=t.file_pattern,
                )
                created += 1
            else:
                if tracker.enabled != t.enabled:
                    tracker.enabled = t.enabled
                    tracker.save()
                    updated += 1

        for tr in existing:
            key = (
                tr.tracker_type,
                tr.repo_url,
                tr.branch,
                tr.proposal_dir,
                tr.file_pattern,
            )
            if key not in desired:
                tr.delete_instance()
                deleted += 1

        return {
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "total": len(trackers),
        }

    def list_enabled(self) -> list[ProposalTracker]:
        return list(ProposalTracker.select().where(ProposalTracker.enabled))

    def check_all(
        self,
        trackers: list[ProposalTracker],
        concurrency: int = 1,
    ) -> ProposalCheckAllResult:
        tracker_statuses: dict[str, str] = {}
        events: list[ProposalEventReport] = []

        if not trackers:
            return ProposalCheckAllResult(events=[], tracker_statuses={})

        if concurrency <= 1:
            for t in trackers:
                t_key = self._tracker_key(t)
                try:
                    ev = self.check(t)
                    tracker_statuses[t_key] = "success"
                    events.extend(ev)
                except Exception as e:
                    logger.warning(f"Proposal tracker check failed for {t_key}: {e}")
                    tracker_statuses[t_key] = "failed"
            return ProposalCheckAllResult(
                events=events, tracker_statuses=tracker_statuses
            )

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(self.check, t): t for t in trackers}
            for future in as_completed(futures):
                t = futures[future]
                t_key = self._tracker_key(t)
                try:
                    ev = future.result()
                    tracker_statuses[t_key] = "success"
                    events.extend(ev)
                except Exception as e:
                    logger.warning(f"Proposal tracker check failed for {t_key}: {e}")
                    tracker_statuses[t_key] = "failed"

        return ProposalCheckAllResult(events=events, tracker_statuses=tracker_statuses)

    def check(self, tracker: ProposalTracker) -> list[ProposalEventReport]:
        if not tracker.enabled:
            return []

        repo_path = self._clone_or_update(tracker)
        current_commit = self.git.get_current_commit(repo_path)
        old_commit = tracker.last_seen_commit

        from .proposal_parsers import (
            DjangoDEPParser,
            EIPParser,
            PEPParser,
            RustRFCParser,
        )

        parser = {
            "eip": EIPParser(),
            "rust_rfc": RustRFCParser(),
            "pep": PEPParser(),
            "django_dep": DjangoDEPParser(),
        }.get(tracker.tracker_type)
        if parser is None:
            raise ValueError(f"Unknown tracker type: {tracker.tracker_type}")

        if not old_commit:
            result = self._handle_initial_check(
                tracker, parser, repo_path, current_commit
            )
            tracker.last_check_time = get_now(self.cfg.get_timezone())
            if result.parsed_files > 0:
                tracker.last_seen_commit = current_commit
            tracker.save()
            return result.reports

        if old_commit == current_commit:
            tracker.last_check_time = get_now(self.cfg.get_timezone())
            tracker.save()
            return []

        changes = self.git.get_changed_file_statuses(
            repo_path, old_commit, current_commit
        )
        proposal_files = self._filter_proposal_files(tracker, changes)
        reports: list[ProposalEventReport] = []

        for status, rel_path in proposal_files:
            reports.extend(
                self._process_proposal_file(
                    tracker,
                    parser,
                    repo_path,
                    rel_path,
                    status,
                    old_commit,
                    current_commit,
                )
            )

        tracker.last_seen_commit = current_commit
        tracker.last_check_time = get_now(self.cfg.get_timezone())
        tracker.save()

        return reports

    def _clone_or_update(self, tracker: ProposalTracker) -> Path:
        repo_name = sanitize_repo_name(self._tracker_repo_slug(tracker.repo_url))
        local_dir = self.git.workspace_dir / "proposal_repos" / repo_name
        local_dir.parent.mkdir(parents=True, exist_ok=True)

        if local_dir.exists() and (local_dir / ".git").exists():
            try:
                self.git.fetch_and_reset(local_dir, tracker.branch)
                return local_dir
            except Exception as e:
                raise GitException(str(e)) from e

        try:
            if local_dir.exists():
                shutil.rmtree(local_dir, ignore_errors=True)

            run_command(
                [
                    "git",
                    "clone",
                    "--single-branch",
                    "--branch",
                    tracker.branch,
                    tracker.repo_url,
                    str(local_dir),
                ],
                timeout=self.cfg.github.git_timeout,
                check=True,
            )
            return local_dir
        except Exception as e:
            raise GitException(str(e)) from e

    def _filter_proposal_files(
        self,
        tracker: ProposalTracker,
        changes: list[tuple[str, str]],
    ) -> list[tuple[str, str]]:
        filtered: list[tuple[str, str]] = []

        for status, path in changes:
            if tracker.proposal_dir:
                norm_dir = tracker.proposal_dir.strip("/") + "/"
                if not path.startswith(norm_dir):
                    continue

            if tracker.file_pattern:
                name = Path(path).name
                if not fnmatch.fnmatch(name, tracker.file_pattern):
                    continue

            filtered.append((status, path))

        return filtered

    def _process_proposal_file(
        self,
        tracker: ProposalTracker,
        parser,
        repo_path: Path,
        rel_path: str,
        change_status: str,
        old_commit: str,
        new_commit: str,
    ) -> list[ProposalEventReport]:
        abs_path = str(repo_path / rel_path)

        if change_status.startswith("D"):
            return self._handle_deleted_proposal(tracker, rel_path, new_commit)

        try:
            data = parser.parse(abs_path)
        except ProposalParseError as e:
            logger.warning(f"Failed to parse proposal {abs_path}: {e}")
            self._log_event(
                tracker,
                None,
                ProposalEventType.CONTENT_MODIFIED.value,
                None,
                None,
                new_commit,
                {"error": str(e), "file_path": rel_path},
            )
            return []

        old_model = self._get_existing_proposal_model(tracker.tracker_type, data.number)
        events = self._detect_proposal_events(tracker.tracker_type, old_model, data)
        reports: list[ProposalEventReport] = []
        file_url = self._build_file_url(tracker, new_commit, rel_path)

        for e in events:
            if e.event_type == ProposalEventType.CONTENT_MODIFIED.value:
                diff_text = self.git.get_file_diff(
                    repo_path, old_commit, new_commit, rel_path
                )
                sections = self._extract_changed_sections(diff_text)
                e.metadata["changed_sections"] = sections
                e.metadata["file_path"] = rel_path
                summary, detail = self._analyze_event(
                    tracker.tracker_type,
                    e.event_type,
                    data.number,
                    data.title,
                    e.old_status,
                    e.new_status,
                    proposal_text=None,
                    diff_text=diff_text,
                )
            else:
                summary, detail = self._analyze_event(
                    tracker.tracker_type,
                    e.event_type,
                    data.number,
                    data.title,
                    e.old_status,
                    e.new_status,
                    proposal_text=data.full_text,
                    diff_text=None,
                )

            proposal_model = self._upsert_proposal_model(
                tracker.tracker_type,
                old_model,
                data,
                commit_hash=new_commit,
                repo_file_path=rel_path,
            )
            if summary and detail:
                proposal_model.analysis_summary = summary
                proposal_model.analysis_detail = detail
                proposal_model.save()

            event_record = self._log_event(
                tracker,
                proposal_model,
                e.event_type,
                e.old_status,
                e.new_status,
                new_commit,
                e.metadata,
            )

            reports.append(
                ProposalEventReport(
                    tracker_type=tracker.tracker_type,
                    proposal_number=data.number,
                    title=data.title,
                    event_type=e.event_type,
                    old_status=e.old_status,
                    new_status=e.new_status,
                    commit_hash=new_commit,
                    detected_at=event_record.detected_at,
                    analysis_summary=proposal_model.analysis_summary,
                    analysis_detail=proposal_model.analysis_detail,
                    file_path=rel_path,
                    file_url=file_url,
                )
            )

        return reports

    def _handle_initial_check(
        self, tracker: ProposalTracker, parser, repo_path: Path, new_commit: str
    ) -> InitialCheckResult:
        tracker_key = self._tracker_key(tracker)
        base = repo_path / tracker.proposal_dir if tracker.proposal_dir else repo_path
        if not base.exists():
            logger.warning(
                f"Initial proposal check skipped ({tracker_key}): proposal_dir not found: {tracker.proposal_dir}"
            )
            return InitialCheckResult(reports=[], matched_files=0, parsed_files=0)

        matches: list[Path] = []
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if tracker.file_pattern and not parser.matches_pattern(
                str(p), tracker.file_pattern
            ):
                continue
            matches.append(p)

        if not matches:
            logger.warning(
                f"Initial proposal check found no matching files ({tracker_key}): dir={tracker.proposal_dir} pattern={tracker.file_pattern}"
            )
            return InitialCheckResult(reports=[], matched_files=0, parsed_files=0)

        utc = ZoneInfo("UTC")
        latest: tuple[datetime | None, Path] | None = None
        parsed_files = 0

        for p in matches:
            rel_path = str(p.relative_to(repo_path))
            try:
                data = parser.parse(str(p))
            except ProposalParseError:
                continue

            parsed_files += 1

            existing = self._get_existing_proposal_model(
                tracker.tracker_type, data.number
            )
            self._upsert_proposal_model(
                tracker.tracker_type,
                existing,
                data,
                commit_hash=new_commit,
                repo_file_path=rel_path,
            )

            created_str = self.git.get_file_creation_date(repo_path, rel_path)
            created_dt = None
            if created_str:
                try:
                    created_dt = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S %z")
                except ValueError:
                    created_dt = None

            if created_dt is not None and created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=utc)

            created_cmp = created_dt or datetime.min.replace(tzinfo=utc)
            latest_cmp = (
                latest[0] if latest and latest[0] else None
            ) or datetime.min.replace(tzinfo=utc)

            if latest is None or (created_cmp > latest_cmp):
                latest = (created_dt, p)

        if not latest:
            logger.warning(
                f"Initial proposal check found no parsable proposals ({tracker_key}): matched={len(matches)} parsed=0"
            )
            return InitialCheckResult(
                reports=[], matched_files=len(matches), parsed_files=0
            )

        latest_rel_path = str(latest[1].relative_to(repo_path))
        try:
            data = parser.parse(str(latest[1]))
        except ProposalParseError:
            logger.warning(
                f"Initial proposal check could not parse selected example ({tracker_key}): {latest_rel_path}"
            )
            return InitialCheckResult(
                reports=[], matched_files=len(matches), parsed_files=parsed_files
            )

        model = self._get_existing_proposal_model(tracker.tracker_type, data.number)
        model = self._upsert_proposal_model(
            tracker.tracker_type,
            model,
            data,
            commit_hash=new_commit,
            repo_file_path=latest_rel_path,
        )

        try:
            summary, detail = self._analyze_event(
                tracker.tracker_type,
                ProposalEventType.CREATED.value,
                data.number,
                data.title,
                None,
                data.status,
                proposal_text=data.full_text,
                diff_text=None,
            )
            if summary and detail:
                model.analysis_summary = summary
                model.analysis_detail = detail
                model.save()
        except Exception as e:
            logger.warning(f"Initial proposal analysis failed: {e}")

        event_record = self._log_event(
            tracker,
            model,
            ProposalEventType.CREATED.value,
            None,
            data.status,
            new_commit,
            {"file_path": latest_rel_path, "initial_check": True},
        )

        file_url = self._build_file_url(tracker, new_commit, latest_rel_path)
        reports = [
            ProposalEventReport(
                tracker_type=tracker.tracker_type,
                proposal_number=data.number,
                title=data.title,
                event_type=ProposalEventType.CREATED.value,
                old_status=None,
                new_status=data.status,
                commit_hash=new_commit,
                detected_at=event_record.detected_at,
                analysis_summary=model.analysis_summary,
                analysis_detail=model.analysis_detail,
                file_path=latest_rel_path,
                file_url=file_url,
            )
        ]

        logger.info(
            f"Initial proposal check completed ({tracker_key}): matched={len(matches)} parsed={parsed_files} example={latest_rel_path}"
        )
        return InitialCheckResult(
            reports=reports,
            matched_files=len(matches),
            parsed_files=parsed_files,
        )

    def _handle_deleted_proposal(
        self, tracker: ProposalTracker, rel_path: str, new_commit: str
    ):
        proposal_number = None
        try:
            proposal_number = self._extract_number_from_path(
                tracker.tracker_type, rel_path
            )
        except Exception:
            return []

        existing = self._get_existing_proposal_model(
            tracker.tracker_type, proposal_number
        )
        if not existing:
            return []

        old_status = getattr(existing, "status", None)
        if old_status and str(old_status).strip().lower() in {
            "draft",
            "deferred",
            "proposed",
        }:
            new_status = "Withdrawn"
            existing.status = new_status
            existing.save()
            event_type = ProposalEventType.WITHDRAWN.value
        else:
            new_status = old_status
            event_type = ProposalEventType.CONTENT_MODIFIED.value

        event_record = self._log_event(
            tracker,
            existing,
            event_type,
            str(old_status) if old_status else None,
            str(new_status) if new_status else None,
            new_commit,
            {"deleted": True, "file_path": rel_path},
        )

        file_url = self._build_file_url(tracker, new_commit, rel_path)
        return [
            ProposalEventReport(
                tracker_type=tracker.tracker_type,
                proposal_number=proposal_number,
                title=getattr(existing, "title", ""),
                event_type=event_type,
                old_status=str(old_status) if old_status else None,
                new_status=str(new_status) if new_status else None,
                commit_hash=new_commit,
                detected_at=event_record.detected_at,
                analysis_summary=getattr(existing, "analysis_summary", None),
                analysis_detail=getattr(existing, "analysis_detail", None),
                file_path=rel_path,
                file_url=file_url,
            )
        ]

    @staticmethod
    def _build_file_url(tracker: ProposalTracker, commit_hash: str, rel_path: str) -> str:
        repo_url = str(getattr(tracker, "repo_url", "") or "")
        base_url = ""
        if repo_url.startswith("https://github.com/"):
            base_url = repo_url.removesuffix(".git")
        elif repo_url.startswith("git@github.com:"):
            base_url = "https://github.com/" + repo_url[len("git@github.com:") :].removesuffix(
                ".git"
            )
        elif repo_url.startswith("ssh://git@github.com/"):
            base_url = "https://github.com/" + repo_url[
                len("ssh://git@github.com/") :
            ].removesuffix(".git")
        else:
            base_url = TRACKER_REPO_URLS.get(tracker.tracker_type, "")

        if not base_url:
            return ""
        return f"{base_url}/blob/{commit_hash}/{rel_path}"

    def _extract_number_from_path(self, tracker_type: str, rel_path: str) -> int:
        from .proposal_parsers import (
            DjangoDEPParser,
            EIPParser,
            PEPParser,
            RustRFCParser,
        )

        parser = {
            "eip": EIPParser(),
            "pep": PEPParser(),
            "rust_rfc": RustRFCParser(),
            "django_dep": DjangoDEPParser(),
        }[tracker_type]
        return parser.get_proposal_number(rel_path)

    def _tracker_repo_slug(self, repo_url: str) -> str:
        s = repo_url
        s = s.removesuffix(".git")
        if s.startswith("https://github.com/"):
            s = s[len("https://github.com/") :]
        return s

    def _tracker_key(self, tracker: ProposalTracker) -> str:
        return f"{tracker.tracker_type}:{tracker.repo_url}@{tracker.branch}"

    def _get_existing_proposal_model(self, tracker_type: str, number: int):
        if tracker_type == "eip":
            return EIP.select().where(EIP.eip_number == number).first()
        if tracker_type == "rust_rfc":
            return RustRFC.select().where(RustRFC.rfc_number == number).first()
        if tracker_type == "pep":
            return PEP.select().where(PEP.pep_number == number).first()
        if tracker_type == "django_dep":
            return DjangoDEP.select().where(DjangoDEP.dep_number == number).first()
        return None

    def _upsert_proposal_model(
        self,
        tracker_type: str,
        existing,
        data,
        commit_hash: str,
        repo_file_path: str,
    ):
        now = get_now(self.cfg.get_timezone())

        if tracker_type == "eip":
            fields = {
                "eip_number": data.number,
                "title": data.title,
                "status": data.status,
                "type": data.type,
                "category": data.extra.get("category"),
                "author": data.author,
                "created_date": data.created_date,
                "file_path": repo_file_path,
                "last_seen_commit": commit_hash,
                "last_check_time": now,
            }
            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
                existing.save()
                return existing
            return EIP.create(**fields)

        if tracker_type == "rust_rfc":
            fields = {
                "rfc_number": data.number,
                "title": data.title,
                "status": data.status,
                "author": data.author,
                "created_date": data.created_date,
                "file_path": repo_file_path,
                "last_seen_commit": commit_hash,
                "last_check_time": now,
            }
            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
                existing.save()
                return existing
            return RustRFC.create(**fields)

        if tracker_type == "pep":
            fields = {
                "pep_number": data.number,
                "title": data.title,
                "status": data.status,
                "type": data.type,
                "topic": data.extra.get("topic"),
                "author": data.author,
                "created_date": data.created_date,
                "file_path": repo_file_path,
                "last_seen_commit": commit_hash,
                "last_check_time": now,
            }
            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
                existing.save()
                return existing
            return PEP.create(**fields)

        if tracker_type == "django_dep":
            fields = {
                "dep_number": data.number,
                "title": data.title,
                "status": data.status,
                "type": data.type,
                "created_date": data.created_date,
                "file_path": repo_file_path,
                "last_seen_commit": commit_hash,
                "last_check_time": now,
            }
            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
                existing.save()
                return existing
            return DjangoDEP.create(**fields)

        raise ValueError(f"Unknown tracker type: {tracker_type}")

    @dataclass
    class _DetectedEvent:
        event_type: str
        old_status: str | None
        new_status: str | None
        metadata: dict

    def _detect_proposal_events(self, tracker_type: str, old_model, new_data):
        events: list[ProposalTrackerManager._DetectedEvent] = []

        if old_model is None:
            events.append(
                self._DetectedEvent(
                    event_type=ProposalEventType.CREATED.value,
                    old_status=None,
                    new_status=new_data.status,
                    metadata={},
                )
            )
            return events

        old_status = str(getattr(old_model, "status", ""))
        new_status = str(new_data.status)
        normalized_new = new_status.strip().lower()

        if old_status.strip() != new_status.strip():
            event_type = ProposalEventType.STATUS_CHANGED.value
            if normalized_new in {"accepted", "final", "active", "living"}:
                event_type = ProposalEventType.ACCEPTED.value
            elif normalized_new in {"rejected"}:
                event_type = ProposalEventType.REJECTED.value
            elif normalized_new in {"withdrawn", "abandoned"}:
                event_type = ProposalEventType.WITHDRAWN.value
            elif normalized_new in {"postponed", "deferred"}:
                event_type = ProposalEventType.POSTPONED.value
            elif normalized_new in {"resurrected"}:
                event_type = ProposalEventType.RESURRECTED.value
            elif normalized_new in {"superseded"}:
                event_type = ProposalEventType.SUPERSEDED.value

            events.append(
                self._DetectedEvent(
                    event_type=event_type,
                    old_status=old_status,
                    new_status=new_status,
                    metadata={},
                )
            )
        else:
            events.append(
                self._DetectedEvent(
                    event_type=ProposalEventType.CONTENT_MODIFIED.value,
                    old_status=old_status,
                    new_status=new_status,
                    metadata={},
                )
            )

        return events

    def _log_event(
        self,
        tracker: ProposalTracker,
        proposal_model,
        event_type: str,
        old_status: str | None,
        new_status: str | None,
        commit_hash: str,
        metadata: dict,
    ) -> ProposalEvent:
        kwargs = {
            "event_type": event_type,
            "old_status": old_status,
            "new_status": new_status,
            "commit_hash": commit_hash,
            "metadata": metadata,
        }

        if proposal_model is None:
            return ProposalEvent.create(**kwargs)

        if tracker.tracker_type == "eip":
            kwargs["eip"] = proposal_model
        elif tracker.tracker_type == "rust_rfc":
            kwargs["rust_rfc"] = proposal_model
        elif tracker.tracker_type == "pep":
            kwargs["pep"] = proposal_model
        elif tracker.tracker_type == "django_dep":
            kwargs["django_dep"] = proposal_model
        else:
            return ProposalEvent.create(**kwargs)

        return ProposalEvent.create(**kwargs)

    def _analyze_event(
        self,
        proposal_type: str,
        event_type: str,
        number: int,
        title: str,
        old_status: str | None,
        new_status: str | None,
        proposal_text: str | None,
        diff_text: str | None,
    ) -> tuple[str, str]:
        try:
            return self.analyzer.analyze_proposal(
                proposal_type=proposal_type,
                event_type=event_type,
                proposal_number=number,
                title=title,
                old_status=old_status,
                new_status=new_status,
                proposal_text=proposal_text,
                diff_text=diff_text,
            )
        except AnalysisException:
            return ("", "")

    def _extract_changed_sections(self, diff_text: str) -> list[str]:
        sections: list[str] = []
        for line in diff_text.splitlines():
            if not line.startswith("+"):
                continue
            content = line[1:].strip()
            if content.startswith("#"):
                sections.append(content.lstrip("#").strip())
        return list(dict.fromkeys(sections))[:20]

    def is_high_priority_event(self, event_type: str) -> bool:
        return event_type in {
            ProposalEventType.CREATED.value,
            ProposalEventType.ACCEPTED.value,
            ProposalEventType.REJECTED.value,
            ProposalEventType.WITHDRAWN.value,
        }
