from enum import StrEnum
from typing import NamedTuple


class ProposalKind(StrEnum):
    EIP = "eip"
    ERC = "erc"
    PEP = "pep"
    RFC = "rfc"
    DEP = "dep"


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


TERMINAL_STATUSES = frozenset(
    {
        ProposalStatus.FINAL,
        ProposalStatus.ACTIVE,
        ProposalStatus.WITHDRAWN,
        ProposalStatus.REJECTED,
        ProposalStatus.SUPERSEDED,
        ProposalStatus.MOVED,
        ProposalStatus.UNKNOWN,
    }
)


class KindConfig(NamedTuple):
    repo_url: str
    branch: str
    proposal_dir: str
    file_pattern: list[str]


KIND_CONFIGS: dict[ProposalKind, KindConfig] = {
    ProposalKind.EIP: KindConfig(
        repo_url="https://github.com/ethereum/EIPs",
        branch="master",
        proposal_dir="EIPS",
        file_pattern=["eip-*.md"],
    ),
    ProposalKind.ERC: KindConfig(
        repo_url="https://github.com/ethereum/ercs",
        branch="main",
        proposal_dir="ERCS",
        file_pattern=["erc-*.md"],
    ),
    ProposalKind.PEP: KindConfig(
        repo_url="https://github.com/python/peps",
        branch="main",
        proposal_dir="",
        file_pattern=["pep-*.rst"],
    ),
    ProposalKind.RFC: KindConfig(
        repo_url="https://github.com/rust-lang/rfcs",
        branch="master",
        proposal_dir="text",
        file_pattern=["*.md"],
    ),
    ProposalKind.DEP: KindConfig(
        repo_url="https://github.com/django/deps",
        branch="main",
        proposal_dir="",
        file_pattern=["*.rst", "*.md"],
    ),
}
