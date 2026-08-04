"""``feed`` integration package.

Importing this package registers :class:`FeedIntegration` with the global
integration registry via the ``@register("feed")`` decorator.
"""

from progress.integrations.feed.client import MINIFLUX_TIMEOUT, MinifluxClient, RawEntry
from progress.integrations.feed.config import FeedIntegrationConfig
from progress.integrations.feed.fetcher import MAX_ENTRIES_PER_FEED, Feed
from progress.integrations.feed.models import FeedTracker
from progress.integrations.feed.tracker import EntryAnalysis, FeedAnalysis, FeedIntegration

__all__ = [
    "MAX_ENTRIES_PER_FEED",
    "MINIFLUX_TIMEOUT",
    "EntryAnalysis",
    "Feed",
    "FeedAnalysis",
    "FeedIntegration",
    "FeedIntegrationConfig",
    "FeedTracker",
    "MinifluxClient",
    "RawEntry",
]
