import logging
import logging.config

from .utils import canonicalify, ensure_path

_OTEL_FIELDS = ("otelTraceID", "otelSpanID", "otelTraceSampled", "otelServiceName")


class _OtelContextFilter(logging.Filter):
    """Default OpenTelemetry log-record fields so the format never KeyErrors.

    ``opentelemetry-instrumentation-logging`` injects real trace ids via a log
    record factory when telemetry is active; this filter only supplies empty
    defaults when that instrumentor is not running (e.g. in tests or when
    observability is disabled).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for attr in _OTEL_FIELDS:
            if not hasattr(record, attr):
                setattr(record, attr, "")
        return True


LOGGING_CONFIG = {
    "version": 1,
    "filters": {
        "otel_context": {"()": lambda: _OtelContextFilter()},
    },
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(levelname)s] [trace_id=%(otelTraceID)s span_id=%(otelSpanID)s] "
            "[%(processName)s] [%(threadName)s] - %(message)s"
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": logging.INFO,
            "formatter": "default",
            "filters": ["otel_context"],
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": logging.DEBUG,
            "formatter": "default",
            "filters": ["otel_context"],
            "filename": "data/progress.log",
            "maxBytes": 5 * 1024 * 1024,  # 5MB
            "backupCount": 100,
        },
    },
    "loggers": {
        "progress": {
            "handlers": ["console", "file"],
            "level": logging.DEBUG,
            "propagate": True,
        }
    },
}


def setup(logfile=None):
    if not logfile:
        logfile = LOGGING_CONFIG["handlers"]["file"]["filename"]

    p = canonicalify(logfile)
    if len(p.parts) > 1:
        ensure_path(p.parent)

    logging.config.dictConfig(LOGGING_CONFIG)


logger = logging.getLogger("progress")
