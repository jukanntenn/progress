# User & Password Management

English | [中文](users.zh.md)

The auth subsystem is always active (`src/progress/api/auth.py`). On first boot with `auth.enabled=true` and an empty users table, an initial superuser is created from `cfg.auth.initial_admin_username` / `initial_admin_password`; a random password is printed to the logs once.

Manage users from the CLI (`progress users ...`, see `src/progress/cli/users.py`):

```bash
uv run progress users list
uv run progress users create <name> [--superuser] [-p <password>]
uv run progress users reset-password <name> [-p <password>]   # random if -p omitted
uv run progress users deactivate <name>
```

Self-service password change is in the Web UI (Settings page, top-right user menu) and via `POST /api/v1/auth/change-password` (requires current password).
