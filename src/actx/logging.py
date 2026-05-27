"""Structured logging setup. Keeps human-readable in dev, JSON in prod."""

from __future__ import annotations

import logging
import os
import sys

import structlog


def configure_logging(level: str = "info") -> None:
    """Configure ``structlog`` once at startup.

    Set ``ACTX_LOG_JSON=true`` to emit JSON lines (suitable for shipping to
    Loki, Datadog, etc.). Otherwise pretty-prints to stderr.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=log_level)

    use_json = os.environ.get("ACTX_LOG_JSON", "").lower() in {"1", "true", "yes"}
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if use_json else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
