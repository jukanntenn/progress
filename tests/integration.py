#!/usr/bin/env python3
"""Standalone integration test for Progress using real GitHub repositories."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
import shutil


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))


class TestAssertionError(Exception):
    pass


class TestConsole:
    GREEN = "\033[92m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    YELLOW = "\033[93m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @staticmethod
    def success(msg: str) -> None:
        print(f"{TestConsole.GREEN}✓ {msg}{TestConsole.RESET}")

    @staticmethod
    def error(msg: str) -> None:
        print(f"{TestConsole.RED}✗ {msg}{TestConsole.RESET}", file=sys.stderr)

    @staticmethod
    def info(msg: str) -> None:
        print(f"{TestConsole.BLUE}{msg}{TestConsole.RESET}")

    @staticmethod
    def step(n: int, total: int, msg: str) -> None:
        print(f"{TestConsole.BOLD}[{n}/{total}]{TestConsole.RESET} {msg}")

    @staticmethod
    def header(title: str) -> None:
        print(f"\n{TestConsole.BOLD}{TestConsole.BLUE}{'=' * 60}{TestConsole.RESET}")
        print(f"{TestConsole.BOLD}{TestConsole.BLUE}{title.center(60)}{TestConsole.RESET}")
        print(f"{TestConsole.BOLD}{TestConsole.BLUE}{'=' * 60}{TestConsole.RESET}\n")


class GitHubCLI:
    def __init__(self) -> None:
        self.user = self.get_user()

    def _run(self, args: list[str], check: bool = True, env: dict[str, str] | None = None) -> str:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if check and result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            raise RuntimeError(
                f"gh {' '.join(args)} failed (code={result.returncode})"
                + (f"\nstdout:\n{stdout}" if stdout else "")
                + (f"\nstderr:\n{stderr}" if stderr else "")
            )
        return result.stdout.strip()

    def get_user(self) -> str:
        return self._run(["api", "/user", "--jq", ".login"])

    def get_token(self) -> str:
        env_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if env_token:
            return env_token
        token = self._run(["auth", "token"], check=True)
        if not token:
            raise RuntimeError("Unable to obtain GitHub token from gh auth token")
        return token

    def create_repo(self, owner: str, name: str, description: str = "", private: bool = False) -> str:
        args = ["repo", "create", f"{owner}/{name}", "--description", description, "--confirm"]
        args.append("--private" if private else "--public")
        return self._run(args)

    def delete_repo(self, owner: str, name: str) -> None:
        self._run(["repo", "delete", f"{owner}/{name}", "--yes"], check=False)

    def create_release(self, owner: str, repo: str, tag: str, title: str, notes: str = "") -> None:
        self._run(
            [
                "release",
                "create",
                tag,
                "--repo",
                f"{owner}/{repo}",
                "--title",
                title,
                "--notes",
                notes,
            ]
        )

    def add_commit(self, owner: str, repo: str, files: dict[str, str], message: str) -> None:
        with tempfile.TemporaryDirectory(prefix="progress-integration-") as tmpdir:
            repo_path = Path(tmpdir) / repo
            subprocess.run(
                ["gh", "repo", "clone", f"{owner}/{repo}", str(repo_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(["git", "checkout", "-B", "main"], cwd=repo_path, check=False)

            for rel_path, content in files.items():
                full_path = repo_path / rel_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")

            subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=progress-integration",
                    "-c",
                    "user.email=progress-integration@example.invalid",
                    "commit",
                    "-m",
                    message,
                ],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
            )
            push = subprocess.run(
                ["git", "push"],
                cwd=repo_path,
                check=False,
                capture_output=True,
                text=True,
            )
            if push.returncode != 0:
                subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo_path, check=True)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise TestAssertionError(message)


@dataclass(frozen=True)
class CreatedRepo:
    owner: str
    name: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def https_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}.git"

    @property
    def raw_changelog_url(self) -> str:
        return f"https://raw.githubusercontent.com/{self.owner}/{self.name}/main/CHANGELOG.md"


class IntegrationTest:
    def __init__(self, *, prefix: str, keep_repos: bool, keep_artifacts: bool) -> None:
        self.console = TestConsole()
        self.gh = GitHubCLI()
        self.owner = self.gh.user
        self.prefix = prefix
        self.keep_repos = keep_repos
        self.keep_artifacts = keep_artifacts
        self.created_repos: list[CreatedRepo] = []

        run_id = f"{int(time.time())}"
        self.base_dir = ROOT_DIR / "data" / "integration" / f"{self.prefix}-{run_id}"
        self.workspace_dir = self.base_dir / "repos"
        self.database_path = self.base_dir / "progress.db"
        self.config_path = self.base_dir / "config.toml"

    def cleanup_environment(self) -> None:
        if self.base_dir.exists() and not self.keep_artifacts:
            shutil.rmtree(self.base_dir, ignore_errors=True)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def _unique_name(self, suffix: str) -> str:
        return f"{self.prefix}-{suffix}-{int(time.time())}"

    def create_initial_repos(self) -> tuple[CreatedRepo, CreatedRepo]:
        repo_main = CreatedRepo(self.owner, self._unique_name("main"))
        repo_proposals = CreatedRepo(self.owner, self._unique_name("proposals"))

        self.console.info(f"Creating {repo_main.slug}...")
        self.gh.create_repo(self.owner, repo_main.name, description="Progress integration test repo")
        self.created_repos.append(repo_main)

        self.gh.add_commit(
            self.owner,
            repo_main.name,
            {
                "README.md": f"# {repo_main.slug}\n\nIntegration test repository.",
                "CHANGELOG.md": "# Changelog\n\n## [0.1.0] - 2025-01-01\n\nInitial release\n",
                "src/app.py": "print('hello')\n",
            },
            "Initial commit",
        )
        self.gh.create_release(self.owner, repo_main.name, "v0.1.0", "v0.1.0", notes="Initial release")

        self.console.info(f"Creating {repo_proposals.slug}...")
        self.gh.create_repo(
            self.owner,
            repo_proposals.name,
            description="Progress integration proposals test repo",
        )
        self.created_repos.append(repo_proposals)

        pep1 = (
            ":PEP: 1\n"
            ":Title: Integration Test PEP\n"
            ":Author: Progress Bot\n"
            ":Status: Draft\n"
            ":Type: Standards Track\n"
            ":Created: 2025-01-01\n"
            "\n"
            "Integration test proposal content.\n"
        )
        pep2 = (
            ":PEP: 2\n"
            ":Title: Another Integration Test PEP\n"
            ":Author: Progress Bot\n"
            ":Status: Draft\n"
            ":Type: Standards Track\n"
            ":Created: 2025-01-01\n"
            "\n"
            "Another proposal.\n"
        )
        self.gh.add_commit(
            self.owner,
            repo_proposals.name,
            {
                "README.md": f"# {repo_proposals.slug}\n\nIntegration test proposals repository.",
                "peps/pep-0001.rst": pep1,
                "peps/pep-0002.rst": pep2,
            },
            "Add initial PEPs",
        )

        return repo_main, repo_proposals

    def write_config(self, *, repos: list[CreatedRepo], proposals_repo: CreatedRepo, changelog_repo: CreatedRepo) -> None:
        repos_lines = "\n".join(
            [
                "\n".join(
                    [
                        "[[repos]]",
                        f'url = "{r.slug}"',
                        'branch = "main"',
                        "enabled = true",
                        "",
                    ]
                )
                for r in repos
            ]
        ).rstrip()

        content = "\n".join(
            [
                'language = "en"',
                'timezone = "UTC"',
                f'database_path = "{self.database_path.as_posix()}"',
                f'workspace_dir = "{self.workspace_dir.as_posix()}"',
                "",
                "[markpost]",
                "enabled = false",
                "timeout = 5",
                "max_batch_size = 1048576",
                "",
                "[notification]",
                "enabled = false",
                "",
                "[github]",
                'protocol = "https"',
                "git_timeout = 600",
                "gh_timeout = 300",
                "",
                "[analysis]",
                "max_diff_length = 200000",
                "concurrency = 1",
                'language = "en"',
                "timeout = 60",
                "",
                repos_lines,
                "",
                "[[owners]]",
                'type = "user"',
                f'name = "{self.owner}"',
                "enabled = true",
                "",
                "[[proposal_trackers]]",
                'type = "pep"',
                f'repo_url = "{proposals_repo.https_url}"',
                'branch = "main"',
                "enabled = true",
                'proposal_dir = "peps"',
                'file_pattern = "pep-*.rst"',
                "",
                "[[changelog_trackers]]",
                f'name = "{changelog_repo.slug}"',
                f'url = "{changelog_repo.raw_changelog_url}"',
                'parser_type = "markdown_heading"',
                "enabled = true",
                "",
            ]
        ).rstrip() + "\n"

        self.config_path.write_text(content, encoding="utf-8")

    def run_progress(self) -> None:
        token = self.gh.get_token()
        env = os.environ.copy()
        env["PROGRESS_GITHUB__GH_TOKEN"] = token
        env["PROGRESS_NOTIFICATION__ENABLED"] = "false"
        env["PROGRESS_MARKPOST__ENABLED"] = "false"

        result = subprocess.run(
            ["uv", "run", "progress", "-c", str(self.config_path)],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            raise TestAssertionError(
                "Progress execution failed"
                + (f"\nstdout:\n{result.stdout.strip()}" if result.stdout else "")
                + (f"\nstderr:\n{result.stderr.strip()}" if result.stderr else "")
            )

    def verify_database(self, *, expected_repo_count: int, min_reports: int, min_discovered: int, min_events: int) -> None:
        from progress.db import close_db, create_tables, init_db
        from progress.models import DiscoveredRepository, ProposalEvent, Report, Repository

        init_db(str(self.database_path))
        create_tables()

        try:
            repo_count = Repository.select().count()
            report_count = Report.select().count()
            discovered_count = DiscoveredRepository.select().count()
            event_count = ProposalEvent.select().count()

            _assert(repo_count == expected_repo_count, f"Repository count expected {expected_repo_count}, got {repo_count}")
            _assert(report_count >= min_reports, f"Report count expected >= {min_reports}, got {report_count}")
            _assert(discovered_count >= min_discovered, f"DiscoveredRepository count expected >= {min_discovered}, got {discovered_count}")
            _assert(event_count >= min_events, f"ProposalEvent count expected >= {min_events}, got {event_count}")

            latest_aggregated = (
                Report.select().where(Report.repo.is_null(True)).order_by(Report.created_at.desc()).first()
            )
            _assert(latest_aggregated is not None, "Aggregated report not found in database")
            _assert(
                latest_aggregated.content is not None and latest_aggregated.content.strip() != "",
                "Aggregated report content is empty",
            )
        finally:
            close_db()

    def evolve_repos(self, repo_main: CreatedRepo, repo_proposals: CreatedRepo) -> CreatedRepo:
        self.gh.add_commit(
            repo_main.owner,
            repo_main.name,
            {
                "src/app.py": "print('hello v2')\n",
                "CHANGELOG.md": (
                    "# Changelog\n\n"
                    "## [0.2.0] - 2025-01-02\n\n"
                    "### Added\n"
                    "- New feature\n\n"
                    "## [0.1.0] - 2025-01-01\n\n"
                    "Initial release\n"
                ),
            },
            "Add feature and bump changelog",
        )
        self.gh.create_release(repo_main.owner, repo_main.name, "v0.2.0", "v0.2.0", notes="New feature release")

        pep1_updated = (
            ":PEP: 1\n"
            ":Title: Integration Test PEP\n"
            ":Author: Progress Bot\n"
            ":Status: Accepted\n"
            ":Type: Standards Track\n"
            ":Created: 2025-01-01\n"
            "\n"
            "Integration test proposal content.\n"
        )
        pep3 = (
            ":PEP: 3\n"
            ":Title: New Integration Test PEP\n"
            ":Author: Progress Bot\n"
            ":Status: Draft\n"
            ":Type: Standards Track\n"
            ":Created: 2025-01-02\n"
            "\n"
            "Newly added proposal.\n"
        )
        self.gh.add_commit(
            repo_proposals.owner,
            repo_proposals.name,
            {
                "peps/pep-0001.rst": pep1_updated,
                "peps/pep-0003.rst": pep3,
            },
            "Update PEP 1 status and add PEP 3",
        )

        repo_new = CreatedRepo(self.owner, self._unique_name("extra"))
        self.console.info(f"Creating {repo_new.slug}...")
        self.gh.create_repo(self.owner, repo_new.name, description="Additional repo for second run")
        self.created_repos.append(repo_new)
        self.gh.add_commit(
            self.owner,
            repo_new.name,
            {"README.md": f"# {repo_new.slug}\n\nCreated for second run."},
            "Initial commit",
        )
        return repo_new

    def cleanup_repos(self) -> None:
        for r in reversed(self.created_repos):
            self.console.info(f"Deleting {r.slug}...")
            self.gh.delete_repo(r.owner, r.name)

    def run(self) -> int:
        self.console.header("Progress Integration Test")
        try:
            self.console.step(1, 7, "Preparing environment")
            self.cleanup_environment()

            self.console.step(2, 7, "Creating initial GitHub repositories")
            repo_main, repo_proposals = self.create_initial_repos()

            self.console.step(3, 7, "Writing Progress config")
            self.write_config(
                repos=[repo_main, repo_proposals],
                proposals_repo=repo_proposals,
                changelog_repo=repo_main,
            )

            self.console.step(4, 7, "Running Progress (first run)")
            self.run_progress()

            self.console.step(5, 7, "Verifying database (first run)")
            self.verify_database(expected_repo_count=2, min_reports=2, min_discovered=1, min_events=0)

            self.console.step(6, 7, "Evolving repositories and updating config")
            repo_new = self.evolve_repos(repo_main, repo_proposals)
            self.write_config(
                repos=[repo_main, repo_proposals, repo_new],
                proposals_repo=repo_proposals,
                changelog_repo=repo_main,
            )

            self.console.step(7, 7, "Running Progress and verifying database (second run)")
            self.run_progress()
            self.verify_database(expected_repo_count=3, min_reports=4, min_discovered=2, min_events=1)

            self.console.success("All integration checks passed")
            return 0
        except TestAssertionError as e:
            self.console.error(str(e))
            if self.keep_artifacts:
                self.console.info(f"Artifacts kept at: {self.base_dir}")
            return 1
        finally:
            if not self.keep_repos:
                try:
                    self.cleanup_repos()
                except Exception as e:
                    self.console.error(f"Repository cleanup failed: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Progress standalone integration test")
    parser.add_argument("--prefix", default="progress-it", help="Repository name prefix")
    parser.add_argument("--keep-repos", action="store_true", help="Do not delete created GitHub repos")
    parser.add_argument("--keep-artifacts", action="store_true", help="Keep local database/workspace")
    args = parser.parse_args()

    test = IntegrationTest(prefix=args.prefix, keep_repos=args.keep_repos, keep_artifacts=args.keep_artifacts)
    return test.run()


if __name__ == "__main__":
    raise SystemExit(main())
