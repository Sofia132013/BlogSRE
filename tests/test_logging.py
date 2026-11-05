"""Sensitive values must not escape through application console formatting."""

import json
import logging
import sys
from io import StringIO

import pytest
from django.conf import settings
from django.db import connection
from django.http import HttpResponseServerError
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.utils.log import log_response

from blog.logging import JsonFormatter, RedactingFormatter


def test_json_log_is_one_line_with_utc_time_and_searchable_fields():
    record = logging.LogRecord("blog.access", logging.INFO, __file__, 1, "Запрос\nзавершён", (), None)
    record.created = 0.125
    record.request_id = "request-for-test"
    record.method = "GET"
    record.status = 200
    record.duration_ms = 12.5
    record.cookie = "private-cookie-value"

    output = JsonFormatter().format(record)
    event = json.loads(output)

    assert len(output.splitlines()) == 1
    assert event["timestamp"] == "1970-01-01T00:00:00.125Z"
    assert event["level"] == "info"
    assert event["service.name"] == "blog"
    assert event["message"] == "Запрос\nзавершён"
    assert event["request_id"] == "request-for-test"
    assert event["method"] == "GET"
    assert event["status"] == 200
    assert event["duration_ms"] == 12.5
    assert "private-cookie-value" not in output


def test_json_redacts_message_and_traceback_before_serialization(monkeypatch):
    monkeypatch.setenv("DJANGO_SECRET_KEY", "json-secret-for-test")
    try:
        raise ValueError("json-secret-for-test")
    except ValueError:
        record = logging.LogRecord(
            "blog.test", logging.ERROR, __file__, 1,
            'password=unsafe-password\nCookie: sessionid=private-cookie', (), sys.exc_info(),
        )
    output = JsonFormatter().format(record)
    event = json.loads(output)
    assert len(output.splitlines()) == 1
    assert event["level"] == "error"
    assert "ValueError" in event["error.stack"]
    assert "[REDACTED]" in event["message"]
    for value in ("json-secret-for-test", "unsafe-password", "private-cookie"):
        assert value not in output


def format_error(message, exc_info=None):
    record = logging.LogRecord("django.request", logging.ERROR, __file__, 1, message, (), exc_info)
    return RedactingFormatter("%(levelname)s %(message)s").format(record)


def test_redacts_known_environment_credentials(monkeypatch):
    monkeypatch.setenv("DJANGO_SECRET_KEY", "secret-key-for-log-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://blog:database-password-for-test@db:5432/blog")
    monkeypatch.setenv("POSTGRES_PASSWORD", "database-password-for-test")
    monkeypatch.setenv("EMAIL_HOST_PASSWORD", "smtp-password-for-test")
    monkeypatch.setenv("BLOG_DEMO_PASSWORD", "demo-password-for-test")

    try:
        raise ValueError("Connection failed with database-password-for-test")
    except ValueError:
        output = format_error(
            "Settings: secret-key-for-log-test postgresql://blog:database-password-for-test@db:5432/blog "
            "smtp-password-for-test demo-password-for-test",
            sys.exc_info(),
        )

    assert "secret-key-for-log-test" not in output
    assert "database-password-for-test" not in output
    assert "postgresql://blog:" not in output
    assert "smtp-password-for-test" not in output
    assert "demo-password-for-test" not in output
    assert "ValueError" in output
    assert "[REDACTED]" in output


def test_redacts_request_tokens_headers_and_cookies():
    output = format_error(
        "Internal Server Error: /auth/reset/MQ/reset-token-value/ "
        "password=unsafe-password Authorization: Bearer auth-token-value\n"
        "Cookie: sessionid=session-cookie-value"
    )

    assert "reset-token-value" not in output
    assert "unsafe-password" not in output
    assert "auth-token-value" not in output
    assert "session-cookie-value" not in output
    assert "Internal Server Error" in output


def test_django_error_log_hides_password_reset_token():
    stream = StringIO()
    logger = logging.Logger("django.request.test", level=logging.ERROR)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    request = RequestFactory().get("/auth/reset/MQ/reset-token-value/")

    log_response(
        "Internal Server Error: %s", request.path,
        response=HttpResponseServerError(), request=request, logger=logger,
    )

    assert "Internal Server Error" in stream.getvalue()
    assert "reset-token-value" not in stream.getvalue()


def test_django_loggers_use_only_redacting_console_handlers():
    for name in ("", "django", "django.request", "django.server", "django.db.backends"):
        handlers = logging.getLogger(name).handlers
        console = [handler for handler in handlers if handler.name == "console"]
        assert len(console) == 1
        assert type(console[0]) is logging.StreamHandler
        assert isinstance(console[0].formatter, RedactingFormatter)
        assert isinstance(console[0].formatter, JsonFormatter)
        assert not isinstance(console[0], logging.FileHandler)
    # pytest adds its own capture/file handlers to the root logger; inspect
    # only the application's logging configuration for persistent destinations.
    assert all(
        "FileHandler" not in handler["class"] and "AdminEmailHandler" not in handler["class"]
        for handler in settings.LOGGING["handlers"].values()
    )


@pytest.mark.django_db
def test_application_debug_works_without_sql_parameters(settings, monkeypatch, caplog):
    settings.DEBUG = True
    assert connection.vendor == "postgresql"
    stream = StringIO()
    console = next(handler for handler in logging.getLogger().handlers if handler.name == "console")
    monkeypatch.setattr(console, "stream", stream)
    marker = "FAKE_SQL_SECRET_12345"

    # Exercise both application DEBUG logging and Django's real SQL debug path.
    with caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, logger="django"):
        logging.getLogger("blog.test").info("Normal application event")
        logging.getLogger("blog.test").debug("Application debug event")
        with CaptureQueriesContext(connection) as queries:
            with connection.cursor() as cursor:
                cursor.execute("SELECT %s", [marker])
                assert cursor.fetchone() == (marker,)
        logging.getLogger("django.db.backends").warning("Database warning event")

    assert len(queries) == 1
    assert marker in queries[0]["sql"]  # The sensitive query really executed.
    output = stream.getvalue()
    assert "Normal application event" in output
    assert "Application debug event" in output
    assert "Database warning event" in output
    assert marker not in output + caplog.text
    assert "SELECT" not in output
