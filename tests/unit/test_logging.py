import logging
import logging.handlers
import re

from progress.observability.logging import configure_structlog


def test_console_filters_debug(tmp_path):
    # pytest installs its own capture handlers on the root logger; snapshot them
    # so we can isolate the handlers configure_structlog() adds.
    before = {id(h) for h in logging.getLogger().handlers}
    configure_structlog(tmp_path, console_level=logging.INFO, file_level=logging.DEBUG)
    added = [h for h in logging.getLogger().handlers if id(h) not in before]
    console_handlers = [
        h
        for h in added
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, (logging.FileHandler, logging.handlers.TimedRotatingFileHandler))
    ]
    assert console_handlers, "no stderr console handler registered"
    assert console_handlers[0].level == logging.INFO


def test_file_collects_debug(tmp_path):
    configure_structlog(tmp_path, console_level=logging.INFO, file_level=logging.DEBUG)
    file_handler = next(
        h for h in logging.getLogger().handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)
    )
    assert file_handler.level == logging.DEBUG
    logger = logging.getLogger("test.file.debug")
    logger.debug("debug line that should reach the file sink")
    for h in logging.getLogger().handlers:
        h.flush()
    log_content = (tmp_path / "progress.log").read_text()
    assert "debug line that should reach the file sink" in log_content


def test_timestamp_format(tmp_path):
    configure_structlog(tmp_path)
    logger = logging.getLogger("test.timestamp")
    logger.warning("test message")
    for h in logging.getLogger().handlers:
        h.flush()
    log_content = (tmp_path / "progress.log").read_text()
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", log_content)


def test_uvicorn_access_downgraded(tmp_path):
    configure_structlog(tmp_path)
    assert logging.getLogger("uvicorn.access").level == logging.DEBUG
    assert logging.getLogger("aiohttp.server").level == logging.DEBUG


def test_noisy_third_party_loggers_downgraded(tmp_path):
    """Third-party DEBUG noise (httpx/markdown_it/openai internals) must be
    downgraded to WARNING so it doesn't drown out business DEBUG in the file
    sink, while the root logger stays DEBUG for our own code."""
    configure_structlog(tmp_path)
    for name in ("httpx", "httpcore", "openai", "markdown_it"):
        assert logging.getLogger(name).level == logging.WARNING
    assert logging.getLogger().level == logging.DEBUG
