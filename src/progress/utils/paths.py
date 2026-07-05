"""Path canonicalization helpers."""

from pathlib import Path


def canonicalify(p: Path | str) -> Path:
    return Path(p).expanduser().resolve()


def ensure_path(p: Path | str) -> Path:
    path = canonicalify(p)
    path.mkdir(parents=True, exist_ok=True)
    return path
