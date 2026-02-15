"""Claude Code analyzer."""

import json
import logging
import re
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from progress.consts import (
    CMD_CLAUDE,
    TEMPLATE_ANALYSIS_PROMPT,
    TEMPLATE_README_ANALYSIS_PROMPT,
    TIMEOUT_CLAUDE_ANALYSIS,
)
from progress.errors import AnalysisException
from progress.i18n import gettext as _
from progress.utils import run_command

logger = logging.getLogger(__name__)


class ClaudeCodeAnalyzer:
    """Claude Code CLI analyzer for code changes."""

    def __init__(
        self,
        max_diff_length: int = 100000,
        timeout: int = TIMEOUT_CLAUDE_ANALYSIS,
        language: str = "zh",
    ):
        self.claude_code_path = CMD_CLAUDE
        self.max_diff_length = max_diff_length
        self.timeout = timeout
        self.language = language
        template_dir = Path(__file__).parent.parent.parent / "templates"
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def analyze_diff(
        self,
        repo_name: str,
        branch: str,
        diff: str,
        commit_messages: list[str],
    ) -> tuple[str, str, bool, int, int]:
        """Analyze code diff and return summary and detail.

        Args:
            repo_name: Repository name
            branch: Branch name
            diff: Code diff content
            commit_messages: List of commit messages

        Returns:
            (summary, detail, truncated, original_diff_length, analyzed_diff_length)
        """
        original_length = len(diff)
        truncated = False

        if original_length > self.max_diff_length:
            truncated = True
            diff = diff[: self.max_diff_length]
            logger.warning(
                f"Repository {repo_name} diff length ({original_length} chars) exceeds "
                f"limit ({self.max_diff_length} chars), truncated to first {self.max_diff_length} chars"
            )

        safe_name = repo_name.replace("/", "_")
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=f"{safe_name}_{branch}_diff.patch",
        ) as temp_file:
            temp_file.write(diff)
            diff_file = Path(temp_file.name)
            logger.debug(f"Created temporary diff file: {diff_file}")

            prompt = self._build_analysis_prompt(
                repo_name,
                branch,
                commit_messages,
                truncated,
                original_length,
                len(diff),
            )
            logger.info(f"Analyzing code changes for {repo_name}...")
            try:
                summary, detail = self._run_claude_analysis(diff, prompt)
            except Exception as e:
                logger.warning(f"Code analysis failed: {e}")
                summary = _("Code analysis unavailable")
                detail = _(
                    "Claude Code analysis failed or timed out. See logs for details."
                )

            return summary, detail, truncated, original_length, len(diff)

    def analyze_releases(
        self,
        repo_name: str,
        branch: str,
        release_data: dict,
    ) -> tuple[str, str]:
        """Analyze GitHub releases and return summary and detail.

        Args:
            repo_name: Repository name
            branch: Branch name
            release_data: Release data dict from repo.check_releases()

        Returns:
            (summary, detail) tuple
        """
        prompt = self._build_release_analysis_prompt(
            repo_name,
            branch,
            release_data,
        )
        logger.info(f"Analyzing releases for {repo_name}...")
        summary, detail = self._run_claude_release_analysis(prompt)
        return summary, detail

    def analyze_readme(
        self,
        repo_name: str,
        description: str | None,
        readme_content: str,
    ) -> tuple[str, str]:
        template = self.jinja_env.get_template(TEMPLATE_README_ANALYSIS_PROMPT)
        prompt = template.render(
            repo_name=repo_name,
            description=description,
            readme_content=readme_content,
            language=self.language,
        )
        logger.info(f"Analyzing README for {repo_name}...")
        return self._run_claude_readme_analysis(prompt)

    def analyze_proposal(
        self,
        proposal_type: str,
        event_type: str,
        proposal_number: int,
        title: str,
        old_status: str | None = None,
        new_status: str | None = None,
        proposal_text: str | None = None,
        diff_text: str | None = None,
    ) -> tuple[str, str]:
        if event_type == "created":
            return self.analyze_new_proposal(
                proposal_type=proposal_type,
                proposal_number=proposal_number,
                title=title,
                proposal_text=proposal_text or "",
            )
        if event_type in {"accepted", "rejected", "withdrawn", "status_changed"}:
            return self.analyze_status_change(
                proposal_type=proposal_type,
                proposal_number=proposal_number,
                title=title,
                event_type=event_type,
                old_status=old_status or "",
                new_status=new_status or "",
                proposal_text=proposal_text or "",
            )
        if event_type == "content_modified":
            return self.analyze_content_modification(
                proposal_type=proposal_type,
                proposal_number=proposal_number,
                title=title,
                diff_text=diff_text or "",
            )
        return ("", "")

    def analyze_new_proposal(
        self,
        proposal_type: str,
        proposal_number: int,
        title: str,
        proposal_text: str,
    ) -> tuple[str, str]:
        template = self.jinja_env.get_template("proposal_new_prompt.j2")
        prompt = template.render(
            proposal_type=proposal_type,
            proposal_number=proposal_number,
            title=title,
            language=self.language,
        )
        try:
            return self._run_claude_text_analysis(prompt, proposal_text)
        except Exception as e:
            logger.warning(f"Proposal analysis failed: {e}")
            return (
                _(f"New proposal: {proposal_type} #{proposal_number}"),
                _(
                    f"Analysis unavailable for {proposal_type} #{proposal_number}: {title}"
                ),
            )

    def analyze_status_change(
        self,
        proposal_type: str,
        proposal_number: int,
        title: str,
        event_type: str,
        old_status: str,
        new_status: str,
        proposal_text: str,
    ) -> tuple[str, str]:
        template_name = "proposal_status_change_prompt.j2"
        if event_type == "accepted":
            template_name = "proposal_accepted_prompt.j2"
        elif event_type == "rejected":
            template_name = "proposal_rejected_prompt.j2"
        elif event_type == "withdrawn":
            template_name = "proposal_withdrawn_prompt.j2"

        template = self.jinja_env.get_template(template_name)
        prompt = template.render(
            proposal_type=proposal_type,
            proposal_number=proposal_number,
            title=title,
            old_status=old_status,
            new_status=new_status,
            language=self.language,
        )
        try:
            return self._run_claude_text_analysis(prompt, proposal_text)
        except Exception as e:
            logger.warning(f"Proposal analysis failed: {e}")
            return (
                _(f"Status changed: {proposal_type} #{proposal_number}"),
                _(
                    f"Analysis unavailable for {proposal_type} #{proposal_number}: {title} ({old_status} -> {new_status})"
                ),
            )

    def analyze_content_modification(
        self,
        proposal_type: str,
        proposal_number: int,
        title: str,
        diff_text: str,
    ) -> tuple[str, str]:
        template = self.jinja_env.get_template("proposal_content_modified_prompt.j2")
        prompt = template.render(
            proposal_type=proposal_type,
            proposal_number=proposal_number,
            title=title,
            language=self.language,
        )
        try:
            return self._run_claude_text_analysis(prompt, diff_text)
        except Exception as e:
            logger.warning(f"Proposal analysis failed: {e}")
            return (
                _(f"Content modified: {proposal_type} #{proposal_number}"),
                _(
                    f"Analysis unavailable for {proposal_type} #{proposal_number}: {title}"
                ),
            )

    def _run_claude_readme_analysis(self, prompt: str) -> tuple[str, str]:
        output = ""
        try:
            output = run_command(
                [self.claude_code_path, "-p"],
                input=prompt,
                timeout=self.timeout,
                check=False,
            )

            logger.debug(f"Claude README output length: {len(output)}")

            json_str = self._extract_json(output)
            data = json.loads(json_str)

            summary = data.get("summary", "")
            detail = data.get("detail", "")

            if not summary or not detail:
                raise AnalysisException(
                    "Invalid JSON response: missing 'summary' or 'detail' field"
                )

            return summary, detail

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Claude output: {e}")
            logger.debug(f"Raw output: {output}")
            raise AnalysisException(
                f"Failed to parse JSON from Claude output: {e}"
            ) from e
        except AnalysisException:
            raise
        except Exception as e:
            logger.error(f"Claude Code README analysis failed: {e}")
            raise AnalysisException(str(e)) from e

    def _run_claude_text_analysis(
        self, prompt: str, input_text: str
    ) -> tuple[str, str]:
        output = ""
        try:
            output = run_command(
                [self.claude_code_path, "-p", prompt],
                input=input_text,
                timeout=self.timeout,
                check=False,
            )

            json_str = self._extract_json(output)
            data = json.loads(json_str)

            summary = data.get("summary", "")
            detail = data.get("detail", "")

            if not summary or not detail:
                raise AnalysisException(
                    "Invalid JSON response: missing 'summary' or 'detail' field"
                )

            return summary, detail
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Claude output: {e}")
            logger.debug(f"Raw output: {output}")
            raise AnalysisException(
                f"Failed to parse JSON from Claude output: {e}"
            ) from e
        except AnalysisException:
            raise
        except Exception as e:
            logger.error(f"Claude Code analysis failed: {e}")
            raise AnalysisException(str(e)) from e

    def _build_release_analysis_prompt(
        self,
        repo_name: str,
        branch: str,
        release_data: dict,
    ) -> str:
        """Build release analysis prompt."""
        template = self.jinja_env.get_template("release_analysis_prompt.j2")
        releases = release_data.get("releases", [])
        is_first_check = len(releases) == 1
        return template.render(
            repo_name=repo_name,
            branch=branch,
            release_data=release_data,
            is_first_check=is_first_check,
            language=self.language,
        )

    def _run_claude_release_analysis(self, prompt: str) -> tuple[str, str]:
        """Execute claude-code CLI release analysis.

        Args:
            prompt: Analysis prompt

        Returns:
            (summary, detail) tuple

        Raises:
            AnalysisException: If analysis fails or JSON is invalid
        """
        output = ""
        try:
            output = run_command(
                [self.claude_code_path, "-p"],
                input=prompt,
                timeout=self.timeout,
                check=False,
            )

            logger.debug(f"Claude release output length: {len(output)}")

            json_str = self._extract_json(output)
            data = json.loads(json_str)

            summary = data.get("summary", "")
            detail = data.get("detail", "")

            if not summary or not detail:
                logger.error("JSON response missing required fields")
                raise AnalysisException(
                    "Invalid JSON response: missing 'summary' or 'detail' field"
                )

            return summary, detail

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Claude output: {e}")
            logger.debug(f"Raw output: {output}")
            raise AnalysisException(
                f"Failed to parse JSON from Claude output: {e}"
            ) from e
        except AnalysisException:
            raise
        except Exception as e:
            logger.error(f"Claude Code release analysis failed: {e}")
            raise AnalysisException(str(e)) from e

    def generate_title_and_summary(self, aggregated_report: str) -> tuple[str, str]:
        """Generate title and summary from aggregated report.

        Args:
            aggregated_report: Complete aggregated markdown report

        Returns:
            (title, summary) tuple
        """
        prompt = f"""Your task: Analyze the aggregated code change report below and generate a title and summary.

Language requirement: The user-configured output language is "{self.language}". Use this language for ALL your output.
For example, if you determine the language is Chinese, the title and summary MUST be in Chinese, not English.

CRITICAL FORMAT REQUIREMENTS:
1. Output EXACTLY two lines
2. Line 1 MUST start with "TITLE:" followed by the title
3. Line 2 MUST start with "SUMMARY:" followed by the summary
4. Do NOT output any other text (no explanations, no markdown, no code blocks)

Content requirements:
1. The title must be concise (maximum 10 words or equivalent length)
2. The summary must be a single paragraph (3-5 sentences) highlighting the most important changes across all repositories

Here is the aggregated report:

{aggregated_report}
"""

        try:
            logger.info("Generating title and summary with Claude...")
            output = run_command(
                [self.claude_code_path, "-p"],
                input=prompt,
                timeout=self.timeout,
                check=False,
            ).strip()

            title = _("Progress Report for Open Source Projects")
            summary = _("A progress report for open source projects.")

            for line in output.split("\n"):
                if line.startswith("TITLE:"):
                    title = line[6:].strip()
                elif line.startswith("SUMMARY:"):
                    summary = line[8:].strip()

            logger.info(f"Generated title: {title}")
            return title, summary

        except AnalysisException:
            raise
        except Exception as e:
            logger.error(f"Failed to generate title and summary: {e}")
            raise AnalysisException(str(e)) from e

    def _build_analysis_prompt(
        self,
        repo_name: str,
        branch: str,
        commit_messages: list[str],
        truncated: bool,
        original_length: int,
        analyzed_length: int,
    ) -> str:
        """Build analysis prompt."""
        template = self.jinja_env.get_template(TEMPLATE_ANALYSIS_PROMPT)
        return template.render(
            repo_name=repo_name,
            branch=branch,
            commit_messages=commit_messages,
            language=self.language,
            truncated=truncated,
            original_diff_length=original_length,
            analyzed_diff_length=analyzed_length,
        )

    def _run_claude_analysis(self, diff: str, prompt: str) -> tuple[str, str]:
        """Execute claude-code CLI analysis.

        Args:
            diff: Code diff content to analyze
            prompt: Analysis prompt

        Returns:
            (summary, detail) tuple

        Raises:
            AnalysisException: If analysis fails or JSON is invalid
        """
        output = ""
        try:
            output = run_command(
                [self.claude_code_path, "-p", prompt],
                input=diff,
                timeout=self.timeout,
                check=False,
            )

            logger.debug(f"Claude output length: {len(output)}")

            json_str = self._extract_json(output)
            data = json.loads(json_str)

            summary = data.get("summary", "")
            detail = data.get("detail", "")

            if not summary or not detail:
                logger.error("JSON response missing required fields")
                raise AnalysisException(
                    "Invalid JSON response: missing 'summary' or 'detail' field"
                )

            return summary, detail

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Claude output: {e}")
            logger.debug(f"Raw output: {output}")
            raise AnalysisException(
                f"Failed to parse JSON from Claude output: {e}"
            ) from e
        except AnalysisException:
            raise
        except Exception as e:
            logger.error(f"Claude Code analysis failed: {e}")
            raise AnalysisException(str(e)) from e

    def _extract_json(self, output: str) -> str:
        """Extract JSON from output, handling markdown code blocks.

        Args:
            output: Raw output from Claude

        Returns:
            Extracted JSON string

        Raises:
            AnalysisException: If JSON cannot be extracted
        """
        output = output.strip()

        json_pattern = r"\{[\s\S]*\}"
        match = re.search(json_pattern, output)

        if match:
            return match.group(0)

        raise AnalysisException("Could not extract JSON from Claude output")
