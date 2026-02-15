import os
import shutil
from pathlib import Path

import pytz
import tomlkit
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...config import StorageType
from ...editor_schema import EditorSchema, FieldSchema, SectionSchema
from ...enums import Protocol
from ...errors import ConfigException

router = APIRouter(prefix="/config", tags=["config"])


class ConfigResponse(BaseModel):
    success: bool = True
    data: dict
    toml: str
    path: str
    comments: dict


class ConfigSaveRequest(BaseModel):
    toml: str | None = None
    config: dict | None = None


class ConfigSaveResponse(BaseModel):
    success: bool
    message: str | None = None
    toml: str | None = None
    error: str | None = None


class ConfigValidateRequest(BaseModel):
    toml: str


class ConfigValidateResponse(BaseModel):
    success: bool
    message: str | None = None
    data: dict | None = None
    error: str | None = None


class ConfigValidateDataRequest(BaseModel):
    config: dict


class TimezonesResponse(BaseModel):
    success: bool = True
    timezones: list[str]


def get_config_path() -> str:
    env_path = os.environ.get("CONFIG_FILE")
    if env_path:
        return env_path

    common_paths = [
        "config/simple.toml",
        "config/docker.toml",
        "config/full.toml",
        "/app/config.toml",
        "config.toml",
    ]

    for path in common_paths:
        if Path(path).is_file():
            return path

    return "/app/config.toml"


def read_config_file() -> tuple[str, str]:
    config_path = get_config_path()
    path = Path(config_path)

    if not path.exists():
        raise ConfigException(f"Configuration file not found: {config_path}")

    return path.read_text(encoding="utf-8"), config_path


def write_config_file(content: str):
    config_path = get_config_path()
    path = Path(config_path)

    try:
        tomlkit.loads(content)
    except Exception as e:
        raise ConfigException(f"Invalid TOML syntax: {str(e)}")

    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(content, encoding="utf-8")
    shutil.move(str(temp_path), str(path))


def _toml_to_plain(value):
    if isinstance(value, list):
        return [_toml_to_plain(v) for v in value]
    if isinstance(value, dict) or hasattr(value, "items"):
        try:
            items = value.items()
        except Exception:
            items = []
        return {k: _toml_to_plain(v) for k, v in items}
    if hasattr(value, "unwrap"):
        try:
            return _toml_to_plain(value.unwrap())
        except Exception:
            return str(value)
    if hasattr(value, "value"):
        try:
            inner = value.value
            if inner is value:
                if isinstance(value, bool):
                    return bool(value)
                if isinstance(value, int):
                    return int(value)
                if isinstance(value, float):
                    return float(value)
                if isinstance(value, str):
                    return str(value)
                return str(value)
            return _toml_to_plain(inner)
        except Exception:
            return str(value)
    return value


def config_to_dict(toml_content: str) -> dict:
    return _toml_to_plain(tomlkit.loads(toml_content))


def extract_comments(toml_content: str) -> dict:
    doc = tomlkit.loads(toml_content)
    comments = {}

    def extract_from_table(table, prefix=""):
        for key, item in table.items():
            path = f"{prefix}.{key}" if prefix else key

            if hasattr(item, "trivia") and item.trivia.comment:
                comments[path] = item.trivia.comment.strip()

            if isinstance(item, tomlkit.items.Table):
                extract_from_table(item, path)
            elif isinstance(item, tomlkit.items.InlineTable):
                for k, v in item.items():
                    nested_path = f"{path}.{k}"
                    if hasattr(v, "trivia") and v.trivia.comment:
                        comments[nested_path] = v.trivia.comment.strip()

    for key, value in doc.items():
        if hasattr(value, "trivia") and value.trivia.comment:
            comments[key] = value.trivia.comment.strip()
        if hasattr(value, "items"):
            extract_from_table(value, key)

    return comments


