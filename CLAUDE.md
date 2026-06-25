# Progress

Progress is a GitHub project tracking tool that traces multi-repo code changes, runs AI analysis, and generates reports to help users track open-source project progress.

## Project Structure

Keep this section up to date with the project structure. Use it as a reference to find files and directories.

```text
progress/
├── pyproject.toml          # Project configuration
├── config.example.toml     # Example configuration file
├── requirements.txt        # Dependencies list
├── uv.lock                # uv lock file
├── README.md              # Project README (English)
├── README_zh.md           # Project README (Chinese)
├── CLAUDE.md              # Project instructions
├── .gitignore             # Git ignore file
├── .dockerignore          # Docker ignore file
├── .github/               # GitHub workflow files
├── .claude/               # Claude Code configuration
├── .vscode/               # VS Code configuration
│   └── tasks.json        # VS Code tasks
├── config/                # Configuration files directory
│   ├── docker.toml       # Docker configuration
│   ├── full.toml         # Full configuration
│   └── simple.toml       # Simple configuration
├── data/                  # Application data directory
│   ├── progress.db       # SQLite database
│   ├── progress.log      # Application log
│   └── repos/            # Repositories data
├── docker/                # Docker configuration files
│   ├── Dockerfile        # Unified Docker container definition
│   ├── docker-compose.yml # Docker Compose configuration
│   ├── Caddyfile         # Caddy reverse proxy configuration
│   ├── build.py          # Docker build script (Python)
│   └── s6/               # s6-overlay service definitions
│       ├── cont-init.d/  # Container initialization scripts
│       └── s6-rc.d/      # Service run scripts (caddy, fastapi, nextjs, cron)
├── devops/                # DevOps related files
│   ├── dev.py            # Development environment manager
│   └── ansible/          # Ansible deployment files
├── guides/                # Guide documentation
│   ├── config.md         # Configuration guide
│   ├── dev.md            # Development guide
│   ├── i18n.md           # Internationalization guide
│   ├── proposal_tracking.md # Proposal tracking guide
│   └── testing.md        # Testing guide
├── scripts/               # Utility scripts
│   ├── compilemessages.sh # Compile localization messages
│   └── makemessages.sh   # Generate localization messages
├── web/                   # Frontend (Next.js + React)
│   ├── package.json      # Frontend dependencies
│   ├── pnpm-lock.yaml    # pnpm lock file
│   ├── pnpm-workspace.yaml # pnpm workspace config
│   ├── next.config.ts    # Next.js configuration
│   ├── tsconfig.json     # TypeScript configuration
│   ├── vitest.config.ts  # Vitest test configuration
│   ├── eslint.config.mjs # ESLint configuration
│   ├── postcss.config.mjs # PostCSS configuration
│   ├── public/           # Static assets
│   └── src/              # Frontend source code
│       ├── app/          # Next.js App Router
│       ├── components/   # React components
│       ├── hooks/        # Custom React hooks
│       ├── i18n/         # Internationalization
│       ├── lib/          # Utility libraries
│       └── test/         # Test setup
├── src/                   # Source code directory
│   └── progress/          # Main package directory
│       ├── __init__.py    # Package initialization
│       ├── cli.py         # CLI entry point
│       ├── config.py      # Configuration management
│       ├── consts.py      # Constants
│       ├── db.py          # Database operations
│       ├── enums.py       # Enum definitions
│       ├── errors.py      # Custom errors
│       ├── github.py      # GitHub CLI interactions
│       ├── i18n.py        # Internationalization
│       ├── log.py         # Logging
│       ├── markpost.py    # Markpost functionality
│       ├── models.py      # Peewee ORM models
│       ├── ai/             # AI analysis (analyzers/factory)
│       ├── notification/  # Notifications (channels/messages/factory)
│       ├── notifier.py    # Notifications (legacy)
│       ├── proposal_parsers.py # Proposal parsing modules
│       ├── proposal_tracking.py # Proposal tracking logic
│       ├── repo.py        # Repository management
│       ├── repository.py  # Extended repository operations
│       ├── reporter.py    # Markdown report generator
│       ├── utils.py       # Utility functions
│       ├── api/           # Web API (FastAPI)
│       ├── templates/     # Jinja2 template files
│       │   ├── aggregated_report.j2
│       │   ├── analysis_prompt.j2
│       │   ├── email_notification.j2
│       │   ├── release_analysis_prompt.j2
│       │   ├── repository_report.j2
│       │   ├── proposal_accepted_prompt.j2
│       │   ├── proposal_content_modified_prompt.j2
│       │   ├── proposal_events_report.j2
│       │   ├── proposal_new_prompt.j2
│       │   ├── proposal_rejected_prompt.j2
│       │   ├── proposal_status_change_prompt.j2
│       │   ├── proposal_withdrawn_prompt.j2
│       └── locales/       # Localization files
│           ├── progress.pot
│           └── zh-hans/
│               └── LC_MESSAGES/
│                   └── progress.po
└── tests/                 # Test files directory
    ├── __init__.py
    ├── notification/      # Notification framework tests
    ├── test_analyzer.py
    ├── test_config.py
    ├── test_github.py
    ├── test_markpost.py
    ├── test_proposal_parsers.py
    ├── test_proposal_tracking.py
    ├── test_repo.py
    └── test_utils.py
```

