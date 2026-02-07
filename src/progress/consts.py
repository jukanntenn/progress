"""Constants for Progress application"""

# ==================== File Paths ====================
DATABASE_PATH = "data/progress.db"
WORKSPACE_DIR_DEFAULT = "data/repos"


# ==================== GitHub Patterns ====================
GITHUB_DOMAIN = "github.com"
GITHUB_HTTPS_PREFIX = f"https://{GITHUB_DOMAIN}/"
GITHUB_SSH_PREFIX = "git@github.com:"
GIT_SUFFIX = ".git"

# ==================== Command Names ====================
CMD_GIT = "git"
CMD_GH = "gh"
CMD_CLAUDE = "claude"

# ==================== Timeouts (seconds) ====================
TIMEOUT_GIT_COMMAND = 300  # 5 minutes - git operations
TIMEOUT_GH_COMMAND = 300  # 5 minutes - gh CLI operations
TIMEOUT_CLAUDE_ANALYSIS = 600  # 10 minutes - Claude Code analysis
TIMEOUT_HTTP_REQUEST = 30  # 30 seconds - HTTP requests
TIMEOUT_SMTP = 10  # 10 seconds - SMTP operations

# ==================== Retry Configuration ====================
GIT_MAX_RETRIES = 3
GIT_RETRY_DELAY = 5  # seconds
GH_MAX_RETRIES = 3
GH_RETRY_DELAY = 5  # seconds

# ==================== Template Names ====================
TEMPLATE_ANALYSIS_PROMPT = "analysis_prompt.j2"
TEMPLATE_README_ANALYSIS_PROMPT = "readme_analysis_prompt.j2"
TEMPLATE_REPOSITORY_REPORT = "repository_report.j2"
TEMPLATE_AGGREGATED_REPORT = "aggregated_report.j2"
TEMPLATE_EMAIL_NOTIFICATION = "email_notification.j2"
TEMPLATE_CHANGELOG_NOTIFICATION = "changelog_notification.j2"

# ==================== URL Patterns ====================
REPO_URL_PATTERNS = [
    r"^[\w-]+/[\w-]+$",  # owner/repo
    r"^https?://",  # https:// or http://
    r"^git@[\w.-]+:[\w-]+/[\w-]+\.?git?$",  # git@host:owner/repo.git
]

# ==================== Database Configuration ====================
DB_MAX_CONNECTIONS = 20
DB_STALE_TIMEOUT = 300  # 5 minutes
DB_JOURNAL_MODE = "wal"
DB_SYNCHRONOUS = "NORMAL"
DB_BUSY_TIMEOUT = 5000  # 5 seconds
DB_CACHE_SIZE = -64 * 1000  # 64MB

# ==================== Database Pragmas ====================
DB_PRAGMAS = {
    "journal_mode": DB_JOURNAL_MODE,
    "synchronous": DB_SYNCHRONOUS,
    "busy_timeout": DB_BUSY_TIMEOUT,
    "foreign_keys": 1,
    "cache_size": DB_CACHE_SIZE,
}


def parse_repo_name(url: str) -> str:
    """Extract repository slug (owner/repo) from URL.

    Args:
        url: Repository URL in any supported format:
             - owner/repo
             - https://github.com/owner/repo(.git)
             - git@github.com:owner/repo(.git)

    Returns:
        Repository slug in "owner/repo" format

    Examples:
        >>> parse_repo_name("vitejs/vite")
        'vitejs/vite'
        >>> parse_repo_name("https://github.com/vitejs/vite.git")
        'vitejs/vite'
        >>> parse_repo_name("git@github.com:vitejs/vite")
        'vitejs/vite'
    """
    import re

    if re.match(r"^[\w-]+/[\w-]+$", url):
        return url

    https_match = re.match(r"^https?://github\.com/([^/]+)/([^/.]+)", url)
    if https_match:
        return f"{https_match.group(1)}/{https_match.group(2)}"

    ssh_match = re.match(r"^git@github\.com:([^/]+)/([^/.]+)", url)
    if ssh_match:
        return f"{ssh_match.group(1)}/{ssh_match.group(2)}"

    if "/" in url:
        # Remove .git suffix if present (use removesuffix, not rstrip)
        if url.endswith(GIT_SUFFIX):
            url = url[:-4]
        parts = url.split("/")
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"

    return url
