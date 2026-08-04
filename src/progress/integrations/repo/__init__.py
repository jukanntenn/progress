"""``repo`` integration package.

Importing this package registers :class:`RepoIntegration` with the global
integration registry via the ``@register("repo")`` decorator on the class.
"""

from progress.integrations.repo.config import (
    OwnerItemConfig,
    RepoIntegrationConfig,
    RepoItemConfig,
)
from progress.integrations.repo.models import GitHubOwner, Repository
from progress.integrations.repo.tracker import RepoIntegration

__all__ = [
    "GitHubOwner",
    "OwnerItemConfig",
    "RepoIntegration",
    "RepoIntegrationConfig",
    "RepoItemConfig",
    "Repository",
]
