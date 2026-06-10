from .types import ProposalKind, ProposalStatus

NOTIFY_STATUSES = frozenset(
    {
        ProposalStatus.FINAL,
        ProposalStatus.ACTIVE,
        ProposalStatus.ACCEPTED,
        ProposalStatus.WITHDRAWN,
        ProposalStatus.REJECTED,
    }
)

_EIP_ERC_MAP: dict[str, ProposalStatus] = {
    "Draft": ProposalStatus.DRAFT,
    "Review": ProposalStatus.REVIEW,
    "Last Call": ProposalStatus.REVIEW,
    "Final": ProposalStatus.FINAL,
    "Living": ProposalStatus.ACTIVE,
    "Stagnant": ProposalStatus.STAGNANT,
    "Withdrawn": ProposalStatus.WITHDRAWN,
    "Moved": ProposalStatus.MOVED,
}

_PEP_MAP: dict[str, ProposalStatus] = {
    "Draft": ProposalStatus.DRAFT,
    "Accepted": ProposalStatus.ACCEPTED,
    "Provisional": ProposalStatus.ACCEPTED,
    "Final": ProposalStatus.FINAL,
    "Active": ProposalStatus.ACTIVE,
    "Deferred": ProposalStatus.DEFERRED,
    "Withdrawn": ProposalStatus.WITHDRAWN,
    "Rejected": ProposalStatus.REJECTED,
    "April Fool!": ProposalStatus.REJECTED,
    "Superseded": ProposalStatus.SUPERSEDED,
}

_DEP_MAP: dict[str, ProposalStatus] = {
    "Draft": ProposalStatus.DRAFT,
    "Accepted": ProposalStatus.ACCEPTED,
    "Final": ProposalStatus.FINAL,
    "Withdrawn": ProposalStatus.WITHDRAWN,
    "Rejected": ProposalStatus.REJECTED,
    "Superseded": ProposalStatus.SUPERSEDED,
}

STATUS_MAPS: dict[ProposalKind, dict[str, ProposalStatus]] = {
    ProposalKind.EIP: _EIP_ERC_MAP,
    ProposalKind.ERC: _EIP_ERC_MAP,
    ProposalKind.PEP: _PEP_MAP,
    ProposalKind.RFC: {},
    ProposalKind.DEP: _DEP_MAP,
}


def normalize(kind: ProposalKind, raw_status: str) -> ProposalStatus:
    if kind == ProposalKind.RFC:
        return ProposalStatus.ACCEPTED
    return STATUS_MAPS[kind].get(raw_status, ProposalStatus.UNKNOWN)


def should_notify(
    old_status: ProposalStatus | None, new_status: ProposalStatus
) -> bool:
    if old_status is None:
        return True
    if old_status == new_status:
        return False
    return new_status in NOTIFY_STATUSES


def get_analysis_template(
    old_status: ProposalStatus | None, new_status: ProposalStatus
) -> str:
    if old_status is None:
        return "proposal_new_prompt.j2"
    if old_status == new_status:
        return "proposal_content_modified_prompt.j2"
    return {
        ProposalStatus.FINAL: "proposal_accepted_prompt.j2",
        ProposalStatus.ACTIVE: "proposal_accepted_prompt.j2",
        ProposalStatus.ACCEPTED: "proposal_accepted_prompt.j2",
        ProposalStatus.REJECTED: "proposal_rejected_prompt.j2",
        ProposalStatus.WITHDRAWN: "proposal_withdrawn_prompt.j2",
    }.get(new_status, "proposal_status_change_prompt.j2")
