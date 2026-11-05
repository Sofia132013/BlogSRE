"""Operational logs identify successful actions without recording user content."""

import logging

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.urls import reverse

from posts.models import Comment, Follow, Group, Post


@pytest.mark.django_db
def test_access_log_uses_route_and_request_id_without_query_or_user_data(client, caplog):
    author = get_user_model().objects.create_user(username="private-username")
    post = Post.objects.create(author=author, text="private-post-body")

    with caplog.at_level(logging.INFO):
        response = client.get(
            reverse("post_view", args=[author.username, post.pk])
            + "?token=private-query-value"
        )
        client.get(reverse("readyz"))

    access = [record for record in caplog.records if record.name == "blog.access"]
    assert response.status_code == 200
    assert len(access) == 1  # Successful health probes do not flood access logs.
    assert "method=GET" in access[0].message
    assert "route=/<str:username>/<int:post_id>/" in access[0].message
    assert "status=200" in access[0].message
    assert response["X-Request-ID"] == access[0].request_id
    assert access[0].method == "GET"
    assert access[0].status == 200
    assert access[0].route == "/<str:username>/<int:post_id>/"
    assert access[0].duration_ms >= 0
    assert "private-username" not in access[0].message
    assert "private-query-value" not in access[0].message
    assert "private-post-body" not in access[0].message


@pytest.mark.django_db
def test_failed_readiness_is_logged_without_connection_details(client, caplog, monkeypatch):
    from blog import urls

    class UnavailableDatabase:
        def cursor(self):
            raise DatabaseError("private-connection-detail")

    monkeypatch.setattr(urls, "connections", {"default": UnavailableDatabase()})
    with caplog.at_level(logging.INFO):
        response = client.get(reverse("readyz"))

    access = [record for record in caplog.records if record.name == "blog.access"]
    assert response.status_code == 503
    assert len(access) == 1
    assert access[0].levelno == logging.ERROR
    assert "route=/readyz/ status=503" in access[0].message
    assert "private-connection-detail" not in access[0].message


@pytest.mark.django_db
def test_write_events_log_ids_but_not_form_contents(client, caplog):
    user_model = get_user_model()
    author = user_model.objects.create_user(username="author", password="test-password")
    reader = user_model.objects.create_user(username="reader", password="test-password")
    client.force_login(author)
    caplog.clear()

    with caplog.at_level(logging.INFO):
        response = client.post(reverse("new_category"), {
            "title": "Private category title", "description": "Private description"
        })
        assert response.status_code == 302
        category = Group.objects.get(title="Private category title")

        response = client.post(reverse("new_post"), {
            "group": category.pk, "text": "Private post text"
        })
        assert response.status_code == 302
        post = Post.objects.get(author=author)

        response = client.post(reverse("post_edit", args=[author.username, post.pk]), {
            "group": category.pk, "text": "Private edited text"
        })
        assert response.status_code == 302

        response = client.post(reverse("add_comment", args=[author.username, post.pk]), {
            "text": "Private comment text"
        })
        assert response.status_code == 302
        comment = Comment.objects.get(post=post)

        response = client.post(reverse("profile_follow", args=[reader.username]))
        assert response.status_code == 302
        assert Follow.objects.filter(user=author, author=reader).exists()

        response = client.post(reverse("profile_unfollow", args=[reader.username]))
        assert response.status_code == 302

        response = client.post(reverse("post_delete", args=[author.username, post.pk]))
        assert response.status_code == 302

    events = [record.message for record in caplog.records if record.name == "blog.activity"]
    assert events == [
        f"category.created actor_id={author.pk} category_id={category.pk}",
        f"post.created actor_id={author.pk} post_id={post.pk}",
        f"post.updated actor_id={author.pk} post_id={post.pk}",
        f"comment.created actor_id={author.pk} comment_id={comment.pk} post_id={post.pk}",
        f"follow.created actor_id={author.pk} author_id={reader.pk}",
        f"follow.deleted actor_id={author.pk} author_id={reader.pk}",
        f"post.deleted actor_id={author.pk} post_id={post.pk}",
    ]
    assert not any("Private" in event for event in events)


@pytest.mark.django_db
def test_account_events_log_user_id_without_credentials(client, caplog):
    with caplog.at_level(logging.INFO):
        response = client.post(reverse("signup"), {
            "username": "registered-user",
            "email": "private@example.com",
            "password1": "PrivatePass-123456",
            "password2": "PrivatePass-123456",
        })
        assert response.status_code == 302
        user = get_user_model().objects.get(username="registered-user")

        response = client.post(reverse("login"), {
            "username": user.username,
            "password": "PrivatePass-123456",
        })
        assert response.status_code == 302
        response = client.post(reverse("logout"))
        assert response.status_code in (200, 302)

    events = [record.message for record in caplog.records if record.name == "blog.activity"]
    assert events == [
        f"user.registered actor_id={user.pk}",
        f"auth.login actor_id={user.pk}",
        f"auth.logout actor_id={user.pk}",
    ]
    assert "PrivatePass-123456" not in caplog.text
    assert "private@example.com" not in caplog.text


@pytest.mark.django_db
def test_denied_edits_and_deletes_are_logged_without_post_content(client, caplog):
    user_model = get_user_model()
    author = user_model.objects.create_user(username="author")
    other = user_model.objects.create_user(username="other")
    post = Post.objects.create(author=author, text="Private existing text")
    client.force_login(other)
    caplog.clear()

    with caplog.at_level(logging.INFO):
        edit = client.post(reverse("post_edit", args=[author.username, post.pk]), {
            "text": "Private attempted edit"
        })
        delete = client.post(reverse("post_delete", args=[author.username, post.pk]))

    assert edit.status_code == delete.status_code == 302
    assert Post.objects.filter(pk=post.pk, text="Private existing text").exists()
    events = [record.message for record in caplog.records if record.name == "blog.activity"]
    assert events == [
        f"post.edit_denied actor_id={other.pk} post_id={post.pk}",
        f"post.delete_denied actor_id={other.pk} post_id={post.pk}",
    ]
    assert "Private" not in caplog.text
