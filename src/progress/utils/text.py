"""String manipulation helpers."""


def strip_git_suffix(name: str) -> str:
    """Safely remove .git suffix from a string.

    Unlike str.rstrip('.git'), this only removes the exact suffix.

    Args:
        name: String that may end with .git

    Returns:
        String with .git suffix removed if present

    Examples:
        >>> strip_git_suffix("owner/repo.git")
        'owner/repo'
        >>> strip_git_suffix("OpenList")
        'OpenList'
        >>> strip_git_suffix("vue.js")
        'vue.js'
    """
    if name.endswith(".git"):
        return name[:-4]
    return name
