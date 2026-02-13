"""Database migration for owner monitoring tables."""

import logging

from progress.contrib.repo.models import DiscoveredRepository, GitHubOwner

logger = logging.getLogger(__name__)


def apply(database) -> None:
    database.create_tables([GitHubOwner, DiscoveredRepository], safe=True)
    logger.info("Migration applied: owner monitoring tables")


def rollback(database) -> None:
    database.drop_tables([DiscoveredRepository, GitHubOwner], safe=True)
    logger.info("Migration rolled back: owner monitoring tables")