## Commands

- Install dependencies: `uv sync`
- Install frontend dependencies: `cd web && pnpm install`
- Run application: `uv run progress -c config.toml`
- Run unit tests: `uv run pytest -v`
- Run frontend tests: `cd web && pnpm test`
- Start dev server (backend): `PYTHONPATH=src CONFIG_FILE=config.toml uv run fastapi dev`
- Start dev server (frontend): `cd web && pnpm dev`
- Start all services: `python devops/dev.py start`
- Stop all services: `python devops/dev.py stop`
- Build Docker images: `python docker/build.py`

## Proposal Tracking

- Configure proposal trackers in `config.toml` via `proposal_trackers`, a list of kind strings (e.g., `proposal_trackers = ["eip", "erc", "pep", "rfc", "dep"]`). Supported kinds: `"eip"`, `"erc"`, `"pep"`, `"rfc"`, `"dep"`. Per-kind repository details (URL, branch, directory, file patterns) are defined in code (`KIND_CONFIGS` in `src/progress/contrib/proposal/types.py`), not in the config file.
- Run proposal-only checks with `uv run progress check --trackers-only`.
- Run proposal checks explicitly with `uv run progress track-proposals`.

## Tech Stack

- Programming Language: Python 3.12+
- Package and Project Manager: uv 0.9+
- CLI Framework: Click 8.3+
- Web Framework: FastAPI 0.115+
- Frontend: React 19 + TypeScript + Next.js 16 + Tailwind CSS v4
- Frontend UI: @base-ui/react + class-variance-authority
- Frontend Data Fetching: @tanstack/react-query v5
- Frontend i18n: next-intl v4
- Frontend Themes: next-themes
- Frontend Package Manager: pnpm
- RSS Generation: feedgen
- Markdown Rendering: markdown-it-py (CommonMark compliant with GitHub style)
- Containerized development and deployment: Docker
- Git Operations: GitPython 3.1.46+
- GitHub API: PyGithub 2.8.1+
- GitHub CLI: GitHub CLI (gh) - only for initial repository clone
- AI Assistant: Claude Code

## Standards

MUST FOLLOW THESE RULES, NO EXCEPTIONS

- All imports must be placed at the beginning of the file
- DO NOT write comments (Except for existing comments) – use self-documenting code instead. When necessary, only add meaningful comments explaining why (not what) something is done
- Prefer using dbhub MCP instead of bash commands for database-related operations
- Prefer using Context7 MCP when need library/API documentation, code generation, setup or configuration steps without having to explicitly ask
- Prior to running any external tool (e.g., gh, claude) within the code, it is recommended to verify its usage by using the help parameter (e.g., `gh repo clone --help`)
- English shall be used for comments, documentation, log messages and exception information in code except for those intended to be targeted to other languages (e.g., Chinese documentation / prompt files)
- For adding or modifying configuration items, refer to `guides/config.md`
- For development server usage, refer to `guides/dev.md`
- For writing test code, refer to `guides/testing.md`
- For i18n, refer to `guides/i18n.md`
