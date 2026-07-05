"""Sensitive-data masking for safe logging."""


def sanitize(sensitive: str | None, keep_chars: int = 2) -> str:
    """Mask sensitive information for logging.

    Args:
        sensitive: The sensitive string to mask (e.g., token, password, URL)
        keep_chars: Number of leading and trailing characters to keep

    Returns:
        Masked string with middle characters replaced by asterisks.

    Examples:
        >>> sanitize("ghp_abc123def456xyz789")
        'gh***89'
        >>> sanitize("my_secret_password", keep_chars=3)
        'my***ord'
        >>> sanitize(None)
        '***'
    """
    if not sensitive:
        return "***"

    if len(sensitive) <= keep_chars * 2:
        return "***"

    return f"{sensitive[:keep_chars]}***{sensitive[-keep_chars:]}"
