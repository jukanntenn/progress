"""Flask web service for viewing aggregated reports."""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path as PathlibPath

import tomlkit
from flask import Blueprint, Flask, current_app, jsonify, render_template, request
from feedgen.feed import FeedGenerator
from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.footnote import footnote_plugin

import pytz

from .consts import DATABASE_PATH
from .db import close_db, create_tables, init_db
from .editor_schema import EditorSchema
from .errors import ConfigException
from .models import Report

logger = logging.getLogger(__name__)

PAGE_SIZE = 50

bp = Blueprint("web", __name__, template_folder="templates/web")

mdit = MarkdownIt("commonmark", {"breaks": True, "html": True}).use(
    front_matter_plugin
).use(footnote_plugin)


def create_app(config=None):
    """Create and configure Flask application.

    Args:
        config: Application configuration object (optional, will load from file if not provided)

    Returns:
        Configured Flask application
    """
    from .config import Config

    if config is None:
        config_file = os.environ.get("CONFIG_FILE", "/app/config.toml")
        config = Config.load_from_file(config_file)

    app = Flask(__name__)
    app.config["config"] = config
    app.config["timezone"] = config.get_timezone()

    init_db(DATABASE_PATH)
    create_tables()

    app.register_blueprint(bp)

    @app.teardown_appcontext
    def shutdown_db_session(exception=None):
        """Close database connection after each request."""
        close_db()

    return app


def render_markdown(content: str) -> str:
    """Render markdown content to HTML using markdown-it-py.

    Args:
        content: Markdown content

    Returns:
        Rendered HTML content
    """
    if not content:
        return ""
    return mdit.render(content)


def get_config_path(app=None):
    """Get the configuration file path from app config, environment, or default."""
    if app and "config_file" in app.config:
        return app.config["config_file"]

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
        if PathlibPath(path).is_file():
            return path

    return "/app/config.toml"


