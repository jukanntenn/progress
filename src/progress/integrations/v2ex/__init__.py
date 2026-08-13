"""``v2ex`` integration package.

Importing this package registers :class:`V2exIntegration` with the global
integration registry via the ``@register("v2ex")`` decorator.
"""

from progress.integrations.v2ex.client import V2exClient
from progress.integrations.v2ex.config import V2exIntegrationConfig
from progress.integrations.v2ex.fetcher import ClassifiedPost
from progress.integrations.v2ex.models import V2exTracker
from progress.integrations.v2ex.parser import RawTopic, parse_tab_page
from progress.integrations.v2ex.tracker import (
    V2exClassificationResult,
    V2exIntegration,
    V2exPostClassification,
    V2exPostSummary,
    V2exSummaryResult,
)

__all__ = [
    "ClassifiedPost",
    "RawTopic",
    "V2exClassificationResult",
    "V2exClient",
    "V2exIntegration",
    "V2exIntegrationConfig",
    "V2exPostClassification",
    "V2exPostSummary",
    "V2exSummaryResult",
    "V2exTracker",
    "parse_tab_page",
]