def _update_toml_document(doc, config_dict):
    from tomlkit.items import AoT

    for key, value in config_dict.items():
        if isinstance(value, dict) and key not in doc:
            doc[key] = tomlkit.table()
            _update_toml_document(doc[key], value)
        elif isinstance(value, dict):
            _update_toml_document(doc[key], value)
        elif isinstance(value, list):
            aot = AoT([])
            for item in value:
                if isinstance(item, dict):
                    table = tomlkit.table()
                    for k, v in item.items():
                        table[k] = v
                    aot.append(table)
                else:
                    aot.append(item)
            doc[key] = aot
        else:
            doc[key] = value

    _remove_empty_values(doc)


def _remove_empty_values(table):
    keys_to_remove = []

    for key, value in table.items():
        if isinstance(value, tomlkit.items.Table):
            _remove_empty_values(value)
        elif isinstance(value, str) and value == "":
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del table[key]


def format_validation_error(e: Exception) -> str:
    from pydantic import ValidationError

    if not isinstance(e, ValidationError):
        return str(e)

    lines = ["Configuration validation failed:"]
    for error in e.errors():
        loc = " -> ".join(str(item) for item in error.get("loc", []))
        msg = error.get("msg", "")
        lines.append(f"  - {loc}: {msg}" if loc else f"  - {msg}")
    return "\n".join(lines)


def validate_against_model(config_dict: dict) -> None:
    from pydantic_settings import (
        BaseSettings,
        PydanticBaseSettingsSource,
        SettingsConfigDict,
    )

    from ...config import Config as AppConfig

    if (
        "github" not in config_dict
        or not isinstance(config_dict["github"], dict)
        or "gh_token" not in config_dict["github"]
    ):
        env_token = os.environ.get("PROGRESS_GITHUB__GH_TOKEN")
        if env_token:
            config_dict.setdefault("github", {})
            if isinstance(config_dict["github"], dict):
                config_dict["github"].setdefault("gh_token", env_token)

    class _DictConfig(AppConfig):
        model_config = SettingsConfigDict(
            env_prefix="PROGRESS_",
            env_nested_delimiter="__",
        )

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (init_settings,)

    _DictConfig(**config_dict)


