"""Config API routes — backed by the database config blob.

The TOML file seeds the blob on first run; thereafter the blob is the single
source of truth and these endpoints read/write it. Writes are guarded by
optimistic locking (``version``) and secrets are masked in every GET response.
"""

from typing import Any
import pytz
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...config import OwnerConfig, RepositoryConfig
from ...config_store import (
    ConfigVersionConflict,
    get_config_json_schema,
    load_app_config,
    mask_secrets,
    save_app_config,
    validate_app_config,
)
from ...contrib.repo.models import GitHubOwner
from ...contrib.repo.owner import replace_owners
from ...contrib.repo.repository import replace_repositories
from ...db.models import Repository
from ...errors import ConfigException

router = APIRouter(prefix="/config", tags=["config"])


class ConfigResponse(BaseModel):
    data: dict[str, Any]
    version: int


class ConfigSaveRequest(BaseModel):
    config: dict[str, Any]
    version: int


class ConfigValidateRequest(BaseModel):
    config: dict[str, Any]


class ConfigValidateResponse(BaseModel):
    success: bool
    error: str | None = None


class TimezonesResponse(BaseModel):
    timezones: list[str]


@router.get("", response_model=ConfigResponse)
async def get_config():
    loaded = await load_app_config()
    if loaded is None:
        raise HTTPException(
            status_code=409,
            detail="Application config has not been seeded.",
        )
    data, version = loaded
    return ConfigResponse(data=mask_secrets(data), version=version)


@router.post("", response_model=ConfigResponse)
async def save_config(request: ConfigSaveRequest):
    try:
        merged, version = await save_app_config(request.config, request.version)
    except ConfigVersionConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ConfigException as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ConfigResponse(data=mask_secrets(merged), version=version)


@router.post("/validate", response_model=ConfigValidateResponse)
async def validate_config(request: ConfigValidateRequest):
    try:
        await validate_app_config(request.config)
    except ConfigException as e:
        return ConfigValidateResponse(success=False, error=str(e))
    return ConfigValidateResponse(success=True)


@router.get("/schema")
def get_schema():
    return get_config_json_schema()


@router.get("/timezones", response_model=TimezonesResponse)
def get_timezones():
    return TimezonesResponse(timezones=sorted(pytz.all_timezones))


# --- table-backed lists (repos / owners) ----------------------------------
# These live in the repositories/github_owners tables, not the config blob, so
# they have their own read/replace endpoints separate from the blob above.


class RepoView(BaseModel):
    id: int
    name: str
    url: str
    branch: str
    enabled: bool


class OwnerView(BaseModel):
    id: int
    owner_type: str
    name: str
    enabled: bool


@router.get("/repos", response_model=list[RepoView])
async def list_repos():
    return [
        RepoView(id=r.id, name=r.name, url=r.url, branch=r.branch, enabled=r.enabled)
        for r in await Repository.all().order_by("id")
    ]


@router.put("/repos", response_model=list[RepoView])
async def replace_repos_route(request: Request, repos: list[RepositoryConfig]):
    await replace_repositories(repos, request.app.state.config.github.protocol)
    return await list_repos()


@router.get("/owners", response_model=list[OwnerView])
async def list_owners():
    return [
        OwnerView(id=o.id, owner_type=o.owner_type, name=o.name, enabled=o.enabled)
        for o in await GitHubOwner.all().order_by("id")
    ]


@router.put("/owners", response_model=list[OwnerView])
async def replace_owners_route(owners: list[OwnerConfig]):
    await replace_owners(owners)
    return await list_owners()
