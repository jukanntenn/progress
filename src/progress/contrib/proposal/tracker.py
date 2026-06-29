import fnmatch
import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, NamedTuple
from zoneinfo import ZoneInfo

from progress.ai import Analyzer
from progress.errors import GitException, ProposalParseError
from progress.github import GitClient, sanitize_repo_name
from progress.telemetry import report_error
from progress.utils import run_command

from .analysis import run_analysis
from .models import Proposal, ProposalTrackerState
from .parser import get_parser
from .status import get_analysis_template, normalize
from .types import (
    KIND_CONFIGS,
    TERMINAL_STATUSES,
    KindConfig,
    ProposalKind,
    ProposalStatus,
)

logger = logging.getLogger(__name__)

UTC = ZoneInfo("UTC")
_EPOCH = datetime.min.replace(tzinfo=UTC)


class ProposalReport(NamedTuple):
    kind: ProposalKind
    number: str
    title: str | None
    old_status: ProposalStatus | None
    new_status: ProposalStatus
    file_path: str
    file_url: str
    commit_hash: str
    analysis_summary: str | None
    analysis_detail: str | None


class ProposalTracker:
    def __init__(
        self,
        analyzer: Analyzer,
        git_client: GitClient,
        clock: Callable[[], datetime],
        language: str = "en",
    ):
        self.analyzer = analyzer
        self.git = git_client
        self.clock = clock
        self.language = language

    def check(self, kind: ProposalKind) -> list[ProposalReport]:
        config = KIND_CONFIGS[kind]
        state = self._get_or_create_state(kind)
        parser = get_parser(kind)

        logger.info("Proposal check started: kind=%s", kind.value)
        start = time.monotonic()

        try:
            repo_path = self._clone_or_update(config)
        except GitException as e:
            report_error(e, kind=kind.value, stage="clone")
            raise
        current_commit = self.git.get_current_commit(repo_path)
        logger.info(
            "Proposal repo ready: kind=%s commit=%s",
            kind.value,
            current_commit[:12],
        )

        if state.last_seen_commit is None:
            return self._initial_check(
                kind, config, state, parser, repo_path, current_commit
            )

        if current_commit == state.last_seen_commit:
            logger.info("No new commits: kind=%s", kind.value)
            state.last_check_time = self.clock()
            state.save()
            return []

        changed_files = self.git.get_changed_file_statuses(
            repo_path, state.last_seen_commit, current_commit
        )
        filtered = self._filter_files(config, changed_files)
        logger.info(
            "Incremental check: kind=%s changed=%d filtered=%d %s..%s",
            kind.value,
            len(changed_files),
            len(filtered),
            state.last_seen_commit[:12],
            current_commit[:12],
        )

        moved_numbers = self._detect_moved_proposals(filtered, parser)
        if moved_numbers:
            logger.debug(
                "Detected moved proposals: kind=%s numbers=%s",
                kind.value,
                moved_numbers,
            )

        reports: list[ProposalReport] = []

        for change_type, rel_path in filtered:
            if change_type.startswith("D"):
                continue
            r = self._handle_changed(
                kind,
                config,
                state,
                parser,
                repo_path,
                rel_path,
                state.last_seen_commit,
                current_commit,
            )
            if r:
                logger.info(
                    "Proposal changed: kind=%s number=%s %s -> %s",
                    kind.value,
                    r.number,
                    r.old_status.value if r.old_status else "new",
                    r.new_status.value,
                )
                reports.append(r)

        for change_type, rel_path in filtered:
            if not change_type.startswith("D"):
                continue
            number = parser.extract_number(rel_path)
            if number in moved_numbers:
                logger.debug(
                    "Skipping delete for moved proposal: kind=%s number=%s",
                    kind.value,
                    number,
                )
                continue
            r = self._handle_deleted(kind, state, parser, rel_path, current_commit)
            if r:
                logger.info(
                    "Proposal deleted: kind=%s number=%s %s -> %s",
                    kind.value,
                    r.number,
                    r.old_status.value,
                    r.new_status.value,
                )
                reports.append(r)

        state.last_seen_commit = current_commit
        state.last_check_time = self.clock()
        state.save()

        duration = time.monotonic() - start
        logger.info(
            "Proposal check completed: kind=%s reports=%d duration=%.1fs",
            kind.value,
            len(reports),
            duration,
        )
        return reports

    def check_all(
        self,
        kinds: list[ProposalKind],
        concurrency: int = 1,
    ) -> list[ProposalReport]:
        if not kinds:
            return []

        if concurrency <= 1:
            reports: list[ProposalReport] = []
            for kind in kinds:
                try:
                    reports.extend(self.check(kind))
                except Exception as e:
                    logger.warning(
                        "Proposal tracker check failed for %s: %s", kind.value, e
                    )
            return reports

        all_reports: list[ProposalReport] = []
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(self.check, kind): kind for kind in kinds}
            for future in as_completed(futures):
                kind = futures[future]
                try:
                    all_reports.extend(future.result())
                except Exception as e:
                    logger.warning(
                        "Proposal tracker check failed for %s: %s", kind.value, e
                    )
        return all_reports

    def _get_or_create_state(self, kind: ProposalKind) -> ProposalTrackerState:
        state = (
            ProposalTrackerState.select()
            .where(ProposalTrackerState.kind == kind.value)
            .first()
        )
        if state is None:
            state = ProposalTrackerState.create(kind=kind.value)
            logger.info("Created tracker state: kind=%s", kind.value)
        return state

    def _clone_or_update(self, config: KindConfig) -> Path:
        repo_slug = config.repo_url.removesuffix(".git")
        if repo_slug.startswith("https://github.com/"):
            repo_slug = repo_slug[len("https://github.com/") :]
        sanitized = sanitize_repo_name(repo_slug)

        local_dir = self.git.workspace_dir / "proposal_repos" / sanitized
        local_dir.parent.mkdir(parents=True, exist_ok=True)

        if local_dir.exists() and (local_dir / ".git").exists():
            try:
                self.git.fetch_and_reset(local_dir, config.branch)
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
                    config.branch,
                    config.repo_url,
                    str(local_dir),
                ],
                timeout=self.git.timeout,
                check=True,
            )
            logger.info("Cloned proposal repo: %s -> %s", config.repo_url, sanitized)
            return local_dir
        except Exception as e:
            raise GitException(str(e)) from e

    def _filter_files(
        self,
        config: KindConfig,
        changes: list[tuple[str, str]],
    ) -> list[tuple[str, str]]:
        filtered: list[tuple[str, str]] = []
        for status, path in changes:
            if config.proposal_dir:
                norm_dir = config.proposal_dir.strip("/") + "/"
                if not path.startswith(norm_dir):
                    continue

            name = Path(path).name
            if not any(fnmatch.fnmatch(name, p) for p in config.file_pattern):
                continue

            filtered.append((status, path))
        return filtered

    def _detect_moved_proposals(
        self,
        filtered: list[tuple[str, str]],
        parser,
    ) -> set[str]:
        add_paths = [p for s, p in filtered if not s.startswith("D")]
        del_paths = [p for s, p in filtered if s.startswith("D")]
        if not add_paths or not del_paths:
            return set()

        add_numbers = {parser.extract_number(p) for p in add_paths} - {""}
        moved: set[str] = set()
        for del_path in del_paths:
            num = parser.extract_number(del_path)
            if num and num in add_numbers:
                moved.add(num)
        return moved

    def _upsert_proposal(
        self,
        state: ProposalTrackerState,
        parsed,
        new_status: ProposalStatus,
    ) -> None:
        existing = (
            Proposal.select()
            .where((Proposal.tracker == state) & (Proposal.number == parsed.number))
            .first()
        )
        if existing:
            existing.title = parsed.title
            existing.raw_status = parsed.raw_status
            existing.status = new_status.value
            existing.save()
        else:
            Proposal.create(
                tracker=state,
                number=parsed.number,
                title=parsed.title,
                raw_status=parsed.raw_status,
                status=new_status.value,
            )

    def _initial_check(
        self,
        kind: ProposalKind,
        config: KindConfig,
        state: ProposalTrackerState,
        parser,
        repo_path: Path,
        current_commit: str,
    ) -> list[ProposalReport]:
        start = time.monotonic()
        base = repo_path / config.proposal_dir if config.proposal_dir else repo_path
        if not base.exists():
            logger.warning(
                "Initial proposal check skipped (%s): dir not found: %s",
                kind.value,
                config.proposal_dir,
            )
            state.last_seen_commit = current_commit
            state.last_check_time = self.clock()
            state.save()
            return []

        matches: list[Path] = []
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if not any(fnmatch.fnmatch(p.name, pat) for pat in config.file_pattern):
                continue
            matches.append(p)

        if not matches:
            logger.warning(
                "Initial proposal check found no files (%s)",
                kind.value,
            )
            state.last_seen_commit = current_commit
            state.last_check_time = self.clock()
            state.save()
            return []

        latest_path: Path | None = None
        latest_dt = _EPOCH
        parsed_count = 0

        for p in matches:
            rel_path = str(p.relative_to(repo_path))
            try:
                parsed = parser.parse(str(p))
            except ProposalParseError as e:
                logger.debug(
                    "Skipping unparseable file in initial check: %s: %s",
                    rel_path,
                    e,
                )
                continue

            parsed_count += 1
            new_status = normalize(kind, parsed.raw_status)
            self._upsert_proposal(state, parsed, new_status)

            created_str = self.git.get_file_creation_date(repo_path, rel_path)
            cmp = _EPOCH
            if created_str:
                try:
                    created_dt = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S %z")
                    cmp = (
                        created_dt.replace(tzinfo=UTC)
                        if created_dt.tzinfo is None
                        else created_dt
                    )
                except ValueError:
                    pass

            if cmp > latest_dt:
                latest_dt = cmp
                latest_path = p

        logger.info(
            "Initial check: kind=%s parsed=%d files from %s",
            kind.value,
            parsed_count,
            config.proposal_dir or "<root>",
        )

        if latest_path is None:
            state.last_seen_commit = current_commit
            state.last_check_time = self.clock()
            state.save()
            return []

        latest_rel_path = str(latest_path.relative_to(repo_path))
        try:
            parsed = parser.parse(str(latest_path))
        except ProposalParseError:
            logger.warning(
                "Initial proposal check could not parse selected example (%s): %s",
                kind.value,
                latest_rel_path,
            )
            state.last_seen_commit = current_commit
            state.last_check_time = self.clock()
            state.save()
            return []

        new_status = normalize(kind, parsed.raw_status)
        summary, detail = run_analysis(
            self.analyzer,
            "proposal_new_prompt.j2",
            kind,
            parsed.number,
            parsed.title,
            None,
            parsed.raw_status,
            content=parsed.full_text,
            language=self.language,
        )

        file_url = self._build_file_url(config, current_commit, latest_rel_path)
        report = ProposalReport(
            kind=kind,
            number=parsed.number,
            title=parsed.title,
            old_status=None,
            new_status=new_status,
            file_path=latest_rel_path,
            file_url=file_url,
            commit_hash=current_commit,
            analysis_summary=summary or None,
            analysis_detail=detail or None,
        )

        state.last_seen_commit = current_commit
        state.last_check_time = self.clock()
        state.save()

        logger.info(
            "Initial check completed: kind=%s total=%d verification=%s duration=%.1fs",
            kind.value,
            parsed_count,
            parsed.number,
            time.monotonic() - start,
        )
        return [report]

    def _handle_changed(
        self,
        kind: ProposalKind,
        config: KindConfig,
        state: ProposalTrackerState,
        parser,
        repo_path: Path,
        rel_path: str,
        old_commit: str,
        new_commit: str,
    ) -> ProposalReport | None:
        abs_path = str(repo_path / rel_path)
        try:
            parsed = parser.parse(abs_path)
        except ProposalParseError as e:
            logger.warning("Failed to parse proposal %s: %s", abs_path, e)
            return None

        new_status = normalize(kind, parsed.raw_status)

        existing = (
            Proposal.select()
            .where((Proposal.tracker == state) & (Proposal.number == parsed.number))
            .first()
        )
        old_status = ProposalStatus(existing.status) if existing else None

        template = get_analysis_template(old_status, new_status)

        if old_status is not None and old_status == new_status:
            diff_text = self.git.get_file_diff(
                repo_path, old_commit, new_commit, rel_path
            )
            summary, detail = run_analysis(
                self.analyzer,
                template,
                kind,
                parsed.number,
                parsed.title,
                parsed.raw_status,
                parsed.raw_status,
                content=diff_text,
                language=self.language,
            )
        else:
            summary, detail = run_analysis(
                self.analyzer,
                template,
                kind,
                parsed.number,
                parsed.title,
                existing.raw_status if existing else None,
                parsed.raw_status,
                content=parsed.full_text,
                language=self.language,
            )

        self._upsert_proposal(state, parsed, new_status)

        file_url = self._build_file_url(config, new_commit, rel_path)
        return ProposalReport(
            kind=kind,
            number=parsed.number,
            title=parsed.title,
            old_status=old_status,
            new_status=new_status,
            file_path=rel_path,
            file_url=file_url,
            commit_hash=new_commit,
            analysis_summary=summary or None,
            analysis_detail=detail or None,
        )

    def _handle_deleted(
        self,
        kind: ProposalKind,
        state: ProposalTrackerState,
        parser,
        rel_path: str,
        new_commit: str,
    ) -> ProposalReport | None:
        number = parser.extract_number(rel_path)
        if not number:
            return None

        existing = (
            Proposal.select()
            .where((Proposal.tracker == state) & (Proposal.number == number))
            .first()
        )
        if not existing:
            logger.debug(
                "Ignoring delete for unknown proposal: kind=%s path=%s",
                kind.value,
                rel_path,
            )
            return None

        old_status = ProposalStatus(existing.status)

        if old_status not in TERMINAL_STATUSES:
            existing.status = ProposalStatus.WITHDRAWN.value
            existing.save()
            new_status = ProposalStatus.WITHDRAWN
        else:
            new_status = old_status

        config = KIND_CONFIGS[kind]
        file_url = self._build_file_url(config, state.last_seen_commit, rel_path)
        return ProposalReport(
            kind=kind,
            number=number,
            title=existing.title,
            old_status=old_status,
            new_status=new_status,
            file_path=rel_path,
            file_url=file_url,
            commit_hash=new_commit,
            analysis_summary=None,
            analysis_detail=None,
        )

    @staticmethod
    def _build_file_url(config: KindConfig, commit_hash: str, rel_path: str) -> str:
        base_url = config.repo_url.removesuffix(".git")
        return f"{base_url}/blob/{commit_hash}/{rel_path}"
