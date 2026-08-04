"""Integration endpoints (spec 12).

Surfaces the plugin registry over HTTP so the frontend can render per-plugin
status panels and discover which integrations are configured.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from progress.api.auth import get_current_user
from progress.api.schemas import IntegrationSummary
from progress.config.schema import get_config_json_schema
from progress.integrations.registry import discover_integrations

router = APIRouter(tags=["integrations"], dependencies=[Depends(get_current_user)])


@router.get(
    "/integrations",
    response_model=list[IntegrationSummary],
    status_code=status.HTTP_200_OK,
)
async def list_integrations() -> list[IntegrationSummary]:
    """Registered integration list (spec 12)."""
    schemas = get_config_json_schema()
    return [
        IntegrationSummary(
            name=name,
            config_schema=schemas.get(name, {}),
        )
        for name in discover_integrations()
    ]


@router.get(
    "/integrations/{name}/status",
    response_model=IntegrationSummary,
    status_code=status.HTTP_200_OK,
)
async def integration_status(name: str) -> IntegrationSummary:
    """Return one integration's status summary (spec 12)."""
    integration_cls = discover_integrations().get(name)
    if integration_cls is None:
        raise HTTPException(status_code=404, detail=f"integration '{name}' not registered")
    schemas = get_config_json_schema()
    return IntegrationSummary(name=name, config_schema=schemas.get(name, {}))


__all__ = ["router"]
