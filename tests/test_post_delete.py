import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from posts.models import Post


@pytest.mark.django_db
def test_author_can_delete_post(user_client, post_with_group):
    response = user_client.post(
        reverse(
            "post_delete",
            args=(post_with_group.author.username, post_with_group.id),
        )
    )

    assert response.status_code == 302
    assert response.url == reverse("index")
    assert not Post.objects.filter(pk=post_with_group.pk).exists()


@pytest.mark.django_db
def test_other_user_cannot_delete_post(client, post_with_group):
    other_user = get_user_model().objects.create_user(
        username="other-user", password="test-password"
    )
    client.force_login(other_user)

    response = client.post(
        reverse(
            "post_delete",
            args=(post_with_group.author.username, post_with_group.id),
        )
    )

    assert response.status_code == 302
    assert response.url == reverse(
        "post_view", args=(post_with_group.author.username, post_with_group.id)
    )
    assert Post.objects.filter(pk=post_with_group.pk).exists()
