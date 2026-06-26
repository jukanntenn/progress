"""Config API routes — backed by the database config blob.

The TOML file seeds the blob on first run; thereafter the blob is the single
source of truth and these endpoints read/write it. Writes are guarded by
optimistic locking (``version``) and secrets are masked in every GET response.
"""

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
    validate_config_dict,
)
from ...contrib.repo.models import GitHubOwner
from ...contrib.repo.owner import replace_owners
from ...contrib.repo.repository import replace_repositories
from ...db.models import Repository
from ...errors import ConfigException

router = APIRouter(prefix="/config", tags=["config"])


class ConfigResponse(BaseModel):
    data: dict
    version: int


class ConfigSaveRequest(BaseModel):
    config: dict
    version: int


class ConfigValidateRequest(BaseModel):
    config: dict


class ConfigValidateResponse(BaseModel):
    success: bool
    error: str | None = None


class TimezonesResponse(BaseModel):
    timezones: list[str]


@router.get("", response_model=ConfigResponse)
def get_config():
    loaded = load_app_config()
    if loaded is None:
        raise HTTPException(
            status_code=409,
            detail="Application config has not been seeded.",
        )
    data, version = loaded
    return ConfigResponse(data=mask_secrets(data), version=version)


@router.post("", response_model=ConfigResponse)
def save_config(request: ConfigSaveRequest):
    try:
        merged, version = save_app_config(request.config, request.version)
    except ConfigVersionConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ConfigException as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ConfigResponse(data=mask_secrets(merged), version=version)


@router.post("/validate", response_model=ConfigValidateResponse)
def validate_config(request: ConfigValidateRequest):
    try:
        validate_config_dict(request.config)
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
def list_repos():
    return [
        RepoView(id=r.id, name=r.name, url=r.url, branch=r.branch, enabled=r.enabled)
        for r in Repository.select().order_by(Repository.id)
    ]


@router.put("/repos", response_model=list[RepoView])
def replace_repos_route(request: Request, repos: list[RepositoryConfig]):
    replace_repositories(repos, request.app.state.config.github.protocol)
    return list_repos()


@router.get("/owners", response_model=list[OwnerView])
def list_owners():
    return [
        OwnerView(id=o.id, owner_type=o.owner_type, name=o.name, enabled=o.enabled)
        for o in GitHubOwner.select().order_by(GitHubOwner.id)
    ]


@router.put("/owners", response_model=list[OwnerView])
def replace_owners_route(owners: list[OwnerConfig]):
    replace_owners(owners)
    return list_owners()
