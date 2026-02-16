import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class DBStorage:
    def __init__(
        self,
        *,
        report_type: str = "repo_update",
        repo_id: int | None = None,
        commit_hash: str = "",
        previous_commit_hash: str | None = None,
        commit_count: int = 0,
        markpost_url: str | None = None,
    ) -> None:
        self._report_type = report_type
        self._repo_id = repo_id
        self._commit_hash = commit_hash
        self._previous_commit_hash = previous_commit_hash
        self._commit_count = commit_count
        self._markpost_url = markpost_url
        self.report_id: int | None = None

    def save(self, title: str, body: str | None, directory: Path) -> str:
        from progress.db.models import Report

        report = Report.create(
            report_type=self._report_type,
            repo=self._repo_id,
            title=title,
            commit_hash=self._commit_hash,
            previous_commit_hash=self._previous_commit_hash,
            commit_count=self._commit_count,
            markpost_url=self._markpost_url,
            content=body,
        )
        self.report_id = report.id
        logger.info(f"Report saved: {report.id} (type={self._report_type})")
        return str(report.id)
