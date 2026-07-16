"""Logging setup: rotating file at ``data/logs/sanjaya.log`` (5 x 1MB, INFO
default) plus a console handler. Also provides a rate-limited helper so the
sampler loop can log recurring failures without flooding the file (PRD §8.1).
"""
from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler

from . import paths

_configured = False


def setup(level: int = logging.INFO) -> logging.Logger:
    """Idempotently configure the root ``sanjaya`` logger."""
    global _configured
    logger = logging.getLogger("sanjaya")
    if _configured:
        return logger

    paths.ensure_dirs()
    logger.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fileh = RotatingFileHandler(
        paths.LOG_DIR / "sanjaya.log",
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    fileh.setFormatter(fmt)
    logger.addHandler(fileh)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    logger.propagate = False
    _configured = True
    return logger


def get(name: str = "sanjaya") -> logging.Logger:
    if not _configured:
        setup()
    return logging.getLogger(name if name.startswith("sanjaya") else f"sanjaya.{name}")


class RateLimitedLog:
    """Log a repeating message at most once per ``interval_s`` seconds.

    Used by the collector tick so a persistent failure (e.g. access-denied on a
    protected window) is recorded once, not 30 times a minute.
    """

    def __init__(self, logger: logging.Logger, interval_s: float = 60.0):
        self._log = logger
        self._interval = interval_s
        self._last: dict[str, float] = {}

    def warn(self, key: str, msg: str, *args) -> None:
        now = time.monotonic()
        if now - self._last.get(key, 0.0) >= self._interval:
            self._last[key] = now
            self._log.warning(msg, *args)
