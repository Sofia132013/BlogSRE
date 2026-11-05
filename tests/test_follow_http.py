"""Subscription writes must use POST and Django's CSRF protection."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from posts.models import Follow, Post


class FollowHttpTest(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.reader = user_model.objects.create_user(username="reader", password="test-password")
        self.author = user_model.objects.create_user(username="writer", password="test-password")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.reader)

    def test_profile_forms_require_post_and_csrf(self):
        profile_url = reverse("profile", args=[self.author.username])
        follow_url = reverse("profile_follow", args=[self.author.username])
        unfollow_url = reverse("profile_unfollow", args=[self.author.username])

        response = self.client.get(profile_url)
        self.assertContains(response, 'method="post"')
        self.assertContains(response, f'action="{follow_url}"')
        token = self.client.cookies["csrftoken"].value

        self.assertEqual(self.client.get(follow_url).status_code, 405)
        self.assertEqual(self.client.post(follow_url).status_code, 403)
        self.assertEqual(Follow.objects.count(), 0)

        self.assertEqual(
            self.client.post(follow_url, HTTP_X_CSRFTOKEN=token).status_code, 302
        )
        self.assertTrue(Follow.objects.filter(user=self.reader, author=self.author).exists())
        self.assertContains(self.client.get(profile_url), f'action="{unfollow_url}"')

        self.assertEqual(self.client.get(unfollow_url).status_code, 405)
        self.assertEqual(self.client.post(unfollow_url).status_code, 403)
        self.assertEqual(Follow.objects.count(), 1)
        self.assertEqual(
            self.client.post(unfollow_url, HTTP_X_CSRFTOKEN=token).status_code, 302
        )
        self.assertEqual(Follow.objects.count(), 0)

    def test_post_page_contains_subscription_form(self):
        post = Post.objects.create(author=self.author, text="Subscription form")
        response = self.client.get(reverse("post_view", args=[self.author.username, post.pk]))
        self.assertContains(response, 'method="post"')
        self.assertContains(
            response, f'action="{reverse("profile_follow", args=[self.author.username])}"'
        )
