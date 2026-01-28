"""Flask web service for viewing aggregated reports."""

import logging
import os
from datetime import datetime

from flask import Blueprint, Flask, current_app, render_template, request
from feedgen.feed import FeedGenerator
from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.footnote import footnote_plugin

from .consts import DATABASE_PATH
from .db import close_db, create_tables, init_db
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
            if isinstance(report.created_at, str):
                created_at_str = report.created_at
            elif isinstance(report.created_at, datetime):
                created_at_str = report.created_at.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

        report_list.append({
            "id": report.id,
            "title": report.title,
            "created_at": created_at_str,
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
        if isinstance(report.created_at, str):
            created_at_str = report.created_at
        elif isinstance(report.created_at, datetime):
            created_at_str = report.created_at.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

    return render_template(
        "detail.html",
        report=report,
        content_html=content_html,
        created_at=created_at_str,
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

        content = report.content or ""
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
