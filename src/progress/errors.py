"""Exception definitions for Progress application"""


class ProgressException(Exception):
    """Base exception for all Progress application errors.

    All custom exceptions in the Progress application inherit from this class.
    Use this as a catch-all for Progress-specific errors when you don't need
    to handle specific exception types.
    """

    pass


class ConfigException(ProgressException):
    """Raised when configuration validation or loading fails.

    Use this exception when:
    - The configuration file cannot be found
    - The TOML syntax is invalid
    - Configuration validation fails (missing required fields, invalid values)
    - Type conversion of config values fails
    """

    pass


class GitException(ProgressException):
    """Raised when GitHub/Git operations fail.

    Use this exception when:
    - Git command execution fails (clone, fetch, checkout, etc.)
    - GitHub API calls fail
    - Repository operations encounter errors
    - Git authentication fails
    """

    pass


class AnalysisException(ProgressException):
    """Raised when code analysis operations fail.

    Use this exception when:
    - AI analysis requests fail or timeout
    - JSON parsing of AI responses fails
    - Response validation fails (missing required fields)
    - Analysis output cannot be extracted or processed
    """

    pass


class ProposalParseError(ProgressException):
    pass


class ChangelogParseError(ProgressException):
    pass


class CommandException(ProgressException):
    """Raised when external command execution fails.

    Use this exception when:
    - Shell commands return non-zero exit codes
    - Command execution times out
    - Command cannot be found or executed
    - Any subprocess operation fails
    """

    pass


class ClientError(ProgressException):
    """Raised when HTTP 4XX client errors occur and should not be retried.

    Use this exception when:
    - HTTP requests return 4xx status codes (400-499)
    - The error indicates a client-side problem (authentication, invalid request, etc.)
    - Retrying the request would not succeed without changes

    This exception is distinct from transient 5xx errors or network issues.
    """

    pass
