"""Tests for the central template engine module."""

from __future__ import annotations

from progress import templates
from progress.templates import (
    get_environment,
    render,
    render_string,
)


def test_get_environment_is_singleton():
    env_a = get_environment()
    env_b = get_environment()
    assert env_a is env_b


def test_environment_has_shared_globals_and_filters():
    env = get_environment()

    assert "_" in env.globals

    assert env.filters["escape_html"] is templates._escape_html
    assert env.filters["basename"] is templates._basename


def test_render_loads_template_by_name():
    output = render_string("Hello {{ name }}!", name="Progress")
    assert output == "Hello Progress!"


def test_render_string_inline_template():
    output = render_string("{{ 1 + 2 }}")
    assert output == "3"


def test_escape_html_filter_via_render_string():
    output = render_string("{{ value | escape_html }}", value="<script>x</script>")
    assert output == "&lt;script&gt;x&lt;/script&gt;"


def test_basename_filter_via_render_string():
    output = render_string("{{ path | basename }}", path="a/b/c.md")
    assert output == "c.md"


def test_translation_global_available_in_template():
    output = render_string('{{ _("Diff truncated") }}')
    assert "Diff truncated" in output


def test_missing_dict_attr_is_falsy_in_conditional():
    output = render_string(
        "{% if data.missing %}yes{% else %}no{% endif %}", data={}
    )
    assert output == "no"


def test_missing_top_level_var_renders_empty():
    output = render_string("[{{ missing }}]")
    assert output == "[]"


def test_render_real_repository_report_template():
    from progress.contrib.repo.repository import RepositoryReport

    report = RepositoryReport(
        repo_name="test/repo",
        repo_slug="test-repo",
        repo_web_url="https://github.com/test/repo",
        branch="main",
        commit_count=1,
        current_commit="abc",
        previous_commit="def",
        commit_messages=["feat: x"],
        analysis_summary="Summary",
        analysis_detail="Detail",
        truncated=False,
        original_diff_length=10,
        analyzed_diff_length=10,
    )

    output = render(
        "repository_report.j2",
        report=report,
    )

    assert "test/repo" in output
    assert "feat: x" in output
