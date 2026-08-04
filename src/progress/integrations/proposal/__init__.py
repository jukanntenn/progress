"""``proposal`` integration package.

Importing this package registers :class:`ProposalIntegration` with the global
integration registry via the ``@register("proposal")`` decorator.
"""

from progress.integrations.proposal.config import (
    SUPPORTED_KINDS,
    ProposalIntegrationConfig,
)
from progress.integrations.proposal.models import (
    Proposal,
    ProposalTrackerState,
)
from progress.integrations.proposal.tracker import ProposalIntegration

__all__ = [
    "SUPPORTED_KINDS",
    "Proposal",
    "ProposalIntegration",
    "ProposalIntegrationConfig",
    "ProposalTrackerState",
]
