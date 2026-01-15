# Progress

Progress is a GitHub project tracking tool that traces multi-repo code changes, runs AI analysis, and generates reports to help users track open-source project progress.

## Project Structure

Keep this section up to date with the project structure. Use it as a reference to find files and directories.

```text
src/progress/
├── __init__.py         # Package initialization
├── cli.py              # CLI entry point and main flow control
├── config.py           # Configuration file loading and validation
├── consts.py           # Constants definition
├── enums.py            # Enum definitions
├── models.py           # Peewee ORM model definitions
├── db.py               # Database operations
├── errors.py           # Custom errors and exceptions
├── log.py              # Logging configuration
├── github.py           # GitHub CLI interactions (clone, sync, diff)
├── repository.py       # Repository manager
├── analyzer.py         # Claude Code analyzer
├── reporter.py         # Markdown report generator (Jinja2)
├── notifier.py         # Feishu webhook and email notifications
├── utils.py            # Utility functions
└── templates/          # Jinja2 template files
    ├── repository_report.j2
    ├── aggregated_report.j2
    ├── analysis_prompt.j2
    └── email_notification.j2
```

## Commands

- Install dependencies: `uv sync`
- Run application: `uv run progress -c config.toml`
- Run unit tests: `uv run pytest -v`

## Tech Stack

- Programming Language: Python 3.12+
- Package and Project Manager: uv 0.9+
- CLI Framework: Click 8.3+
- Containerized development and deployment: Docker
- GitHub Interaction: GitHub CLI (gh)
- AI Assistant: Claude Code

## Standards

MUST FOLLOW THESE RULES, NO EXCEPTIONS

- All imports must be placed at the beginning of the file
- DO NOT write comments (Except for existing comments) – use self-documenting code instead. When necessary, only add meaningful comments explaining why (not what) something is done
- Prefer using dbhub MCP instead of bash commands for database-related operations
- Prefer using Context7 MCP when need library/API documentation, code generation, setup or configuration steps without having to explicitly ask
- Prior to running any external tool (e.g., gh, claude) within the code, it is recommended to verify its usage by using the help parameter (e.g., `gh repo clone --help`)
- English shall be used for comments, documentation, log messages and exception information in code
- For adding or modifying configuration items, refer to `guides/config.md`
- For writing test code, refer to `guides/testing.md`
- For i18n, refer to `guides/i18n.md`
