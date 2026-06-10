"""Enumeration type definitions"""

from enum import Enum


class Protocol(Enum):
    """Git protocol types"""

    HTTPS = "https"
    SSH = "ssh"


class ReportType(str, Enum):
    REPO_UPDATE = "repo_update"
    REPO_NEW = "repo_new"
    PROPOSAL = "proposal"
    CHANGELOG = "changelog"
