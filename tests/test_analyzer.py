"""Analyzer module unit tests"""

from types import SimpleNamespace

from progress.analyzer import ClaudeCodeAnalyzer


def test_generate_title_and_summary_prompt_includes_language_requirement(monkeypatch):
    analyzer = ClaudeCodeAnalyzer(language="zh")

    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout="TITLE: 标题\nSUMMARY: 摘要\n", stderr="")

    monkeypatch.setattr("progress.analyzer.subprocess.run", fake_run)

    title, summary = analyzer.generate_title_and_summary("report")
    assert title == "标题"
    assert summary == "摘要"

    prompt = captured["cmd"][2]
    assert (
        'Language requirement: The user-configured output language is "zh".' in prompt
    )
    assert "Output EXACTLY two lines" in prompt


def test_generate_title_and_summary_uses_fallback_when_missing_fields(monkeypatch):
    analyzer = ClaudeCodeAnalyzer(language="zh")

    def fake_run(cmd, capture_output, text, timeout):
        return SimpleNamespace(stdout="SUMMARY: only summary\n", stderr="")

    monkeypatch.setattr("progress.analyzer.subprocess.run", fake_run)

    title, summary = analyzer.generate_title_and_summary("report")
    assert title == "Progress Report for Open Source Projects"
    assert summary == "only summary"
