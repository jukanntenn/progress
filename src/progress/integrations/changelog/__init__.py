"""``changelog`` integration package.

Importing this package registers :class:`ChangelogIntegration` with the global
integration registry via the ``@register("changelog")`` decorator.
"""

from progress.integrations.changelog.config import (
    ChangelogIntegrationConfig,
    ChangelogItemConfig,
    ParserType,
)
from progress.integrations.changelog.models import ChangelogTracker
from progress.integrations.changelog.parsers import (
    ChangelogRule,
    ChangelogVersion,
    apply_rule,
    parse_html_generic,
    parse_markdown_heading,
)
from progress.integrations.changelog.tracker import ChangelogIntegration, UniversalChangelogParser

__all__ = [
    "ChangelogIntegration",
    "ChangelogIntegrationConfig",
    "ChangelogItemConfig",
    "ChangelogRule",
    "ChangelogTracker",
    "ChangelogVersion",
    "ParserType",
    "UniversalChangelogParser",
    "apply_rule",
    "parse_html_generic",
    "parse_markdown_heading",
]
