"""SLI eligibility and fault injection must agree with actual saved data."""
import json
import time
from unittest.mock import Mock

import pytest
from django.db import DatabaseError
from prometheus_client import REGISTRY

from blog import slo_demo
from tests.test_metrics import operation, business_values  # noqa: F401


def attempts(op):
    return REGISTRY.get_sample_value("blog_business_attempts_total", {"operation": op})


@pytest.fixture
def control(tmp_path, monkeypatch):
    path = tmp_path / "demo.json"
    monkeypatch.setattr(slo_demo, "CONTROL_FILE", path)
    return path


@pytest.mark.django_db
@pytest.mark.parametrize("operation,op", [("post", "post"), ("comment", "comment"), ("registration", "registration")], indirect=["operation"])
def test_only_valid_submission_attempts_and_fault_does_not_save(client, operation, op, control):
    url, payload, model = operation
    before = business_values()
    attempted, count = attempts(op), model.objects.count()
    control.write_text(json.dumps({"mode": "errors", "expires_at": time.time()+60}))
    assert client.post(url, {"text": ""}).status_code == 200
    assert attempts(op) == attempted
    assert client.post(url, payload).status_code == 503
    assert attempts(op) == attempted + 1
    assert model.objects.count() == count
    assert business_values() == before


@pytest.mark.django_db
@pytest.mark.parametrize("operation,op", [("post", "post"), ("comment", "comment"), ("registration", "registration")], indirect=["operation"])
def test_expired_fault_restores_save_and_counts_success(client, operation, op, control, django_capture_on_commit_callbacks):
    url, payload, model = operation
    before = business_values()
    attempted, count = attempts(op), model.objects.count()
    control.write_text(json.dumps({"mode": "errors", "expires_at": time.time()-1}))
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(url, payload).status_code == 302
    assert attempts(op) == attempted + 1
    assert model.objects.count() == count + 1
    assert sum(business_values().values()) == sum(before.values()) + 1


@pytest.mark.django_db
@pytest.mark.parametrize("operation,op", [("post", "post"), ("comment", "comment"), ("registration", "registration")], indirect=["operation"])
def test_storage_failure_counts_attempt_without_success(client, operation, op, monkeypatch):
    url, payload, model = operation
    before = business_values()
    attempted = attempts(op)
    monkeypatch.setattr(model, "save", Mock(side_effect=DatabaseError("test outage")))
    with pytest.raises(DatabaseError):
        client.post(url, payload)
    assert attempts(op) == attempted + 1
    assert business_values() == before


def test_slow_mode_is_bounded_and_health_and_metrics_remain_available(client, control, monkeypatch):
    sleep = Mock()
    monkeypatch.setattr(slo_demo.time, "sleep", sleep)
    control.write_text(json.dumps({"mode": "slow", "expires_at": time.time()+60}))
    assert slo_demo.demo_response() is None
    sleep.assert_called_once_with(1.2)
    control.write_text(json.dumps({"mode": "errors", "expires_at": time.time()+60}))
    assert client.get("/healthz/").status_code == 200
    assert client.get("/metrics").status_code == 200
    control.write_text(json.dumps({"mode": "errors", "expires_at": time.time()+1000}))
    assert slo_demo.demo_response() is None
    control.write_text("broken JSON")
    assert slo_demo.demo_response() is None
