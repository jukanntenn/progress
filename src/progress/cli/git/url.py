r"""GitHub URL parsing helpers (spec 07).

Spec 07 calls out a regex bug in the legacy ``REPO_URL_PATTERNS``: the pattern
``\.?git?`` made the trailing ``t`` optional (so "gi" matched). This module
fixes that with strict, unambiguous patterns and exposes a small API:

- ``parse_repo_url(url)`` -> ``RepoRef(owner, name)`` for GitHub URLs.
- ``is_github_url(url)`` -> bool.
- ``build_clone_url(owner, name)`` -> canonical HTTPS clone URL.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

_GITHUB_HTTPS_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/\s]+)/(?P<name>[^/\s]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_GITHUB_SSH_RE = re.compile(
    r"^git@github\.com:(?P<owner>[^/\s]+)/(?P<name>[^/\s]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_GITHUB_OWNER_REPO_RE = re.compile(r"^(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)/(?P<name>[A-Za-z0-9._-]+)$")


@dataclass(frozen=True)
class RepoRef:
    """Owner/name pair identifying a GitHub repository."""

    owner: str
    name: str

    @property
    def slug(self) -> str:
        """``owner/name`` form used by the GitHub REST API."""
        return f"{self.owner}/{self.name}"


def is_github_url(url: str) -> bool:
    """Return True if ``url`` is any recognised GitHub URL form."""
    if not url:
        return False
    return bool(_GITHUB_HTTPS_RE.match(url) or _GITHUB_SSH_RE.match(url) or _GITHUB_OWNER_REPO_RE.match(url))


def parse_repo_url(url: str) -> RepoRef:
    """Parse a GitHub URL or ``owner/name`` shorthand into a :class:`RepoRef`.

    Raises ``ValueError`` if the URL is not recognised. The legacy regex bug
    (``\\.?git?`` making the ``t`` optional) is fixed: only a literal ``.git``
    suffix is stripped, never partial matches.
    """
    if not url:
        raise ValueError("empty repository url")

    for pattern in (_GITHUB_HTTPS_RE, _GITHUB_SSH_RE, _GITHUB_OWNER_REPO_RE):
        match = pattern.match(url.strip())
        if match:
            return RepoRef(
                owner=match.group("owner"),
                name=match.group("name"),
            )

    raise ValueError(f"unrecognised GitHub repository URL: {url!r}")


def build_clone_url(owner: str, name: str) -> str:
    """Return the canonical HTTPS clone URL for ``owner/name``."""
    return f"https://github.com/{owner}/{name}.git"


def build_authenticated_clone_url(owner: str, name: str, token: str) -> str:
    """Return an HTTPS clone URL with the token embedded for non-interactive auth.

    Per spec 07 the token is only embedded in the URL when one is provided; an
    empty ``token`` returns the unauthenticated URL. We never log the token
    (spec 07 security fix).
    """
    base = build_clone_url(owner, name)
    if not token:
        return base
    return f"https://x-access-token:{token}@github.com/{owner}/{name}.git"


__all__ = [
    "RepoRef",
    "build_authenticated_clone_url",
    "build_clone_url",
    "is_github_url",
    "parse_repo_url",
]
