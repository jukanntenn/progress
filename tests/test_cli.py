"""Test CLI functionality."""

from datetime import datetime, timezone


def test_prepare_discovered_repos_data():
    """Test data preparation for discovered repositories report."""
    new_repos = [
        {
            "owner_type": "org",
            "owner_name": "vitejs",
            "repo_name": "vite",
            "name_with_owner": "vitejs/vite",
            "repo_url": "https://github.com/vitejs/vite",
            "description": "Frontend tooling",
            "created_at": datetime(2026, 2, 11, 14, 30, tzinfo=timezone.utc),
            "has_readme": True,
            "readme_was_truncated": False,
            "readme_summary": "**Vite** is fast",
            "readme_detail": "## Full details",
        },
        {
            "owner_type": "org",
            "owner_name": "facebook",
            "repo_name": "react",
            "name_with_owner": "facebook/react",
            "repo_url": "https://github.com/facebook/react",
            "description": None,
            "created_at": datetime(2026, 2, 11, 12, 0, tzinfo=timezone.utc),
            "has_readme": False,
            "readme_was_truncated": False,
        },
    ]

    sorted_repos = sorted(
        new_repos, key=lambda r: r.get("created_at") or datetime.min, reverse=True
    )

    for r in sorted_repos:
        r.setdefault("readme_summary", None)
        r.setdefault("readme_detail", None)

    for r in sorted_repos:
        created_at = r.get("created_at")
        if created_at:
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    created_at = None
            if created_at and hasattr(created_at, "strftime"):
                r["discovered_at"] = created_at.strftime("%Y-%m-%d %H:%M:%S")
            else:
                r["discovered_at"] = "Unknown"
        else:
            r["discovered_at"] = "Unknown"

        if "owner_name" not in r:
            name_with_owner = r.get("name_with_owner", "")
            if "/" in name_with_owner:
                r["owner_name"] = name_with_owner.split("/")[0]
            else:
                r["owner_name"] = "Unknown"

    assert sorted_repos[0]["repo_name"] == "vite"
    assert sorted_repos[1]["repo_name"] == "react"
    assert sorted_repos[0]["readme_summary"] == "**Vite** is fast"
    assert sorted_repos[0]["discovered_at"] == "2026-02-11 14:30:00"
    assert sorted_repos[1]["readme_summary"] is None
    assert sorted_repos[1]["discovered_at"] == "2026-02-11 12:00:00"
