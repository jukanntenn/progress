"""git-proxy entry: configure GitPython subprocess proxying from merged config."""

from __future__ import annotations

from progress.cli.git.local import set_git_proxy
from progress.kernel import Entry


def make_git_proxy_entry() -> Entry:
    async def _apply(ctx, config) -> None:
        set_git_proxy(ctx.config.github.proxy)

    return Entry(id="git-proxy", plugin=_apply, inject=["config"])
