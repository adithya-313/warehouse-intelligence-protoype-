"""Centralized structured logging configuration.

Provides a JSON log formatter that emits structured log records with
consistent top-level keys (timestamp, level, logger, message, correlation_id)
suitable for ingestion by log aggregators (ELK, Grafana Loki, Datadog).

Usage:
    from app.core.logging import configure_logging
    configure_logging(level=logging.INFO)
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Optional


class JSONLogFormatter(logging.Formatter):
    """Emit log records as newline-delimited JSON objects.

    Every record includes:
      - timestamp  (ISO-8601 with timezone)
      - level      (INFO, ERROR, etc.)
      - logger     (the ``__name__`` of the emitting module)
      - message    (the formatted log message)

    If a ``correlation_id`` key is present in ``record.__dict__`` it is
    included in the output so request-scoped tracing works out of the box.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "correlation_id"):
            log_entry["correlation_id"] = record.correlation_id

        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def configure_logging(
    level: int = logging.INFO,
    json_output: bool = True,
    correlation_id: Optional[str] = None,
) -> None:
    """Configure the root logger with a JSON formatter and stdout handler.

    Call once per process (API, Celery worker, stream consumer) so all
    ``logging.getLogger(__name__)`` calls inherit a consistent format.

    Args:
        level:     The log level for the root logger (default: INFO).
        json_output: If True, use JSONLogFormatter; otherwise use a
                     human-readable plain-text formatter.
        correlation_id: An optional correlation ID to attach to every log
                        record emitted by this process.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove any pre-existing handlers so we don't double-emit
    root_logger.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(level)

    if json_output:
        formatter = JSONLogFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    if correlation_id:
        root_logger = logging.getLogger()
        root_logger = logging.LoggerAdapter(
            root_logger, {"correlation_id": correlation_id}
        )
