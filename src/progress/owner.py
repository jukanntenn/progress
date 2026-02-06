import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .github import gh_api_get_readme, gh_repo_list
from .models import DiscoveredRepository, GitHubOwner

logger = logging.getLogger(__name__)

UTC = ZoneInfo("UTC")
MAX_README_LENGTH = 50000


def _parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class OwnerManager:
    def __init__(self, gh_token: str | None):
        self.gh_token = gh_token
        self.logger = logger

    def sync_owners(self, owner_configs) -> dict:
        desired = {
            (cfg.type, cfg.name): {"enabled": getattr(cfg, "enabled", True)}
            for cfg in owner_configs or []
        }

        created = 0
        updated = 0
        deleted = 0

        existing = {(o.owner_type, o.name): o for o in GitHubOwner.select()}

        for (owner_type, name), cfg_data in desired.items():
            enabled = cfg_data.get("enabled", True)
            if not enabled:
                continue

            existing_owner = existing.get((owner_type, name))

            if not existing_owner:
                GitHubOwner.create(owner_type=owner_type, name=name, enabled=True)
                created += 1
            elif not existing_owner.enabled:
                existing_owner.enabled = True
                existing_owner.save()
                updated += 1

        for key, existing_owner in existing.items():
            if key not in desired or not desired[key].get("enabled", True):
                existing_owner.delete_instance()
                deleted += 1

        return {"created": created, "updated": updated, "deleted": deleted}

    def check_all(self) -> list[dict]:
        new_repos: list[dict] = []
        owners = GitHubOwner.select().where(GitHubOwner.enabled == True)
        for owner in owners:
            new_repos.extend(self._check_owner(owner))
        return new_repos

    def _check_owner(self, owner: GitHubOwner) -> list[dict]:
        try:
            repos = gh_repo_list(str(owner.name), limit=100, source=True, gh_token=self.gh_token)
        except Exception as e:
            self.logger.error(f"Failed to list repositories for {owner.name}: {e}")
            return []

        parsed = []
        for r in repos:
            created_at_dt = _parse_github_datetime(r.get("createdAt"))
            if created_at_dt is None:
                continue
            parsed.append((created_at_dt, r))

        if not parsed:
            return []

        parsed.sort(key=lambda x: x[0])
        newest_created_at, _ = parsed[-1]

        last_tracked = owner.last_tracked_repo
        if isinstance(last_tracked, str):
            last_tracked = datetime.fromisoformat(last_tracked)

        if last_tracked is None:
            candidates = [parsed[-1][1]]
        else:
            candidates = [
                r for created_at, r in parsed
                if created_at > last_tracked
            ]

        if not candidates:
            owner.last_check_time = datetime.now(UTC)
            owner.last_tracked_repo = newest_created_at
            owner.save()
            return []

        results: list[dict] = []
        for r in candidates:
            processed = self._process_new_repo(owner, r)
            if processed:
                results.append(processed)

        owner.last_check_time = datetime.now(UTC)
        owner.last_tracked_repo = newest_created_at
        owner.save()
        return results

    def _process_new_repo(self, owner: GitHubOwner, repo_data: dict) -> dict | None:
        name_with_owner = repo_data.get("nameWithOwner")
        if not name_with_owner or "/" not in name_with_owner:
            return None

        slug_owner, repo_name = name_with_owner.split("/", 1)
        repo_url = f"https://github.com/{slug_owner}/{repo_name}"
        description = repo_data.get("description")
        created_at = _parse_github_datetime(repo_data.get("createdAt"))

        readme_content = None
        has_readme = False
        readme_was_truncated = False

        try:
            readme_content = gh_api_get_readme(slug_owner, repo_name, gh_token=self.gh_token)
            has_readme = readme_content is not None
        except Exception as e:
            self.logger.warning(f"Failed to fetch README for {name_with_owner}: {e}")

        if readme_content and len(readme_content) > MAX_README_LENGTH:
            readme_content = readme_content[:MAX_README_LENGTH]
            readme_was_truncated = True

        defaults = {
            "repo_url": repo_url,
            "description": description,
            "has_readme": has_readme,
            "readme_was_truncated": readme_was_truncated,
            "notified": False,
        }
        record, created = DiscoveredRepository.get_or_create(
            owner=owner,
            repo_name=repo_name,
            defaults=defaults,
        )

        if not created:
            for key, value in defaults.items():
                setattr(record, key, value)
            record.save()

        return {
            "id": record.id,
            "owner_type": owner.owner_type,
            "owner_name": owner.name,
            "repo_name": repo_name,
            "name_with_owner": name_with_owner,
            "repo_url": repo_url,
            "description": description,
            "created_at": created_at,
            "has_readme": has_readme,
            "readme_was_truncated": readme_was_truncated,
            "readme_content": readme_content,
        }
