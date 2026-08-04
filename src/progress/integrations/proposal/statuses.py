"""Proposal status handling (spec proposal §10).

Twelve normalized statuses (§10.1), a terminal set and a notify set (§10.2),
per-kind raw → normalized mappings (§10.3), the normalization rule (§10.4),
the notify filter (§10.5), and the template selector (§10.6).

Mappings are case- and whitespace-sensitive: the lookup is a literal
``dict.get`` on the raw string. Unknown / misspelled statuses normalize to
``unknown``.
"""

from __future__ import annotations

from enum import StrEnum


class ProposalStatus(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    ACCEPTED = "accepted"
    FINAL = "final"
    ACTIVE = "active"
    STAGNANT = "stagnant"
    DEFERRED = "deferred"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    MOVED = "moved"
    UNKNOWN = "unknown"


TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        ProposalStatus.FINAL.value,
        ProposalStatus.ACTIVE.value,
        ProposalStatus.WITHDRAWN.value,
        ProposalStatus.REJECTED.value,
        ProposalStatus.SUPERSEDED.value,
        ProposalStatus.MOVED.value,
        ProposalStatus.UNKNOWN.value,
    }
)

NOTIFY_STATUSES: frozenset[str] = frozenset(
    {
        ProposalStatus.FINAL.value,
        ProposalStatus.ACTIVE.value,
        ProposalStatus.ACCEPTED.value,
        ProposalStatus.WITHDRAWN.value,
        ProposalStatus.REJECTED.value,
    }
)

_EIP_STATUS_MAP: dict[str, str] = {
    "Draft": ProposalStatus.DRAFT.value,
    "Review": ProposalStatus.REVIEW.value,
    "Last Call": ProposalStatus.REVIEW.value,
    "Final": ProposalStatus.FINAL.value,
    "Living": ProposalStatus.ACTIVE.value,
    "Stagnant": ProposalStatus.STAGNANT.value,
    "Withdrawn": ProposalStatus.WITHDRAWN.value,
    "Moved": ProposalStatus.MOVED.value,
}

_PEP_STATUS_MAP: dict[str, str] = {
    "Draft": ProposalStatus.DRAFT.value,
    "Accepted": ProposalStatus.ACCEPTED.value,
    "Provisional": ProposalStatus.ACCEPTED.value,
    "Final": ProposalStatus.FINAL.value,
    "Active": ProposalStatus.ACTIVE.value,
    "Deferred": ProposalStatus.DEFERRED.value,
    "Withdrawn": ProposalStatus.WITHDRAWN.value,
    "Rejected": ProposalStatus.REJECTED.value,
    "April Fool!": ProposalStatus.REJECTED.value,
    "Superseded": ProposalStatus.SUPERSEDED.value,
}

_DEP_STATUS_MAP: dict[str, str] = {
    "Draft": ProposalStatus.DRAFT.value,
    "Accepted": ProposalStatus.ACCEPTED.value,
    "Final": ProposalStatus.FINAL.value,
    "Withdrawn": ProposalStatus.WITHDRAWN.value,
    "Rejected": ProposalStatus.REJECTED.value,
    "Superseded": ProposalStatus.SUPERSEDED.value,
}

_STATUS_MAPS: dict[str, dict[str, str]] = {
    "eip": _EIP_STATUS_MAP,
    "erc": _EIP_STATUS_MAP,
    "pep": _PEP_STATUS_MAP,
    "dep": _DEP_STATUS_MAP,
}


def normalize(raw_status: str, kind: str) -> str:
    """Normalize a raw status string per spec proposal §10.4.

    RFC is special-cased: always normalizes to ``accepted`` (RFC has no status
    field). All other kinds look up the literal raw status in their per-kind
    map; unknown / misspelled statuses become ``unknown``.
    """
    if kind == "rfc":
        return ProposalStatus.ACCEPTED.value
    mapping = _STATUS_MAPS.get(kind, {})
    return mapping.get(raw_status, ProposalStatus.UNKNOWN.value)


def should_notify(old_status: str | None, new_status: str) -> bool:
    """Notify filter (spec proposal §10.5).

    | Scenario | Notify? |
    | new proposal (old None) | yes (even draft) |
    | unchanged status | no |
    | new status in NOTIFY set | yes |
    | new status not in NOTIFY set | no |
    """
    if old_status is None:
        return True
    if old_status == new_status:
        return False
    return new_status in NOTIFY_STATUSES


TEMPLATE_NEW = "proposal_new_prompt.j2"
TEMPLATE_ACCEPTED = "proposal_accepted_prompt.j2"
TEMPLATE_REJECTED = "proposal_rejected_prompt.j2"
TEMPLATE_WITHDRAWN = "proposal_withdrawn_prompt.j2"
TEMPLATE_STATUS_CHANGE = "proposal_status_change_prompt.j2"
TEMPLATE_CONTENT_MODIFIED = "proposal_content_modified_prompt.j2"

_ACCEPTED_TEMPLATES = {
    ProposalStatus.FINAL.value,
    ProposalStatus.ACTIVE.value,
    ProposalStatus.ACCEPTED.value,
}
_STATUS_CHANGE_TEMPLATES = {
    ProposalStatus.DEFERRED.value,
    ProposalStatus.STAGNANT.value,
    ProposalStatus.MOVED.value,
    ProposalStatus.SUPERSEDED.value,
    ProposalStatus.UNKNOWN.value,
}


def select_template(old_status: str | None, new_status: str) -> str:
    """Pick the AI prompt template per spec proposal §10.6.

    Independent of :func:`should_notify` — e.g. Draft → Stagnant produces a
    status-change analysis but does NOT send a notification.
    """
    if old_status is None:
        return TEMPLATE_NEW
    if old_status == new_status:
        return TEMPLATE_CONTENT_MODIFIED
    if new_status in _ACCEPTED_TEMPLATES:
        return TEMPLATE_ACCEPTED
    if new_status == ProposalStatus.REJECTED.value:
        return TEMPLATE_REJECTED
    if new_status == ProposalStatus.WITHDRAWN.value:
        return TEMPLATE_WITHDRAWN
    if new_status in _STATUS_CHANGE_TEMPLATES:
        return TEMPLATE_STATUS_CHANGE
    return TEMPLATE_STATUS_CHANGE


__all__ = [
    "NOTIFY_STATUSES",
    "TEMPLATE_ACCEPTED",
    "TEMPLATE_CONTENT_MODIFIED",
    "TEMPLATE_NEW",
    "TEMPLATE_REJECTED",
    "TEMPLATE_STATUS_CHANGE",
    "TEMPLATE_WITHDRAWN",
    "TERMINAL_STATUSES",
    "ProposalStatus",
    "normalize",
    "select_template",
    "should_notify",
]