def read_config_file(app=None):
    """Read configuration file and return content and path."""
    config_path = get_config_path(app)
    path = PathlibPath(config_path)

    if not path.exists():
        raise ConfigException(f"Configuration file not found: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    return content, config_path


def write_config_file(content: str, app=None):
    """Write configuration file atomically with validation."""
    config_path = get_config_path(app)
    path = PathlibPath(config_path)

    try:
        tomlkit.loads(content)
    except Exception as e:
        raise ConfigException(f"Invalid TOML syntax: {str(e)}")

    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(content)

    shutil.move(str(temp_path), str(path))


def config_to_dict(toml_content: str) -> dict:
    """Parse TOML content to dictionary."""
    return tomlkit.loads(toml_content)


def extract_comments(toml_content: str) -> dict:
    """Extract comments from TOML content and associate with config keys.

    Returns:
        Dict mapping config paths to their comments.
    """
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


@bp.route("/")
def index():
    """Render paginated list of aggregated reports."""
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    query = Report.select().where(Report.repo.is_null()).order_by(Report.created_at.desc())

    total = query.count()
    reports = list(query.paginate(page, PAGE_SIZE))

    timezone = current_app.config["timezone"]

    report_list = []
    for report in reports:
        created_at_str = ""
        if report.created_at:
            if isinstance(report.created_at, datetime):
                created_at_str = report.created_at.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(report.created_at, str):
                try:
                    dt = datetime.fromisoformat(report.created_at)
                    created_at_str = dt.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    created_at_str = report.created_at

        report_list.append({
            "id": report.id,
            "title": report.title,
            "created_at": created_at_str,
            "markpost_url": report.markpost_url,
        })

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE

    has_prev = page > 1
    has_next = page < total_pages

    return render_template(
        "list.html",
        reports=report_list,
        page=page,
        total_pages=total_pages,
        has_prev=has_prev,
        has_next=has_next,
        total=total,
    )


@bp.route("/report/<int:report_id>")
def detail(report_id: int):
    """Render single report detail page.

    Args:
        report_id: Report ID
    """
    report = Report.get_or_none(Report.id == report_id)
    if not report:
        return render_template("404.html"), 404

    if report.repo is not None:
        return render_template("404.html"), 404

    content_html = render_markdown(report.content or "")

    timezone = current_app.config["timezone"]
    created_at_str = ""
    if report.created_at:
        if isinstance(report.created_at, datetime):
            created_at_str = report.created_at.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(report.created_at, str):
            try:
                dt = datetime.fromisoformat(report.created_at)
                created_at_str = dt.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                created_at_str = report.created_at

    return render_template(
        "detail.html",
        report=report,
        content_html=content_html,
        created_at=created_at_str,
        markpost_url=report.markpost_url,
    )


@bp.route("/rss")
def rss():
    """Generate RSS feed for aggregated reports."""
    config = current_app.config["config"]
    timezone = current_app.config["timezone"]

    fg = FeedGenerator()
    fg.title("Progress Reports")
    fg.link(href=request.url_root)
    fg.description("Open source project progress reports")
    fg.language(config.language)

    reports = (
        Report.select()
        .where(Report.repo.is_null())
        .order_by(Report.created_at.desc())
        .limit(50)
    )

    for report in reports:
        fe = fg.add_entry()
        fe.title(report.title or "Untitled Report")
        fe.link(href=f"{request.url_root}report/{report.id}")

        content = render_markdown(report.content or "")
        # Use content() instead of description() for better encoding support
        # This creates a <content:encoded> element which handles UTF-8 properly
        fe.content(content)

        if report.created_at:
            if isinstance(report.created_at, datetime):
                created_at = report.created_at.astimezone(timezone)
            else:
                created_at = report.created_at
            fe.published(created_at.strftime("%a, %d %b %Y %H:%M:%S %Z") if isinstance(created_at, datetime) else str(created_at))
            fe.updated(created_at.strftime("%a, %d %b %Y %H:%M:%S %Z") if isinstance(created_at, datetime) else str(created_at))

    rss_feed = fg.rss_str(pretty=True)
    response = current_app.response_class(rss_feed, mimetype="application/rss+xml")
    response.headers.add("Content-Type", "application/rss+xml; charset=utf-8")
    return response


@bp.route("/config")
def config_page():
    """Render configuration editor page."""
    try:
        toml_content, config_path = read_config_file(current_app)
    except ConfigException as e:
        return render_template("404.html", error=str(e)), 404

    config = current_app.config["config"]

    return render_template(
        "web/config.html",
        toml_content=toml_content,
        config_path=config_path,
        current_language=config.language,
        current_timezone=config.timezone,
    )


@bp.route("/api/config")
def get_config():
    """GET API endpoint - returns current configuration as JSON with comments."""
    try:
        toml_content, config_path = read_config_file(current_app)
        config_dict = config_to_dict(toml_content)
        comments = extract_comments(toml_content)

        return jsonify({
            "success": True,
            "data": config_dict,
            "toml": toml_content,
            "path": config_path,
            "comments": comments
        })
    except ConfigException as e:
        return jsonify({"success": False, "error": str(e)}), 400


@bp.route("/api/config", methods=["POST"])
def save_config():
    """POST API endpoint - saves configuration from TOML or JSON data."""
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    if "toml" in data:
        toml_content = data["toml"]
    elif "config" in data:
        config_dict = data["config"]

        toml_content, _ = read_config_file(current_app)
        doc = tomlkit.loads(toml_content)

        _update_toml_document(doc, config_dict)

        toml_content = doc.as_string()
    else:
        return jsonify({"success": False, "error": "Missing 'toml' or 'config' field"}), 400

    try:
        write_config_file(toml_content, current_app)
        return jsonify({
            "success": True,
            "message": "Configuration saved successfully",
            "toml": toml_content
        })
    except ConfigException as e:
        return jsonify({"success": False, "error": str(e)}), 400


def _update_toml_document(doc, config_dict):
    """Update a tomlkit document with new values while preserving structure."""
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
    """Recursively remove empty string values from a tomlkit table."""
    keys_to_remove = []

    for key, value in table.items():
        if isinstance(value, tomlkit.items.Table):
            _remove_empty_values(value)
        elif isinstance(value, str) and value == "":
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del table[key]


@bp.route("/api/config/validate", methods=["POST"])
def validate_config():
    """Validate configuration without saving."""
    data = request.get_json()

    if not data or "toml" not in data:
        return jsonify({"success": False, "error": "Missing TOML content"}), 400

    toml_content = data["toml"]

    try:
        config_dict = config_to_dict(toml_content)
        return jsonify(
            {"success": True, "message": "Configuration is valid", "data": config_dict}
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@bp.route("/api/config/schema")
def get_config_schema():
    """GET API endpoint - returns editor schema for configuration."""
    schema = EditorSchema(sections=[])

    return jsonify({
        "sections": [section.model_dump() for section in schema.sections]
    })


@bp.route("/api/timezones")
def get_timezones():
    """GET API endpoint - returns all IANA timezones sorted alphabetically."""
    timezones = sorted(pytz.all_timezones)

    return jsonify({
        "success": True,
        "timezones": timezones
    })
