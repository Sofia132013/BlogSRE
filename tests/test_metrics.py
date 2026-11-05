"""Metrics describe successful operations, including transaction rollback semantics."""

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction
from django.urls import reverse
from prometheus_client import REGISTRY
from prometheus_client.parser import text_string_to_metric_families

from blog import metrics  # noqa: F401 — register business metrics before taking a snapshot.
from posts.models import Comment, Follow, Post


BUSINESS_METRICS = (
    "blog_posts_created_total",
    "blog_comments_created_total",
    "blog_user_registrations_total",
    "blog_subscriptions_created_total",
)


def business_values():
    return {name: REGISTRY.get_sample_value(name) for name in BUSINESS_METRICS}


@pytest.fixture
def operation(client, request):
    """A valid HTTP request for each of the four business operations."""
    users = get_user_model()
    author = users.objects.create_user(username="metrics-author")
    reader = users.objects.create_user(username="metrics-reader")
    client.force_login(reader)
    post = Post.objects.create(author=author, text="Existing post")
    requests = {
        "post": (reverse("new_post"), {"text": "New post"}, Post),
        "comment": (
            reverse("add_comment", args=[author.username, post.pk]),
            {"text": "New comment"}, Comment,
        ),
        "registration": (
            reverse("signup"),
            {
                "username": "metrics-new-user",
                "password1": "Metrics-Test-Password-729!",
                "password2": "Metrics-Test-Password-729!",
            }, users,
        ),
        "subscription": (
            reverse("profile_follow", args=[author.username]), {}, Follow,
        ),
    }
    return requests[request.param]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "operation,metric",
    list(zip(("post", "comment", "registration", "subscription"), BUSINESS_METRICS)),
    indirect=["operation"],
)
def test_success_increments_only_its_counter_after_commit(
    client, operation, metric, django_capture_on_commit_callbacks,
):
    url, payload, model = operation
    before = business_values()
    count = model.objects.count()
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(url, payload).status_code == 302
        assert model.objects.count() == count + 1
        assert business_values() == before  # Not counted before commit.
    expected = {**before, metric: before[metric] + 1}
    assert business_values() == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    "operation", ("post", "comment", "registration", "subscription"),
    indirect=True,
)
def test_rollback_does_not_count_a_success(
    client, operation, django_capture_on_commit_callbacks,
):
    url, payload, model = operation
    before = business_values()
    count = model.objects.count()
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            assert client.post(url, payload).status_code == 302
            transaction.set_rollback(True)
    assert model.objects.count() == count
    assert business_values() == before


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ("post", "comment", "registration"), indirect=True)
def test_invalid_forms_do_not_increment_counters(
    client, operation, django_capture_on_commit_callbacks,
):
    url, _, model = operation
    before = business_values()
    count = model.objects.count()
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(url, {"text": ""}).status_code == 200
    assert model.objects.count() == count
    assert business_values() == before


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["subscription"], indirect=True)
def test_duplicate_self_and_get_subscriptions_do_not_count(
    client, operation, django_capture_on_commit_callbacks,
):
    url, _, _ = operation
    before = business_values()
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(url).status_code == 302
    assert business_values()[BUSINESS_METRICS[3]] == before[BUSINESS_METRICS[3]] + 1
    after = business_values()
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(url).status_code == 302
        assert client.get(url).status_code == 405
        self_url = reverse("profile_follow", args=["metrics-reader"])
        assert client.post(self_url).status_code == 302
    assert business_values() == after


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["post"], indirect=True)
def test_edits_deletes_and_anonymous_requests_do_not_count_posts(
    client, operation, django_capture_on_commit_callbacks,
):
    url, payload, _ = operation
    reader = get_user_model().objects.get(username="metrics-reader")
    post = Post.objects.create(author=reader, text="Original post")
    before = business_values()
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(
            reverse("post_edit", args=[reader.username, post.pk]),
            {"text": "Edited post"},
        ).status_code == 302
        assert client.post(
            reverse("post_delete", args=[reader.username, post.pk]),
        ).status_code == 302
        client.logout()
        assert client.post(url, payload).status_code == 302
    assert business_values() == before


def test_metrics_are_anonymous_and_scraping_does_not_count_business_events(client):
    before = business_values()
    for _ in range(2):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/plain")
        samples = {
            sample.name: sample
            for family in text_string_to_metric_families(response.content.decode())
            for sample in family.samples
        }
        for name in BUSINESS_METRICS:
            assert samples[name].value == before[name]
            assert samples[name].labels == {}
        assert "django_http_requests_before_middlewares_total" in samples
        assert "django_http_requests_latency_including_middlewares_seconds_bucket" in samples
    assert business_values() == before
