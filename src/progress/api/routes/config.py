"""Config API routes — backed by the database config blob.

The TOML file seeds the blob on first run; thereafter the blob is the single
source of truth and these endpoints read/write it. Writes are guarded by
optimistic locking (``version``) and secrets are masked in every GET response.
"""

import pytz
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...config_store import (
    ConfigVersionConflict,
    get_config_json_schema,
    load_app_config,
    mask_secrets,
    save_app_config,
    validate_config_dict,
)
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
