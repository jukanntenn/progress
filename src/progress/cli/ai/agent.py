"""Pydantic AI agent for structured output extraction (spec 08).

Per spec 08, AI analysis is a **structured output extraction** task, not an
agent task. We use Pydantic AI with ``output_type=str`` and an
``output_validator`` that parses the model's text response into a Pydantic
model, with ``json_repair`` as the last-line fallback for malformed JSON.

The validator signature ``str -> AnalysisResult`` means ``result.output`` is
an ``AnalysisResult`` at runtime (Pydantic AI's ``OutputValidator.validate``
casts via ``Any`` internally so the return type is not statically constrained
to the input type).

Why ``output_type=str`` instead of ``output_type=AnalysisResult``:
- The spec's example code uses this exact pattern (``output: str -> AnalysisResult``).
- It works for ALL providers (strong providers like Anthropic/OpenAI AND weak
  providers like local Ollama that lack schema-constrained tool calling).
- ``json_repair`` is the explicit last-line defense per spec 08.
- Pydantic AI's built-in retry on ``ModelRetry`` still applies.

The model is configured lazily (``defer_model_check=True``) so the agent can
be constructed without env vars; the actual model is passed at ``run()`` time
or overridden in tests via ``agent.override(model=TestModel())``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

import json_repair
from pydantic import BaseModel, ValidationError
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.models import infer_model
from pydantic_ai.providers import infer_provider_class
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from progress.config.root import AnalysisConfig
from progress.errors import ProgressException
from progress.observability import observe_span

logger = logging.getLogger(__name__)

AI_TIMEOUT: int = 600
AI_RETRIES: int = 3
AI_RETRY_INITIAL_DELAY: float = 1.0
AI_RETRY_MAX_DELAY: float = 60.0
AI_CONCURRENCY: int = 1

_extraction_semaphore: asyncio.Semaphore | None = None

_agents: dict[type[BaseModel], Agent[Any, Any]] = {}


async def _acquire_extraction_slot() -> asyncio.Semaphore:
    """Get (lazily creating) the global AI concurrency semaphore.

    Per spec 02 ``AI_CONCURRENCY = 1`` bounds concurrent AI extractions to 1.
    The semaphore is created lazily so it binds to the running event loop
    rather than the import-time loop (which may not exist).
    """
    global _extraction_semaphore
    if _extraction_semaphore is None:
        _extraction_semaphore = asyncio.Semaphore(AI_CONCURRENCY)
    return _extraction_semaphore


class AnalysisResult(BaseModel):
    """Structured output for diff/release/readme/proposal analysis."""

    summary: str
    detail: str


class TitleSummary(BaseModel):
    """Structured output for aggregated report title + summary."""

    title: str
    summary: str


def _validate_with_repair[T: BaseModel](output: str, result_type: type[T]) -> T:
    """Parse ``output`` as ``result_type`` with ``json_repair`` fallback.

    1. Try direct ``model_validate_json`` (fast path for well-formed JSON).
    2. On failure, run ``json_repair.repair_json`` then re-validate.
    3. If repair still fails, raise ``ModelRetry`` so Pydantic AI retries
       the model request with feedback.
    """
    try:
        return result_type.model_validate_json(output)
    except ValidationError:
        pass
    try:
        repaired = json_repair.repair_json(output, return_objects=True)
        return result_type.model_validate(repaired)
    except ValidationError as e:
        raise ModelRetry(f"output could not be parsed as {result_type.__name__} even after json_repair: {e}") from e


def get_agent(
    result_type: type[BaseModel],
    *,
    model: Any = None,
    api_key: str | None = None,
    base_url: str | None = None,
    instructions: str | None = None,
) -> Agent[Any, Any]:
    """Return the cached singleton agent for ``result_type`` (spec 08).

    The cache is keyed **only** by ``result_type`` (one agent per output type).
    The model is resolved once on first construction — from the ``model`` /
    ``api_key`` / ``base_url`` of whichever caller builds it first (DB-config
    credentials are injected via :func:`_resolve_model`, per spec 02/08).
    Subsequent callers' ``model`` / ``api_key`` / ``base_url`` are ignored,
    which is correct because config is seeded once per run.

    Caching by ``result_type`` alone is what makes ``agent.override(model=...)``
    work in tests: ``Agent.override`` sets a ``ContextVar`` on the agent object,
    so it only affects code that calls ``agent.run(...)`` on the *same* instance
    — and production call sites always fetch the same per-type singleton. An
    override always wins over the model baked in here (pydantic-ai
    ``_get_model`` checks ``_override_model`` first).
    """
    cached = _agents.get(result_type)
    if cached is not None:
        return cached
    resolved_model = _resolve_model(model, api_key, base_url)
    agent: Agent[Any, Any] = Agent(
        model=resolved_model,
        output_type=str,
        instructions=instructions,
        defer_model_check=True,
    )

    @agent.output_validator
    def _validator(output: str) -> Any:
        return _validate_with_repair(output, result_type)

    _agents[result_type] = agent
    return agent


def create_agent(
    result_type: type[BaseModel],
    *,
    model: Any = None,
    api_key: str | None = None,
    base_url: str | None = None,
    instructions: str | None = None,
) -> Agent[Any, Any]:
    """Return the cached agent for ``result_type`` (delegates to :func:`get_agent`).

    Kept for backward compatibility; callers should prefer :func:`get_agent`.
    """
    return get_agent(result_type, model=model, api_key=api_key, base_url=base_url, instructions=instructions)


def _resolve_model(model: Any, api_key: str | None, base_url: str | None = None) -> Any:
    """Resolve a model string to a Model instance, injecting ``api_key`` and ``base_url``.

    If ``api_key`` is provided and ``model`` is a string like
    ``"anthropic:claude-sonnet-4"``, the provider is constructed with the
    explicit key so credentials can come from the DB config (spec 02/08)
    rather than only environment variables. Without this, ``infer_model``
    builds the provider with ``api_key=None`` and the SDK falls back to env
    vars — which means a user-set ``analysis.api_key`` in the Web UI would
    be silently ignored.

    ``base_url`` (when non-empty) is passed to providers that accept it
    (e.g. OpenAI-compatible self-hosted services). Empty string means
    "use the provider's default endpoint".
    """
    if not isinstance(model, str) or model == "test":
        return model
    try:
        pass
    except ImportError:
        return model

    if not api_key:
        try:
            return infer_model(model)
        except Exception:
            return model

    try:
        provider_name = model.split(":", 1)[0]
        provider_cls = infer_provider_class(provider_name)
    except Exception:
        try:
            return infer_model(model)
        except Exception:
            return model

    try:
        provider_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            provider_kwargs["base_url"] = base_url
        provider = cast("Any", provider_cls)(**provider_kwargs)
    except TypeError:
        try:
            return infer_model(model)
        except Exception:
            return model

    try:
        return infer_model(model, provider_factory=lambda _name: provider)
    except Exception:
        return model


def build_model_string(cfg: AnalysisConfig) -> str | None:
    """Build a Pydantic AI model string from ``AnalysisConfig``.

    Returns ``None`` if no provider/model is configured (caller should skip
    AI work in that case).
    """
    if not cfg.provider or not cfg.model:
        return None
    return f"{cfg.provider}:{cfg.model}"


def _resolve_agent_model_name(agent: Agent[Any, Any]) -> str:
    """Best-effort extraction of the model name baked into ``agent``.

    Pydantic-ai ``Model`` instances expose ``model_name`` (e.g. ``gpt-4o``,
    ``test``). Falls back to ``"unknown"`` when the attribute is absent so the
    span always carries a non-empty value.
    """
    agent_model = getattr(agent, "model", None)
    return getattr(agent_model, "model_name", None) or "unknown"


async def run_extraction(
    agent: Agent[Any, Any],
    prompt: str,
    *,
    model: Any = None,
) -> Any:
    """Run the extraction agent and return the parsed result.

    Per spec 02, the run is bounded by ``AI_TIMEOUT`` (600s), serialized by
    ``AI_CONCURRENCY`` (1), and retried ``AI_RETRIES`` (3) times with
    exponential backoff on transient failures. Pydantic AI's built-in
    ``ModelRetry`` for validator failures still applies inside each attempt.

    Raises ``ProgressException`` if the model is not configured or the run
    fails after the retry budget is exhausted.
    """

    async def _run() -> Any:
        semaphore = await _acquire_extraction_slot()
        async with semaphore:
            return await asyncio.wait_for(agent.run(prompt, model=model), timeout=AI_TIMEOUT)

    retrying = AsyncRetrying(
        stop=stop_after_attempt(AI_RETRIES),
        wait=wait_exponential_jitter(initial=AI_RETRY_INITIAL_DELAY, max=AI_RETRY_MAX_DELAY),
        retry=retry_if_exception_type((asyncio.TimeoutError, OSError)),
        reraise=True,
    )
    model_attr = model
    span_model_name = str(model_attr) if model_attr else _resolve_agent_model_name(agent)
    async with observe_span(
        "progress.ai.call",
        attributes={"model": span_model_name},
    ):
        try:
            result = await retrying(_run)
        except RetryError as e:
            raise ProgressException(f"AI extraction failed after {AI_RETRIES} attempts: {e}") from e
        except Exception as e:
            raise ProgressException(f"AI extraction failed: {e}") from e
    return result.output


__all__ = [
    "AI_CONCURRENCY",
    "AI_RETRIES",
    "AI_TIMEOUT",
    "AnalysisResult",
    "TitleSummary",
    "build_model_string",
    "create_agent",
    "get_agent",
    "run_extraction",
]
