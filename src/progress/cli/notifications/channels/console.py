"""Console channel: prints a rich notification card to stdout (spec 10).

Two outputs fire per ``send``:

- **stdout** — a structured ``rich`` card (colored panel, stat tiles, badges,
  links) that mirrors the Feishu v2 card and the branded email. This is the
  human-facing progress display during a CLI run.
- **stderr / log file** — a one-line ``structlog`` summary (``notification.console``
  with title/body/content_type) for machine consumption and grep-ability.

stdout vs stderr: the rich card is the *result* the user wants to see, so it
goes to stdout (piped/redirected output captures it). The structlog line goes
to the observability stderr handler + the rotated JSON log file, so it never
mixes into a captured stdout stream. When stdout is not a TTY (piped), rich
automatically strips ANSI color codes so the text stays clean.

Per spec 10, ``send`` does NOT swallow exceptions — the Dispatcher collects
failures into ``DispatchOutcome``. Rich-card rendering itself is defensive
(``render_console_card`` returns ``None`` on any error) so a rendering glitch
can never break delivery; the worst case is the plain-text body is printed.
"""

from __future__ import annotations

from rich.console import Console
import structlog

from progress.cli.notifications.base import ChannelPayload, SendResult
from progress.cli.notifications.channels.console_card import render_console_card

logger = structlog.get_logger(__name__)


class ConsoleChannel:
    """Print a rich notification card to stdout + log a one-line summary."""

    name = "console"

    def __init__(self) -> None:
        self._console = Console()

    async def send(self, payload: ChannelPayload) -> SendResult:
        card = render_console_card(payload)
        if card is not None:
            self._console.print(card)
        else:
            self._console.print(payload.body)
        logger.info(
            "notification.console",
            title=payload.title,
            body=payload.body,
            content_type=payload.content_type.value,
        )
        return SendResult(channel=self.name, ok=True)


__all__ = ["ConsoleChannel"]
