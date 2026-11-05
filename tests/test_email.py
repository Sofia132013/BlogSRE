"""Email configuration must not turn password reset messages into console logs."""

import runpy
from pathlib import Path

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMessage, get_connection
from django.core.mail.backends.dummy import EmailBackend as DummyEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend
from django.urls import reverse


def load_settings(monkeypatch, **environment):
    """Evaluate environment configuration without changing Django's live settings."""
    monkeypatch.delenv("DJANGO_EMAIL_BACKEND", raising=False)
    for name, value in {
        "DJANGO_SECRET_KEY": "fake-email-test-secret",
        "DATABASE_URL": "postgresql://fake:fake-email-test-password@db:5432/fake",
        "DJANGO_ALLOWED_HOSTS": "testserver",
        "DJANGO_DEBUG": "false",
        **environment,
    }.items():
        monkeypatch.setenv(name, value)
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / "blog" / "settings.py"))


@pytest.mark.parametrize("debug", ["true", "false"])
def test_console_email_backend_is_rejected(monkeypatch, debug):
    with pytest.raises(ImproperlyConfigured, match="Console email backend"):
        load_settings(
            monkeypatch,
            DJANGO_DEBUG=debug,
            DJANGO_EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
        )


def test_default_dummy_backend_does_not_print_email(monkeypatch, capsys):
    config = load_settings(monkeypatch)
    backend = get_connection(backend=config["EMAIL_BACKEND"])
    assert isinstance(backend, DummyEmailBackend)
    message = EmailMessage(
        "Fake reset email", "FAKE_DUMMY_EMAIL_TOKEN", "sender@example.invalid",
        ["recipient@example.invalid"], connection=backend,
    )
    assert message.send() == 1
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_smtp_can_be_configured_through_environment(monkeypatch):
    config = load_settings(
        monkeypatch,
        DJANGO_EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.invalid",
        EMAIL_PORT="2525",
        EMAIL_HOST_USER="fake-smtp-user",
        EMAIL_HOST_PASSWORD="fake-smtp-password",
        EMAIL_USE_TLS="false",
        DEFAULT_FROM_EMAIL="blog@example.invalid",
    )
    backend = get_connection(
        backend=config["EMAIL_BACKEND"], host=config["EMAIL_HOST"],
        port=config["EMAIL_PORT"], username=config["EMAIL_HOST_USER"],
        password=config["EMAIL_HOST_PASSWORD"], use_tls=config["EMAIL_USE_TLS"],
    )
    assert isinstance(backend, SMTPEmailBackend)
    assert backend.host == "smtp.example.invalid"
    assert backend.port == 2525
    assert backend.username == "fake-smtp-user"
    assert backend.password == "fake-smtp-password"
    assert backend.use_tls is False
    assert config["DEFAULT_FROM_EMAIL"] == "blog@example.invalid"
    assert backend.connection is None  # No external SMTP connection is opened.


@pytest.mark.django_db
@pytest.mark.parametrize("debug", [True, False])
def test_password_reset_does_not_print_email(
    settings, django_user_model, client, monkeypatch, capsys, caplog, debug,
):
    settings.DEBUG = debug
    settings.EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
    user = django_user_model.objects.create_user(
        username="fake-reset-user", email="reset@example.invalid",
        password="fake-reset-password",
    )
    token = "FAKE_PASSWORD_RESET_TOKEN_12345"
    monkeypatch.setattr(default_token_generator, "make_token", lambda user: token)
    messages = []
    original_send = DummyEmailBackend.send_messages

    def capture_send(backend, email_messages):
        messages.extend(email_messages)
        return original_send(backend, email_messages)

    monkeypatch.setattr(DummyEmailBackend, "send_messages", capture_send)
    response = client.post(reverse("password_reset"), {"email": user.email})

    assert response.status_code == 302
    assert response.url == reverse("password_reset_done")
    assert len(messages) == 1
    assert messages[0].to == [user.email]
    assert token in messages[0].body
    reset_url = next(line.strip() for line in messages[0].body.splitlines() if token in line)
    assert "/auth/reset/" in reset_url
    captured = capsys.readouterr()
    output = captured.out + captured.err + caplog.text
    assert token not in output
    assert reset_url not in output
    assert user.email not in output
