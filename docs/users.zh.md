# 用户与密码管理

[English](users.md) | 中文

认证子系统始终处于启用状态（`src/progress/api/auth.py`）。首次启动时若 `auth.enabled=true` 且 users 表为空，系统会从 `cfg.auth.initial_admin_username` / `initial_admin_password` 创建初始超级用户；随机密码会打印到日志一次。

通过 CLI（命令行界面）管理用户（`progress users ...`，见 `src/progress/cli/users.py`）：

```bash
uv run progress users list
uv run progress users create <name> [--superuser] [-p <password>]
uv run progress users reset-password <name> [-p <password>]   # random if -p omitted
uv run progress users deactivate <name>
```

自助修改密码的入口在 Web UI（设置页，右上角用户菜单），也可通过 `POST /api/v1/auth/change-password` 进行（需提供当前密码）。
