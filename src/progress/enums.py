"""Enumeration type definitions"""

from enum import Enum


class Protocol(Enum):
    """Git protocol types"""

    HTTPS = "https"
    SSH = "ssh"


class ProposalEventType(Enum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    POSTPONED = "postponed"
    CONTENT_MODIFIED = "content_modified"
    RESURRECTED = "resurrected"
    SUPERSEDED = "superseded"


class ReportType(str, Enum):
    REPO_UPDATE = "repo_update"
    REPO_NEW = "repo_new"
    PROPOSAL = "proposal"
    CHANGELOG = "changelog"
