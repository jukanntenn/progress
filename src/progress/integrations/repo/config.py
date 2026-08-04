"""Pydantic config schema for the ``repo`` integration (spec 02 / spec repo §3).

This model is the JSON Schema source for ``section="repo"`` in the ``config``
table. Per spec 02, repo plugin config is::

    [[repos]]
    url = "vitejs/vite"
    branch = "main"
    enabled = true
    protocol = "https"           # "https" | "ssh"; per-repo override

    [[owners]]
    type = "organization"        # "organization" | "user"
    name = "bytedance"
    enabled = true

    first_run_lookback_commits = 3
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SHORTHAND_RE = re.compile(r"^[\w-]+/[\w.\-]+$")
_HTTPS_RE = re.compile(r"^https?://", re.IGNORECASE)
_SSH_RE = re.compile(r"^git@[\w.\-]+:[\w-]+/[\w.\-]+\.?git?$")


class RepoItemConfig(BaseModel):
    """Single tracked repository (spec repo §3)."""

    model_config = ConfigDict(extra="forbid")
    url: str
    branch: str = "main"
    enabled: bool = True
    track_commits: bool = True
    track_releases: bool = True
    protocol: Literal["https", "ssh"] = "https"

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("repo url must not be empty")
        if not (_SHORTHAND_RE.match(v) or _HTTPS_RE.match(v) or _SSH_RE.match(v)):
            raise ValueError("repo url must be 'owner/repo', an HTTPS URL, or 'git@host:owner/repo.git'")
        return v


class OwnerItemConfig(BaseModel):
    """Monitored GitHub owner (organization or user) — spec repo §3.

    The TOML key is ``type`` (per spec).
    """

    model_config = ConfigDict(extra="forbid")
    type: Literal["organization", "user"]
    name: str
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("owner name must not be empty")
        return v


class RepoIntegrationConfig(BaseModel):
    """Top-level config for the ``repo`` integration."""

    model_config = ConfigDict(extra="forbid")
    repos: list[RepoItemConfig] = Field(default_factory=list)
    owners: list[OwnerItemConfig] = Field(default_factory=list)
    first_run_lookback_commits: int = Field(default=3, ge=1)
    max_incremental_lookback_releases: int = Field(default=3, ge=1)


def normalize_repo_url(url: str) -> str:
    """Normalize a repo URL to its canonical GitHub HTTPS form (spec repo §2).

    Accepts ``owner/repo``, ``https://github.com/owner/repo[.git]``, or SSH
    ``git@github.com:owner/repo.git``. Always returns the canonical
    ``https://github.com/owner/repo.git`` form (the upsert/GC/dedup key).
    """
    url = (url or "").strip()
    if not url:
        return url
    if _HTTPS_RE.match(url):
        cleaned = url
        cleaned = cleaned.removesuffix(".git")
        return f"{cleaned}.git"
    if _SSH_RE.match(url):
        host_idx = url.index(":")
        path = url[host_idx + 1 :]
        path = path.removesuffix(".git")
        return f"https://github.com/{path}.git"
    if _SHORTHAND_RE.match(url):
        return f"https://github.com/{url}.git"
    return url


def derive_repo_name(url: str) -> str:
    """Derive ``owner/repo`` from any supported URL form (spec repo §2)."""
    normalized = normalize_repo_url(url)
    if normalized.startswith("https://github.com/"):
        path = normalized[len("https://github.com/") :]
        return path.removesuffix(".git")
    return url.rsplit("/", 1)[-1] if "/" in url else url


__all__ = [
    "OwnerItemConfig",
    "RepoIntegrationConfig",
    "RepoItemConfig",
    "derive_repo_name",
    "normalize_repo_url",
]
