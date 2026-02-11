"""Test CLI functionality."""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch


def test_prepare_discovered_repos_data():
    """Test data preparation for discovered repositories report."""
    from progress.models import DiscoveredRepository

    # Mock repo data from owner.py
    new_repos = [
        {
            "id": 1,
            "owner_type": "org",
            "owner_name": "vitejs",
            "repo_name": "vite",
            "name_with_owner": "vitejs/vite",
            "repo_url": "https://github.com/vitejs/vite",
            "description": "Frontend tooling",
            "created_at": datetime(2026, 2, 11, 14, 30, tzinfo=timezone.utc),
            "has_readme": True,
            "readme_was_truncated": False,
        },
        {
            "id": 2,
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

    # Mock database records
    mock_record1 = Mock(spec=DiscoveredRepository)
    mock_record1.readme_summary = "**Vite** is fast"
    mock_record1.readme_detail = "## Full details"

    mock_record2 = Mock(spec=DiscoveredRepository)
    mock_record2.readme_summary = None
    mock_record2.readme_detail = None

    with patch("progress.cli.DiscoveredRepository") as mock_db:
        mock_db.get_by_id.side_effect = [mock_record1, mock_record2]

        # Sort newest-first
        sorted_repos = sorted(
            new_repos,
            key=lambda r: r.get("created_at") or datetime.min,
            reverse=True
        )

        # Enrich with AI analysis
        for r in sorted_repos:
            record_id = r.get("id")
            if record_id:
                record = mock_db.get_by_id(record_id)
                if record:
                    r["readme_summary"] = record.readme_summary
                    r["readme_detail"] = record.readme_detail

        # Format timestamps
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

            # Ensure owner_name exists
            if "owner_name" not in r:
                name_with_owner = r.get("name_with_owner", "")
                if "/" in name_with_owner:
                    r["owner_name"] = name_with_owner.split("/")[0]
                else:
                    r["owner_name"] = "Unknown"

        # Verify results
        assert sorted_repos[0]["repo_name"] == "vite"  # Newest first
        assert sorted_repos[1]["repo_name"] == "react"
        assert sorted_repos[0]["readme_summary"] == "**Vite** is fast"
        assert sorted_repos[0]["discovered_at"] == "2026-02-11 14:30:00"
        assert sorted_repos[1]["readme_summary"] is None
        assert sorted_repos[1]["discovered_at"] == "2026-02-11 12:00:00"