def build_config_editor_schema() -> EditorSchema:
    protocol_options = [p.value for p in Protocol]
    storage_options = [s.value for s in StorageType]

    general = SectionSchema(
        id="general",
        title="General",
        description="Top-level configuration",
        fields=[
            FieldSchema(
                type="timezone",
                path="timezone",
                label="Timezone",
                default="UTC",
                help_text="Supports all IANA timezone identifiers (e.g., UTC, Asia/Shanghai).",
            ),
            FieldSchema(
                type="text",
                path="language",
                label="UI Language",
                default="en",
                help_text="Controls UI text language (e.g., en, zh-hans).",
            ),
            FieldSchema(
                type="text",
                path="data_dir",
                label="Data Directory",
                default="data",
                help_text="Base directory for data files (database, logs, etc.).",
            ),
            FieldSchema(
                type="text",
                path="workspace_dir",
                label="Workspace Directory",
                default="data/repos",
                help_text="Directory where tracked repositories are cloned.",
            ),
        ],
    )

    web = SectionSchema(
        id="web",
        title="Web",
        description="Web service settings",
        fields=[
            FieldSchema(
                type="boolean",
                path="web.enabled",
                label="Enabled",
                default=False,
                help_text="Enable or disable the web service.",
            ),
            FieldSchema(
                type="text",
                path="web.host",
                label="Host",
                default="0.0.0.0",
                help_text="Bind address (use 0.0.0.0 to listen on all interfaces).",
            ),
            FieldSchema(
                type="number",
                path="web.port",
                label="Port",
                default=5000,
                validation={"min": 1, "max": 65535},
                help_text="Listening port.",
            ),
            FieldSchema(
                type="boolean",
                path="web.debug",
                label="Debug",
                default=False,
                help_text="Do not enable in production.",
            ),
            FieldSchema(
                type="boolean",
                path="web.reload",
                label="Reload",
                default=True,
                help_text="Auto-reload on file changes (development only).",
            ),
        ],
    )

    github = SectionSchema(
        id="github",
        title="GitHub",
        description="GitHub access and cloning behavior",
        fields=[
            FieldSchema(
                type="password",
                path="github.gh_token",
                label="GitHub Token",
                required=True,
                help_text="Required unless provided via environment variable PROGRESS_GITHUB__GH_TOKEN.",
            ),
            FieldSchema(
                type="select",
                path="github.protocol",
                label="Protocol",
                default=Protocol.HTTPS.value,
                options=protocol_options,
                help_text="Default protocol for cloning repositories.",
            ),
            FieldSchema(
                type="text",
                path="github.proxy",
                label="Proxy",
                default="",
                help_text="HTTP/HTTPS/SOCKS5 proxy URL (leave empty to disable).",
            ),
            FieldSchema(
                type="number",
                path="github.git_timeout",
                label="Git Timeout (s)",
                default=300,
                validation={"min": 1},
                help_text="Git command timeout in seconds.",
            ),
            FieldSchema(
                type="number",
                path="github.gh_timeout",
                label="GH Timeout (s)",
                default=300,
                validation={"min": 1},
                help_text="GitHub CLI command timeout in seconds.",
            ),
        ],
    )

    analysis = SectionSchema(
        id="analysis",
        title="Analysis",
        description="Claude Code analysis settings",
        fields=[
            FieldSchema(
                type="number",
                path="analysis.max_diff_length",
                label="Max Diff Length",
                default=100000,
                validation={"min": 1},
                help_text="Diffs longer than this will be truncated.",
            ),
            FieldSchema(
                type="number",
                path="analysis.concurrency",
                label="Concurrency",
                default=1,
                validation={"min": 1},
                help_text="Set > 1 to enable concurrent analysis.",
            ),
            FieldSchema(
                type="number",
                path="analysis.timeout",
                label="Timeout (s)",
                default=600,
                validation={"min": 1},
                help_text="Analysis timeout in seconds.",
            ),
            FieldSchema(
                type="text",
                path="analysis.language",
                label="Output Language",
                default="en",
                help_text="Language of AI analysis output (e.g., en, zh, ja).",
            ),
            FieldSchema(
                type="number",
                path="analysis.first_run_lookback_commits",
                label="First Run Lookback Commits",
                default=3,
                validation={"min": 1},
                help_text="How many commits to look back on first run.",
            ),
        ],
    )

    report = SectionSchema(
        id="report",
        title="Report",
        description="Report storage settings",
        fields=[
            FieldSchema(
                type="select",
                path="report.storage",
                label="Storage",
                default=StorageType.AUTO.value,
                options=storage_options,
                help_text="Where generated reports are stored.",
            )
        ],
    )

    markpost = SectionSchema(
        id="markpost",
        title="Markpost",
        description="Markpost publishing settings",
        fields=[
            FieldSchema(
                type="boolean",
                path="markpost.enabled",
                label="Enabled",
                default=False,
                help_text="Enable Markpost uploads. When enabled, markpost.url must be set.",
            ),
            FieldSchema(
                type="text",
                path="markpost.url",
                label="Publish URL",
                default="",
                help_text="Example: https://markpost.example.com/p/your-post-key",
            ),
            FieldSchema(
                type="number",
                path="markpost.timeout",
                label="Timeout (s)",
                default=30,
                validation={"min": 1},
                help_text="HTTP request timeout in seconds.",
            ),
            FieldSchema(
                type="number",
                path="markpost.max_batch_size",
                label="Max Batch Size (bytes)",
                default=1048576,
                validation={"min": 1},
                help_text="Reports larger than this will be split into multiple batches.",
            ),
        ],
    )

    notification = SectionSchema(
        id="notification",
        title="Notification",
        description="Notification channels",
        fields=[
            FieldSchema(
                type="discriminated_object_list",
                path="notification.channels",
                label="Channels",
                item_label="Channel",
                discriminator="type",
                variants={
                    "console": [
                        FieldSchema(
                            type="boolean",
                            path="enabled",
                            label="Enabled",
                            default=True,
                        ),
                    ],
                    "feishu": [
                        FieldSchema(
                            type="boolean",
                            path="enabled",
                            label="Enabled",
                            default=True,
                        ),
                        FieldSchema(
                            type="text",
                            path="webhook_url",
                            label="Webhook URL",
                            required=True,
                            help_text="Feishu bot webhook URL.",
                        ),
                        FieldSchema(
                            type="number",
                            path="timeout",
                            label="Timeout (s)",
                            default=30,
                            validation={"min": 1},
                        ),
                    ],
                    "email": [
                        FieldSchema(
                            type="boolean",
                            path="enabled",
                            label="Enabled",
                            default=False,
                        ),
                        FieldSchema(type="text", path="host", label="Host", default=""),
                        FieldSchema(
                            type="number",
                            path="port",
                            label="Port",
                            default=587,
                            validation={"min": 1, "max": 65535},
                        ),
                        FieldSchema(type="text", path="user", label="User", default=""),
                        FieldSchema(
                            type="password",
                            path="password",
                            label="Password",
                            default="",
                        ),
                        FieldSchema(
                            type="text",
                            path="from_addr",
                            label="From",
                            default="progress@example.com",
                        ),
                        FieldSchema(
                            type="string_list",
                            path="recipient",
                            label="Recipients",
                            default=[],
                            help_text="One or more recipient email addresses.",
                        ),
                        FieldSchema(
                            type="boolean",
                            path="starttls",
                            label="STARTTLS",
                            default=False,
                        ),
                        FieldSchema(
                            type="boolean",
                            path="ssl",
                            label="SSL",
                            default=False,
                        ),
                    ],
                },
                help_text="Each channel is configured with a 'type' discriminator.",
            )
        ],
    )

    repos = SectionSchema(
        id="repos",
        title="Repositories",
        description="Repositories to track",
        fields=[
            FieldSchema(
                type="object_list",
                path="repos",
                label="Repositories",
                item_label="Repository",
                item_fields=[
                    FieldSchema(
                        type="text",
                        path="url",
                        label="URL",
                        required=True,
                        help_text="Supported formats: owner/repo, https://..., git@....",
                    ),
                    FieldSchema(type="text", path="branch", label="Branch", default="main"),
                    FieldSchema(type="boolean", path="enabled", label="Enabled", default=True),
                    FieldSchema(
                        type="select",
                        path="protocol",
                        label="Protocol",
                        default=Protocol.HTTPS.value,
                        options=protocol_options,
                        help_text="Overrides github.protocol for this repository.",
                    ),
                ],
                help_text="GitHub repositories in owner/repo, https://..., or git@... format.",
            )
        ],
    )

    owners = SectionSchema(
        id="owners",
        title="Owners",
        description="Monitor GitHub users and organizations",
        fields=[
            FieldSchema(
                type="object_list",
                path="owners",
                label="Owners",
                item_label="Owner",
                item_fields=[
                    FieldSchema(
                        type="select",
                        path="type",
                        label="Type",
                        required=True,
                        options=["user", "organization"],
                    ),
                    FieldSchema(type="text", path="name", label="Name", required=True),
                    FieldSchema(type="boolean", path="enabled", label="Enabled", default=True),
                ],
            )
        ],
    )

    proposals = SectionSchema(
        id="proposal_trackers",
        title="Proposal Trackers",
        description="Track EIPs, Rust RFCs, PEPs, and Django DEPs",
        fields=[
            FieldSchema(
                type="object_list",
                path="proposal_trackers",
                label="Trackers",
                item_label="Tracker",
                item_fields=[
                    FieldSchema(
                        type="select",
                        path="type",
                        label="Type",
                        required=True,
                        options=["eip", "rust_rfc", "pep", "django_dep"],
                    ),
                    FieldSchema(
                        type="text",
                        path="repo_url",
                        label="Repo URL",
                        required=True,
                        help_text="Expected format: https://github.com/<owner>/<repo>(.git)",
                    ),
                    FieldSchema(type="text", path="branch", label="Branch", default="main"),
                    FieldSchema(type="boolean", path="enabled", label="Enabled", default=True),
                    FieldSchema(type="text", path="proposal_dir", label="Proposal Dir", default=""),
                    FieldSchema(type="text", path="file_pattern", label="File Pattern", default=""),
                ],
            )
        ],
    )

    changelog = SectionSchema(
        id="changelog_trackers",
        title="Changelog Trackers",
        description="Track changelogs from URLs",
        fields=[
            FieldSchema(
                type="object_list",
                path="changelog_trackers",
                label="Trackers",
                item_label="Tracker",
                item_fields=[
                    FieldSchema(type="text", path="name", label="Name", required=True),
                    FieldSchema(type="text", path="url", label="URL", required=True),
                    FieldSchema(
                        type="select",
                        path="parser_type",
                        label="Parser Type",
                        required=True,
                        options=["markdown_heading", "html_chinese_version"],
                    ),
                    FieldSchema(type="boolean", path="enabled", label="Enabled", default=True),
                ],
            )
        ],
    )

    return EditorSchema(
        sections=[
            general,
            web,
            github,
            analysis,
            report,
            markpost,
            notification,
            repos,
            owners,
            proposals,
            changelog,
        ]
    )


