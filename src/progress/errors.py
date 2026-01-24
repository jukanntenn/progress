"""Exception definitions for Progress application"""


class ProgressException(Exception):
    """Base exception for all Progress application errors."""

    pass


class ConfigException(ProgressException):
    """Raised when configuration validation or loading fails."""

    pass


class GitException(ProgressException):
    """Raised when GitHub/Git operations fail."""

    pass


class AnalysisException(ProgressException):
    """Raised when code analysis operations fail."""

    pass


class CommandException(ProgressException):
    """Raised when external command execution fails."""

    pass


class ClientError(ProgressException):
    """Raised when HTTP 4XX client errors occur and should not be retried."""

    pass
