"""Component tests for repo_update notification template rendering (spec 10).

Renders the three repo_update channel templates (plain_text / html / card_json)
with a mixed ``repo_statuses`` dict (15 success + 2 failed + 1 skipped = 18
total) and asserts that each template aggregates the failed / success / skipped
counts correctly and lists the failed repo names where applicable.

The templates are rendered directly via the project's Jinja2 environment factory
(no Dispatcher / DB / config) — this isolates the rendering contract from the
rest of the notification pipeline.
"""

from __future__ import annotations

import json

import pytest

from progress.cli.notifications.status import status_color, status_icon, status_label
from progress.utils.i18n import gettext as _, ngettext, npgettext, pgettext
from progress.utils.templating import create_environment

_TEMPLATE_DIRS = [
    "src/progress/cli/notifications/templates",
    "src/progress/integrations/changelog/templates/notifications",
    "src/progress/integrations/feed/templates/notifications",
    "src/progress/integrations/proposal/templates/notifications",
    "src/progress/integrations/repo/templates/notifications",
]

_FAILED_REPOS = ["r_f1", "r_f2"]
_SKIPPED_REPOS = ["r_s1"]


@pytest.fixture(scope="module")
def env():
    env = create_environment(_TEMPLATE_DIRS, autoescape=False)
    env.globals.update({"_": _, "ngettext": ngettext, "npgettext": npgettext, "pgettext": pgettext})  # type: ignore
    # Mirror JinjaRenderer._get_env: templates resolve status color/icon/label
    # from the single source (spec 10).

    env.globals.update({"status_color": status_color, "status_icon": status_icon, "status_label": status_label})  # type: ignore
    return env


@pytest.fixture
def repo_statuses() -> dict[str, str]:
    return {
        **{f"r{i}": "success" for i in range(1, 16)},
        "r_f1": "failed",
        "r_f2": "failed",
        "r_s1": "skipped",
    }


def _render(env, template_name: str, repo_statuses: dict[str, str], **overrides) -> str:
    context: dict[str, object] = {
        "title": "Progress Report",
        "summary": "18 repos updated",
        "markpost_url": "https://markpost.example/r/1",
        "repo_statuses": repo_statuses,
        "total_commits": 42,
    }
    context.update(overrides)
    return env.get_template(template_name).render(**context)


def test_plain_text_renders_failed_count(env, repo_statuses: dict[str, str]) -> None:
    text = _render(env, "repo_update/plain_text.j2", repo_statuses)

    assert "❌ 2" in text
    assert "➖ 1" in text
    assert "✅ 15" in text
    assert "18" in text


def test_html_renders_failed_repos(env, repo_statuses: dict[str, str]) -> None:
    html = _render(env, "repo_update/html.j2", repo_statuses)

    assert "Failed Repositories" in html
    for name in _FAILED_REPOS:
        assert name in html
    assert "Skipped Repositories" in html
    for name in _SKIPPED_REPOS:
        assert name in html

    # failure state → red header + FAILED badge in the header
    assert "background-color:#F53F3F" in html
    assert "FAILED" in html
    # failed count appears in the stat tile (red-tinted) and the section heading
    assert f"Failed Repositories ({len(_FAILED_REPOS)})" in html


def test_card_json_renders_failed_count(env, repo_statuses: dict[str, str]) -> None:
    rendered = _render(env, "repo_update/card_json.j2", repo_statuses)
    card = json.loads(rendered)

    assert card["schema"] == "2.0"
    # failed state → red header
    assert card["header"]["template"] == "red"
    assert card["header"]["title"]["content"] == "Progress Report"
    assert card["card_link"] == {"url": "https://markpost.example/r/1"}

    elements = card["body"]["elements"]
    # the stat grid is a column_set with 3 tiles (Total / Commits / Failed)
    grid = next(e for e in elements if e["tag"] == "column_set")
    assert len(grid["columns"]) == 3
    # the failed tile is red-tinted with the failed count (2)
    failed_tile = grid["columns"][2]
    assert failed_tile["background_style"] == "red-50"
    failed_value_md = failed_tile["elements"][1]["content"]
    assert "2" in failed_value_md

    # failed repos appear in column_set rows under the "Failed Repositories" heading
    failed_rows = [e for e in elements if e["tag"] == "column_set" and e.get("background_style") == "red-50"]
    failed_md = " ".join(
        el["content"]
        for row in failed_rows
        for col in row["columns"]
        for el in col["elements"]
        if el["tag"] == "markdown"
    )
    for name in _FAILED_REPOS:
        assert name in failed_md

    # skipped repos are folded into a collapsible_panel
    skipped_panel = next(e for e in elements if e["tag"] == "collapsible_panel")
    skipped_md = skipped_panel["elements"][0]["content"]
    for name in _SKIPPED_REPOS:
        assert name in skipped_md