@router.get("", response_model=ConfigResponse)
def get_config():
    try:
        toml_content, config_path = read_config_file()
        config_dict = config_to_dict(toml_content)
        comments = extract_comments(toml_content)

        return ConfigResponse(
            data=config_dict,
            toml=toml_content,
            path=config_path,
            comments=comments,
        )
    except ConfigException as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("", response_model=ConfigSaveResponse)
def save_config(request: ConfigSaveRequest):
    if request.toml is None and request.config is None:
        return JSONResponse(
            status_code=400,
            content=ConfigSaveResponse(
                success=False,
                error="Missing 'toml' or 'config' field",
            ).model_dump(),
        )

    if request.toml is not None:
        toml_content = request.toml
    else:
        existing_toml, _ = read_config_file()
        doc = tomlkit.loads(existing_toml)
        _update_toml_document(doc, request.config or {})
        toml_content = doc.as_string()

    try:
        write_config_file(toml_content)
        return ConfigSaveResponse(
            success=True,
            message="Configuration saved successfully",
            toml=toml_content,
        )
    except ConfigException as e:
        return JSONResponse(
            status_code=400,
            content=ConfigSaveResponse(success=False, error=str(e)).model_dump(),
        )


@router.post("/validate", response_model=ConfigValidateResponse)
def validate_config(request: ConfigValidateRequest):
    try:
        config_dict = config_to_dict(request.toml)
        validate_against_model(config_dict)
        return ConfigValidateResponse(
            success=True,
            message="Configuration is valid",
            data=config_dict,
        )
    except Exception as e:
        return ConfigValidateResponse(success=False, error=format_validation_error(e))


@router.post("/validate-data", response_model=ConfigValidateResponse)
def validate_config_data(request: ConfigValidateDataRequest):
    try:
        validate_against_model(request.config)
        return ConfigValidateResponse(
            success=True,
            message="Configuration is valid",
            data=request.config,
        )
    except Exception as e:
        return ConfigValidateResponse(success=False, error=format_validation_error(e))


@router.get("/schema")
def get_config_schema():
    schema = build_config_editor_schema()
    return {"sections": [section.model_dump() for section in schema.sections]}


@router.get("/timezones", response_model=TimezonesResponse)
def get_timezones():
    return TimezonesResponse(timezones=sorted(pytz.all_timezones))
