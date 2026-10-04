"""Plugin installation & loading (PRFC 2026-08-31 phase 4d, L3).

Third-party plugins are installed out-of-process into
``<state_home>/plugins`` with ``uv pip install --target ... --no-deps`` —
plugins must not declare ``progress`` as a dependency (progress is not on
PyPI; the host provides the kernel: the shared-cordis guarantee). The
directory is appended to ``sys.path`` (tail, so the host always wins) which
makes the installed ``dist-info`` discoverable through the standard
entry_points machinery; after installation, activation is just a
recomposition (L1).
"""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
import sys

logger = logging.getLogger(__name__)

PLUGIN_DIR_NAME = "plugins"


def plugins_dir(state_home: str) -> Path:
    return Path(state_home) / PLUGIN_DIR_NAME


def ensure_plugin_path(state_home: str) -> Path:
    """Append the plugin directory to ``sys.path`` (idempotent, tail position)."""
    directory = plugins_dir(state_home)
    if not directory.exists():
        return directory
    resolved = str(directory.resolve())
    if resolved not in sys.path:
        sys.path.append(resolved)
    return directory


def install_plugin(state_home: str, requirement: str) -> str:
    """Install a plugin package into the state home via ``uv`` (no deps)."""
    directory = plugins_dir(state_home)
    directory.mkdir(parents=True, exist_ok=True)
    command = [
        "uv",
        "pip",
        "install",
        "--python",
        sys.executable,
        "--target",
        str(directory),
        "--no-deps",
        requirement,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"uv plugin install failed for {requirement!r}:\n{result.stderr or result.stdout}")
    logger.info("plugin installed: %s -> %s", requirement, directory)
    return result.stdout.strip()


def list_plugins(state_home: str) -> list[dict[str, str]]:
    """List installed plugin distributions with their entry-point names."""

    directory = plugins_dir(state_home)
    found: list[dict[str, str]] = []
    if not directory.exists():
        return found
    for dist_info in sorted(directory.glob("*.dist-info")):
        stem = dist_info.name[: -len(".dist-info")]
        name, _, version = stem.rpartition("-")
        name = name.replace("_", "-")
        entry_points = []
        metadata_path = dist_info / "entry_points.txt"
        if metadata_path.exists():
            for line in metadata_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()  # noqa: PLW2901
                if line and not line.startswith("[") and "=" in line:
                    entry_points.append(line.split("=", 1)[0].strip())
        found.append({"name": name, "version": version, "entry_points": ",".join(entry_points)})
    return found


def remove_plugin(state_home: str, name: str) -> bool:
    """Remove an installed plugin distribution directory tree."""
    directory = plugins_dir(state_home)
    removed = False
    for dist_info in directory.glob("*.dist-info"):
        installed_name = dist_info.name[: -len(".dist-info")].rpartition("-")[0]
        if installed_name.replace("-", "_").lower() != name.replace("-", "_").lower():
            continue
        record = dist_info / "RECORD"
        if record.exists():
            for line in record.read_text(encoding="utf-8").splitlines():
                relative = line.split(",", 1)[0].strip()
                if not relative or relative.startswith(".."):
                    continue
                target = directory / relative
                if target.is_file():
                    target.unlink(missing_ok=True)
        dist_info_dir = Path(dist_info)
        import shutil  # noqa: PLC0415

        shutil.rmtree(dist_info_dir, ignore_errors=True)
        removed = True
    return removed


__all__ = ["PLUGIN_DIR_NAME", "ensure_plugin_path", "install_plugin", "list_plugins", "plugins_dir", "remove_plugin"]
