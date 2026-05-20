import logging

logger = logging.getLogger(__name__)


class DBStorage:
    def save(self, title: str, bodies: list[str]) -> list[str]:
        from progress.db.models import Report

        logger.debug("Saving report to database")
        full_body = "\n\n".join(bodies)
        report = Report.create(title=title, content=full_body, commit_hash="")
        return [str(report.id)]
