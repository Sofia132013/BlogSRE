"""Redact known credentials from the application's console log stream."""

import json
import logging
import os
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse


RESET_TOKEN = re.compile(r"(?i)(/auth/reset/[^/\s]+/)[^/?#\s]+")
SENSITIVE_FIELD = re.compile(
    r"(?i)(\b(?:password|token|secret_key|api[_-]?key|sessionid|"
    r"csrfmiddlewaretoken)\s*[:=]\s*)[^\s&;,]+"
)
SENSITIVE_HEADER = re.compile(r"(?i)(\b(?:authorization|cookie|set-cookie)\s*:\s*)[^\r\n]+")
SECRET_ENV_NAMES = (
    "DJANGO_SECRET_KEY",
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "EMAIL_HOST_PASSWORD",
    "BLOG_DEMO_PASSWORD",
)

request_id = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Attach the current request ID to application log records."""

    def filter(self, record):
        record.request_id = request_id.get()
        return True


class RedactingFormatter(logging.Formatter):
    """Sanitize final log text, including formatted exception tracebacks."""

    def format(self, record):
        return self.redact(super().format(record))

    @staticmethod
    def redact(message):
        secrets = {os.getenv(name) for name in SECRET_ENV_NAMES}
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            password = urlparse(database_url).password
            if password:
                secrets.update((password, unquote(password)))
        known_secrets = sorted(
            (value for value in secrets if value and len(value) >= 6),
            key=len,
            reverse=True,
        )
        for secret in known_secrets:
            message = message.replace(secret, "[REDACTED]")
        message = SENSITIVE_HEADER.sub(r"\1[REDACTED]", message)
        message = SENSITIVE_FIELD.sub(r"\1[REDACTED]", message)
        return RESET_TOKEN.sub(r"\1[REDACTED]", message)


class JsonFormatter(RedactingFormatter):
    """One JSON object per line; only explicitly allowed extra fields are logged."""

    def format(self, record):
        event = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "message": self.redact(record.getMessage()),
            "service.name": "blog",
            "logger": record.name,
            "request_id": getattr(record, "request_id", request_id.get()),
        }
        for field in ("method", "route", "status", "duration_ms", "response_bytes", "event"):
            value = getattr(record, field, None)
            if value is not None:
                event[field] = self.redact(value) if isinstance(value, str) else value
        if record.exc_info:
            event["error.stack"] = self.redact(self.formatException(record.exc_info))
        return json.dumps(event, ensure_ascii=False, allow_nan=False)
