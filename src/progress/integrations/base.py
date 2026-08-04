from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:
    import aiohttp

    from progress.cli.notifications.events import Event, NotificationEvent
    from progress.cli.reports.pipeline import IntegrationReport
    from progress.config.root import CoreConfig
    from progress.errors import ProgressException


@dataclass
class Components:
    cfg: CoreConfig | None = None
    session: aiohttp.ClientSession | None = None


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    errors: list[ProgressException] = field(default_factory=list)


@dataclass
class ReportSection:
    """One section produced by an integration.

    Per spec 06:
    - ``title``: human-readable section heading.
    - ``content``: pre-rendered fallback used when template rendering fails.
    - ``payload``: structured fields consumed by the integration's own report
      template (e.g. repo's ``releases``/``commits``). Expanded into Jinja
      template variables at render time as ``**payload``.
    """

    title: str = ""
    content: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    """Unified result of one integration run.

    Per spec 06, the two channels (``reports`` vs ``events``) have different
    semantics and consumers:

    - ``reports`` → ``cli/reports/pipeline``: aggregated render + AI title/
      summary + DB persist + optional MarkPost publish. Produces an
      :class:`~progress.cli.reports.pipeline.IntegrationReport` per report type.
    - ``events`` → business records (snapshots / checkpoints / observability),
      e.g. ``ProposalEvent`` / ``ChangelogEvent`` / ``DiscoveredRepoEvent``.
      These are NOT dispatched to notification channels; the integration's
      ``build_notification`` hook authors its own aggregated
      :class:`~progress.cli.notifications.events.NotificationEvent`(s) from the
      pipeline's per-integration report output.
    """

    name: str = ""
    status: str = "success"
    summary: str = ""
    reports: list[ReportSection] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    errors: list[ProgressException] = field(default_factory=list)


@runtime_checkable
class Integration(Protocol):
    """Unified integration contract (spec 06).

    Five lifecycle hooks with strict responsibilities:

    - ``setup`` — receive shared dependencies (cfg, aiohttp session, etc.).
    - ``sync`` — config → state reconciliation (upsert + GC). No external fetch.
    - ``run``  — actual work: pull external data + diff against state + AI
      analysis + persist results. ``concurrency`` controls non-AI work; AI
      calls are serialized by a global semaphore (spec 08, AI_CONCURRENCY=1).
    - ``build_notification`` — author this integration's aggregated
      notification(s) from the pipeline's per-integration report output
      (``IntegrationReport`` list) plus the integration's own ``RunResult``
      (which carries the rich per-section detail the templates need). Each
      integration is the **sole author** of its own notifications: it decides
      content, fields and template kind. The default implementation produces no
      notifications. Called by the core orchestrator after the reports pipeline
      has run.
    - ``teardown`` — cleanup.
    """

    name: str
    config_schema: type

    async def setup(self, ctx: Components) -> None: ...
    async def sync(self) -> SyncResult: ...
    async def run(self, *, concurrency: int = 1) -> RunResult: ...
    async def build_notification(
        self,
        *,
        result: RunResult,
        reports: list[IntegrationReport],
    ) -> list[NotificationEvent]: ...
    async def teardown(self) -> None: ...


def strip_unknown_config_keys(
    data: dict[str, Any],
    config_schema: type[BaseModel],
) -> tuple[dict[str, Any], list[str]]:
    """Remove keys not present in ``config_schema`` before validation.

    Integrations use ``ConfigDict(extra="forbid")`` so a stale key left in the
    DB (e.g. after a field removal) would make ``model_validate`` reject the
    whole payload and silently fall back to defaults. This helper drops unknown
    top-level keys and recurses into list-of-dict fields (e.g. ``repos[]``) so
    the surviving config survives a schema downgrade. Returns the cleaned dict
    plus the list of removed keys (for logging).
    """

    logger = logging.getLogger(__name__)

    if not isinstance(data, dict):
        return data, []
    allowed = set(config_schema.model_fields.keys())
    cleaned: dict[str, Any] = {}
    removed: list[str] = []
    for key, value in data.items():
        if key not in allowed:
            removed.append(key)
            continue
        field_info = config_schema.model_fields.get(key)
        ann = getattr(field_info, "annotation", None) if field_info else None
        if isinstance(ann, type) and issubclass(ann, BaseModel) and isinstance(value, dict):
            inner, inner_removed = strip_unknown_config_keys(value, ann)
            cleaned[key] = inner
            removed.extend(f"{key}.{r}" for r in inner_removed)
            continue
        if ann is not None and getattr(ann, "__origin__", None) is list:
            args = getattr(ann, "__args__", ())
            item_type = args[0] if args else None
            if isinstance(item_type, type) and issubclass(item_type, BaseModel) and isinstance(value, list):
                new_list: list[Any] = []
                for idx, item in enumerate(value):
                    if isinstance(item, dict):
                        inner, inner_removed = strip_unknown_config_keys(cast("dict[str, Any]", item), item_type)
                        new_list.append(inner)
                        removed.extend(f"{key}[{idx}].{r}" for r in inner_removed)
                    else:
                        new_list.append(item)
                cleaned[key] = new_list
                continue
        cleaned[key] = value
    if removed:
        logger.warning("stripped deprecated config keys %s for schema %s", removed, config_schema.__name__)
    return cleaned, removed
