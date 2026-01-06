import logging.config

from .utils import canonicalify, ensure_path

LOGGING_CONFIG = {
    "version": 1,
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(levelname)s] [%(processName)s] [%(threadName)s] - %(message)s"
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": logging.INFO,
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": logging.DEBUG,
            "formatter": "default",
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
