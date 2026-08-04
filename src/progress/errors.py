"""Structured exception hierarchy for Progress."""


class ProgressException(Exception):  # noqa: N818
    """Base exception for all Progress application errors."""


class ConfigException(ProgressException):
    """Raised when configuration loading or validation fails."""


class GitException(ProgressException):
    """Raised when git operations (clone/fetch/diff) fail."""


class GitHubAPIException(ProgressException):
    """Raised when GitHub API calls fail."""


class GitHubNotFoundException(GitHubAPIException):
    """Raised when GitHub API returns HTTP 404."""


class AnalysisException(ProgressException):
    """Raised when AI analysis operations fail."""


class ProposalParseException(ProgressException):
    """Raised when proposal parsing fails."""


class ChangelogParseException(ProgressException):
    """Raised when changelog parsing fails."""


class CommandException(ProgressException):
    """Raised when subprocess command execution fails."""


class ClientException(ProgressException):
    """Raised when HTTP 4XX client errors occur (non-retryable)."""


class ExternalServiceException(ProgressException):
    """Raised when an external service call fails."""


class ReportException(ProgressException):
    """Raised when report generation fails."""


class NotificationException(ProgressException):
    """Raised when notification dispatch fails."""
