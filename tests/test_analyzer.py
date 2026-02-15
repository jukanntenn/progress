"""Analyzer module unit tests"""

from progress.ai.analyzers.claude_code import ClaudeCodeAnalyzer


def test_generate_title_and_summary_prompt_includes_language_requirement(monkeypatch):
    analyzer = ClaudeCodeAnalyzer(language="zh")

    captured = {}

    def fake_run(cmd, cwd=None, timeout=None, check=True, input=None, env=None):
        captured["cmd"] = cmd
        captured["input"] = input
        return "TITLE: 标题\nSUMMARY: 摘要\n"

    monkeypatch.setattr("progress.ai.analyzers.claude_code.run_command", fake_run)

    title, summary = analyzer.generate_title_and_summary("report")
    assert title == "标题"
    assert summary == "摘要"

    prompt = captured["input"]
    assert (
        'Language requirement: The user-configured output language is "zh".' in prompt
    )
    assert "Output EXACTLY two lines" in prompt


def test_generate_title_and_summary_uses_fallback_when_missing_fields(monkeypatch):
    analyzer = ClaudeCodeAnalyzer(language="zh")

    def fake_run(cmd, cwd=None, timeout=None, check=True, input=None, env=None):
        return "SUMMARY: only summary\n"

    monkeypatch.setattr("progress.ai.analyzers.claude_code.run_command", fake_run)

    title, summary = analyzer.generate_title_and_summary("report")
    assert title == "Progress Report for Open Source Projects"
    assert summary == "only summary"
