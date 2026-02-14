#!/usr/bin/env python3
"""Standalone integration test for Progress using real GitHub repositories."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

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
        print(
            f"{TestConsole.BOLD}{TestConsole.BLUE}{title.center(60)}{TestConsole.RESET}"
        )
        print(f"{TestConsole.BOLD}{TestConsole.BLUE}{'=' * 60}{TestConsole.RESET}\n")


class GitHubCLI:
    def __init__(self, gh_token: str) -> None:
        self.gh_token = gh_token
        self.user = self.get_user()

    def repo_exists(self, owner: str, name: str) -> bool:
        env = os.environ.copy()
        env["GH_TOKEN"] = self.gh_token
        result = subprocess.run(
            ["gh", "repo", "view", f"{owner}/{name}"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        return result.returncode == 0

    def _run(self, args: list[str], check: bool = True) -> str:
        env = os.environ.copy()
        env["GH_TOKEN"] = self.gh_token
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

    def create_repo(
        self, owner: str, name: str, description: str = "", private: bool = False
    ) -> str:
        args = [
            "repo",
            "create",
            f"{owner}/{name}",
            "--description",
            description,
            "--confirm",
        ]
        args.append("--private" if private else "--public")

        return self._run(args)

    def delete_repo(self, owner: str, name: str) -> None:
        self._run(["repo", "delete", f"{owner}/{name}", "--yes"], check=False)

    def create_release(
        self, owner: str, repo: str, tag: str, title: str, notes: str = ""
    ) -> None:
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

    def add_commit(
        self, owner: str, repo: str, files: dict[str, str], message: str
    ) -> None:
        testing_root = ROOT_DIR / "data" / "testing-repos"
        testing_root.mkdir(parents=True, exist_ok=True)
        repo_path = testing_root / repo
        if repo_path.exists():
            shutil.rmtree(repo_path, ignore_errors=True)

        ssh_key = Path.home() / ".ssh" / "id_wsl"
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key} -o IdentitiesOnly=yes"

        clone_result = subprocess.run(
            ["git", "clone", f"git@github.com:{owner}/{repo}.git", str(repo_path)],
            capture_output=True,
            text=True,
            env=env,
        )
        if clone_result.returncode != 0:
            repo_path.mkdir(parents=True)
            subprocess.run(
                ["git", "init"], cwd=repo_path, check=True, capture_output=True
            )
            subprocess.run(
                [
                    "git",
                    "remote",
                    "add",
                    "origin",
                    f"git@github.com:{owner}/{repo}.git",
                ],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

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
            env=env,
        )
        if push.returncode != 0:
            subprocess.run(
                ["git", "push", "-u", "origin", "main"],
                cwd=repo_path,
                check=True,
                env=env,
            )


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
    def __init__(self) -> None:
        from progress.config import Config

        self.console = TestConsole()
        self.config_path = ROOT_DIR / "config" / "test_integration.toml"
        config = Config.load_from_file(str(self.config_path))
        self.gh_token = config.github.gh_token
        self.gh = GitHubCLI(self.gh_token)
        self.owner = self.gh.user
        self.testing_repo_name = "progress-testing"
        self.proposals_repo_name = "progress-proposals"
        self.new_repo_name = "progress-testing-new"
        self.created_repos: list[CreatedRepo] = []
        self.database_path = ROOT_DIR / "data" / "progress.db"
        self.reports_dir = ROOT_DIR / "data" / "reports"
        self.testing_repos_dir = ROOT_DIR / "data" / "testing-repos"

    def cleanup_environment(self) -> None:
        if self.database_path.exists():
            self.database_path.unlink()
        if self.reports_dir.exists():
            shutil.rmtree(self.reports_dir, ignore_errors=True)
        if self.testing_repos_dir.exists():
            shutil.rmtree(self.testing_repos_dir, ignore_errors=True)

    def get_latest_report(self, directory: Path) -> Path | None:
        if not directory.exists():
            return None
        files = list(directory.glob("*.md"))
        if not files:
            return None
        return max(files, key=lambda f: int(f.stem))

    def verify_repo_update_report(self, repo: CreatedRepo) -> None:
        report = self.get_latest_report(self.reports_dir / "repo" / "update")
        _assert(report is not None, "No repo update report found")
        content = report.read_text(encoding="utf-8")
        _assert(repo.slug in content, f"Repo update report missing {repo.slug}")

    def verify_new_repo_report(self, repo: CreatedRepo) -> None:
        report = self.get_latest_report(self.reports_dir / "repo" / "new")
        _assert(report is not None, "No new repo report found")
        content = report.read_text(encoding="utf-8")
        _assert(repo.slug in content, f"New repo report missing {repo.slug}")

    def verify_proposal_report(self) -> None:
        report = self.get_latest_report(self.reports_dir / "proposal")
        _assert(report is not None, "No proposal report found")
        content = report.read_text(encoding="utf-8")
        _assert("pep" in content.lower(), "Proposal report missing PEP reference")

    def verify_changelog_report(self) -> None:
        report = self.get_latest_report(self.reports_dir / "changelog")
        _assert(report is not None, "No changelog report found")
        content = report.read_text(encoding="utf-8")
        _assert(len(content) > 0, "Changelog report is empty")

    def create_initial_repos(self) -> tuple[CreatedRepo, CreatedRepo]:
        repo_main = CreatedRepo(self.owner, self.testing_repo_name)
        repo_proposals = CreatedRepo(self.owner, self.proposals_repo_name)

        self.console.info(f"Creating {repo_main.slug}...")
        self.gh.create_repo(
            self.owner, repo_main.name, description="Progress integration test repo"
        )
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
        self.gh.create_release(
            self.owner, repo_main.name, "v0.1.0", "v0.1.0", notes="Initial release"
        )

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

    def run_progress(
        self,
        *,
        repos: list[CreatedRepo],
        proposals_repo: CreatedRepo,
        changelog_repo: CreatedRepo,
    ) -> None:
        result = subprocess.run(
            ["uv", "run", "progress", "-c", str(self.config_path)],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise TestAssertionError(
                "Progress execution failed"
                + (f"\nstdout:\n{result.stdout.strip()}" if result.stdout else "")
                + (f"\nstderr:\n{result.stderr.strip()}" if result.stderr else "")
            )

    def verify_database(
        self,
        *,
        expected_repo_count: int,
        min_reports: int,
        min_discovered: int,
        min_events: int,
    ) -> None:
        from progress.contrib.proposal.models import ProposalEvent
        from progress.contrib.repo.models import DiscoveredRepository
        from progress.db import close_db, create_tables, init_db
        from progress.db.models import Report, Repository

        init_db(str(self.database_path))
        create_tables()

        try:
            repo_count = Repository.select().count()
            report_count = Report.select().count()
            discovered_count = DiscoveredRepository.select().count()
            event_count = ProposalEvent.select().count()

            _assert(
                repo_count == expected_repo_count,
                f"Repository count expected {expected_repo_count}, got {repo_count}",
            )
            _assert(
                report_count >= min_reports,
                f"Report count expected >= {min_reports}, got {report_count}",
            )
            _assert(
                discovered_count >= min_discovered,
                f"DiscoveredRepository count expected >= {min_discovered}, got {discovered_count}",
            )
            _assert(
                event_count >= min_events,
                f"ProposalEvent count expected >= {min_events}, got {event_count}",
            )

            latest_aggregated = (
                Report.select()
                .where(Report.repo.is_null(True))
                .order_by(Report.created_at.desc())
                .first()
            )
            _assert(
                latest_aggregated is not None, "Aggregated report not found in database"
            )
            _assert(
                latest_aggregated.content is not None
                and latest_aggregated.content.strip() != "",
                "Aggregated report content is empty",
            )
        finally:
            close_db()

    def evolve_repos(
        self, repo_main: CreatedRepo, repo_proposals: CreatedRepo
    ) -> CreatedRepo:
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
        self.gh.create_release(
            repo_main.owner,
            repo_main.name,
            "v0.2.0",
            "v0.2.0",
            notes="New feature release",
        )

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

        repo_new = CreatedRepo(self.owner, self.new_repo_name)
        self.console.info(f"Creating {repo_new.slug}...")
        self.gh.create_repo(
            self.owner, repo_new.name, description="Additional repo for second run"
        )
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
            self.console.step(1, 6, "Preparing environment")
            self.cleanup_environment()

            self.console.step(2, 6, "Creating initial GitHub repositories")
            repo_main, repo_proposals = self.create_initial_repos()

            self.console.step(3, 6, "Running Progress (first run)")
            self.run_progress(
                repos=[repo_main, repo_proposals],
                proposals_repo=repo_proposals,
                changelog_repo=repo_main,
            )

            self.console.step(4, 6, "Verifying first run results")
            self.verify_database(
                expected_repo_count=2, min_reports=2, min_discovered=1, min_events=0
            )
            self.verify_repo_update_report(repo_main)
            self.verify_proposal_report()
            self.verify_changelog_report()

            self.console.step(5, 6, "Evolving repositories")
            repo_new = self.evolve_repos(repo_main, repo_proposals)

            self.console.step(6, 6, "Running Progress and verifying (second run)")
            self.run_progress(
                repos=[repo_main, repo_proposals, repo_new],
                proposals_repo=repo_proposals,
                changelog_repo=repo_main,
            )
            self.verify_database(
                expected_repo_count=3, min_reports=4, min_discovered=2, min_events=1
            )
            self.verify_repo_update_report(repo_main)
            self.verify_new_repo_report(repo_new)
            self.verify_proposal_report()
            self.verify_changelog_report()

            self.console.success("All integration checks passed")
            return 0
        except TestAssertionError as e:
            self.console.error(str(e))
            return 1
        finally:
            try:
                self.cleanup_repos()
            except Exception as e:
                self.console.error(f"Repository cleanup failed: {e}")


def main() -> int:
    test = IntegrationTest()
    return test.run()


if __name__ == "__main__":
    raise SystemExit(main())
