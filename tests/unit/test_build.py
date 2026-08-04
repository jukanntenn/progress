"""Unit tests for docker/build.py registry resolution, platform selection, and image naming."""

from __future__ import annotations

from argparse import Namespace
import subprocess
from unittest.mock import patch

from docker.build import (
    ALL_PLATFORMS,
    _resolve_owner_from_git,
    _resolve_registry,
    detect_host_platform,
    resolve_platforms,
)
import pytest


def _make_args(**kwargs):
    defaults = {"all_platforms": False, "platform": []}
    defaults.update(kwargs)
    return Namespace(**defaults)


class TestResolveRegistry:
    def test_ghcr_alias(self):
        host, needs_owner = _resolve_registry("ghcr")
        assert host == "ghcr.io"
        assert needs_owner is True

    def test_dockerhub_alias(self):
        host, needs_owner = _resolve_registry("dockerhub")
        assert host == "docker.io"
        assert needs_owner is True

    def test_docker_alias(self):
        host, needs_owner = _resolve_registry("docker")
        assert host == "docker.io"
        assert needs_owner is True

    def test_flat_host_with_port(self):
        host, needs_owner = _resolve_registry("192.168.5.50:5000")
        assert host == "192.168.5.50:5000"
        assert needs_owner is False

    def test_flat_host_with_dot(self):
        host, needs_owner = _resolve_registry("ghcr.io")
        assert host == "ghcr.io"
        assert needs_owner is False

    def test_localhost(self):
        host, needs_owner = _resolve_registry("localhost")
        assert host == "localhost"
        assert needs_owner is False

    def test_full_path_with_namespace(self):
        host, needs_owner = _resolve_registry("ghcr.io/jukanntenn")
        assert host == "ghcr.io/jukanntenn"
        assert needs_owner is False

    def test_full_path_with_port_and_namespace(self):
        host, needs_owner = _resolve_registry("registry.local:5000/team")
        assert host == "registry.local:5000/team"
        assert needs_owner is False

    def test_unknown_alias_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            _resolve_registry("myreg")
        assert exc_info.value.code == 2


class TestResolveOwnerFromGit:
    def test_ssh_url(self):
        with patch("subprocess.check_output", return_value="git@github.com:jukanntenn/progress.git\n"):
            owner = _resolve_owner_from_git()
            assert owner == "jukanntenn"

    def test_https_url(self):
        with patch("subprocess.check_output", return_value="https://github.com/jukanntenn/progress.git\n"):
            owner = _resolve_owner_from_git()
            assert owner == "jukanntenn"

    def test_non_github_url_exits(self):
        with patch("subprocess.check_output", return_value="git@gitlab.com:user/repo.git\n"):
            with pytest.raises(SystemExit) as exc_info:
                _resolve_owner_from_git()
            assert exc_info.value.code == 2

    def test_no_remote_exits(self):
        with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
            with pytest.raises(SystemExit) as exc_info:
                _resolve_owner_from_git()
            assert exc_info.value.code == 2


class TestResolvePlatforms:
    def test_default_no_args(self):
        platforms = resolve_platforms(_make_args())
        assert platforms == [detect_host_platform()]

    def test_all_platforms_flag(self):
        platforms = resolve_platforms(_make_args(all_platforms=True))
        assert set(platforms) == set(ALL_PLATFORMS)

    def test_single_platform_alias(self):
        platforms = resolve_platforms(_make_args(platform=["amd64"]))
        assert platforms == ["linux/amd64"]

    def test_multiple_platforms(self):
        platforms = resolve_platforms(_make_args(platform=["amd64", "arm64"]))
        assert set(platforms) == {"linux/amd64", "linux/arm64"}

    def test_full_platform_name(self):
        platforms = resolve_platforms(_make_args(platform=["linux/amd64"]))
        assert platforms == ["linux/amd64"]

    def test_unsupported_platform_exits(self):
        with patch("docker.build.env_error") as mock_env_error:
            mock_env_error.side_effect = SystemExit(2)
            with pytest.raises(SystemExit):
                resolve_platforms(_make_args(platform=["riscv64"]))
            mock_env_error.assert_called_once()


class TestImageNaming:
    def test_private_registry_prefix(self):
        registry, needs_owner = _resolve_registry("192.168.5.50:5000")
        prefix = registry if not needs_owner else f"{registry}/owner"
        assert prefix == "192.168.5.50:5000"

    def test_ghcr_alias_with_owner(self):
        registry, needs_owner = _resolve_registry("ghcr")
        owner = "jukanntenn"
        prefix = registry if not needs_owner else f"{registry}/{owner}"
        assert prefix == "ghcr.io/jukanntenn"

    def test_full_path_passthrough(self):
        registry, needs_owner = _resolve_registry("ghcr.io/jukanntenn")
        prefix = registry if not needs_owner else f"{registry}/owner"
        assert prefix == "ghcr.io/jukanntenn"
