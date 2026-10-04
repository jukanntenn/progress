# AI agent 钩子

[English](agent-hooks.md) | 中文

为 Claude Code、Codex、ZCode 与 OpenCode 配置的项目本地生命周期钩子：它们让 agent（智能体）写出的代码保持整洁，并在 lint 失败时拒绝让 agent 结束回合。

## 设计：prek 是唯一真源

所有钩子都把格式化与 lint 委托给 **prek**（本仓库的 pre-commit 运行器）。prek 以 **workspace 模式**运行：根目录 `prek.toml` 承载后端 + builtin 钩子，`web/prek.toml` 承载前端（eslint/prettier）钩子。两个文件定义了相同的两个组名：

- **`format`**：只改字节、永不失败的格式化器，包括 `ruff-format`、`prettier`、`trailing-whitespace`、`end-of-file-fixer`、`mixed-line-ending`。
- **`lint`**：可能失败（并尽量 `--fix`）的 linter，包括 `ruff-check`、`eslint`。

与具体 agent 无关的操作位于 **`.agents/hooks/_core.py`**，它只负责运行 prek：

```python
format(paths)            # prek run --group format --files <paths>          (best-effort)
lint(*paths, all_files=) # prek run --group lint   --files <paths> | --all-files
```

函数名与组名一一对应。prek 自身的按钩子 `files` 过滤与 workspace 目录路由会把每个文件送到正确的工具（`.py` 路径只会命中根项目的 ruff；`.ts` 路径只会命中 web/ 项目的 eslint/prettier），因此各 agent shell 从不硬编码「扩展名 → 工具」的映射，该映射只存在于两个 `prek.toml` 文件中。新增一个格式化器只需改一行配置，所有 agent 都会自动获得它。

## shell 与 core 的分工

每个 agent 保留**自己的钩子 shell**（payload 解析与 stdout 协议因 agent 而异，并未统一），各 shell **只**通过 `_core` 共享 prek 操作：

| agent | 钩子配置 | shell | payload / 协议 |
|-------|--------------|-------|--------------------|
| Claude Code | `.claude/settings.json` | `.claude/hooks/post_tool_use.py`, `stop.py` | `tool_input.file_path`; snake_case; block = `{"decision":"block","reason":...}` |
| Codex | `.codex/hooks.json` | `.codex/hooks/post_tool_use.py`, `stop.py` | `tool_input.command` 中的 `apply_patch` V4A patch 文本；`stop_hook_active` 守卫 |
| ZCode | `~/.zcode/cli/config.json`（用户级） | `.zcode/hooks/post_tool_use.py`, `stop.py` | `toolInput.file_path`; camelCase; `stopHookActive`; 续跑上限 3 次 |
| OpenCode | `.opencode/plugins/hooks.ts`（自动加载） | （自包含 TS） | `args.filePath`/`patchText`；OpenCode 事件无法阻断，因此注入一条合成消息 |

OpenCode 运行在 Bun 之下，因此它的 shell 不导入 `_core`，而是通过 Bun 的 shell `` $ `` 直接调用 `prek run -C <root> --group ...`，但使用的组与语义完全相同。

## PostToolUse：逐文件格式化

每次编辑后触发。shell 提取被编辑的路径，先运行 `_core.format(paths)`，再运行 `_core.lint(*paths)`（均为 best-effort，忽略退出码）。调用完成后文件即完全规范化：已格式化**且**已修复 lint（例如移除了未使用的 import），之后再对它执行 `prek run` 就是空操作。这正是 agent 编辑后再跑 `prek` 能让工作树保持干净的原因：agent 运行的 prek 组与 prek 自己随后将运行的完全相同。

## Stop：全仓库 lint 门禁

当 agent 想结束回合时触发。shell 运行 `_core.lint(all_files=True)`（`prek run --group lint --all-files`）：

- **lint 干净**：退出码 0、无输出，agent 正常停止。
- **lint 有问题**：shell 打印该 agent 的阻断形式（Claude/Codex/ZCode：携带 prek 输出的 `{"decision":"block","reason":...}` JSON；OpenCode：一条合成用户消息），agent 被送回再做一轮。

prek 同样把「某个 fixer 修改了文件」视为非零退出（重新暂存语义）。在有 CI 门禁的干净工作树里，Stop 时不会有任何东西再改文件（被编辑的文件早已被 PostToolUse 修复），因此非零退出就明确意味着仍存在无法自动修复的 lint 问题。

### 死循环守卫

钩子输入携带「stop 已激活」标志（`stop_hook_active` / `stopHookActive`）：首次 Stop 为 `false`，之后为 `true`。一旦为真，钩子即收手放行，让 agent 停止；权威的 lint 裁决从此属于 CI，绝不属于钩子循环。

## 生成文件豁免

生成产物（`progress.pot`、`web/openapi.json`、`web/src/api/schema.ts`）保持逐字节原样：它们的字节归其生成器所有，不归任何钩子（见本仓库的 drift 约定）。它们在两处互补的位置被排除：

- **prek 的 `exclude`**：根 `prek.toml` 列出了全部生成文件（它是 workspace 根配置，其 exclude 会在文件到达任何项目的钩子之前全局生效，包括根项目的 builtin 钩子）；`web/prek.toml` 针对 `cd web && prek run` 的场景重复列出两个 web/ 产物。因此没有任何 prek 钩子（format、lint、builtin）会碰它们，`_core` 的 format/lint 调用也会自动跳过它们。
- **`web/.prettierignore`**（`openapi.json`、`src/api/schema.ts`）与 eslint 的 `ignores`：使 `pnpm format` / `pnpm lint`（开发者直接调用、不经 prek）也跳过它们。

`web/pnpm-lock.yaml` 与 `.po` 语言文件（人工翻译）是被跟踪的例外：lockfile 经 `.prettierignore` 忽略，`.po` 则仍在作用域内，由 hygiene + catalog-lint 钩子负责。

## ZCode 配置位于用户级

ZCode 运行时（v2.1.0，WSL）会从 `.zcode/config.json` 剥离 workspace 级钩子（"Project hooks were ignored by the security policy"）。因此钩子配置放在**用户级** `~/.zcode/cli/config.json`，并通过 `${ZCODE_PROJECT_DIR}` 检查 `.zcode/hooks/` 是否存在，以免影响其他 workspace。证据见 `.zcode/README.md`。

## 在本地测试钩子

```bash
# PostToolUse on a clean file: no output, exit 0
echo '{"tool_input":{"file_path":"src/progress/__init__.py"}}' \
  | uv run .claude/hooks/post_tool_use.py

# Codex PostToolUse (V4A patch text carries the path)
printf '%s' '{"tool_input":{"command":"*** Update File: src/progress/__init__.py\nprint(1)"}}' \
  | uv run .codex/hooks/post_tool_use.py

# Stop gate, loop guard active: no output, exit 0
echo '{"stop_hook_active":true}' | uv run .claude/hooks/stop.py

# Functional: an ill-formatted temp file IS reformatted by the hook
printf 'x=1\n' > /tmp/_t.py  # (place inside the repo for prek to see it)
echo '{"tool_input":{"file_path":"_t.py"}}' | uv run .claude/hooks/post_tool_use.py
```

想看阻断路径，可制造一个 lint 错误（例如未使用的 import）并运行 Stop 钩子：它会打印 `{"decision":"block",...}` JSON，prek 的诊断输出放在 `reason` 里。
