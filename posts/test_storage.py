"""Uploaded images remain available through the shared PostgreSQL database."""

import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from posts.models import Post, StoredImage, User


GIF = (
    b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00"
    b"\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


class SharedImageStorageTest(TestCase):
    def test_uploaded_image_is_stored_in_postgresql_and_served(self):
        author = User.objects.create_user(username="image_author", password="test-password")
        self.client.force_login(author)

        response = self.client.post(
            reverse("new_post"),
            {"text": "Image post", "image": SimpleUploadedFile("photo.gif", GIF, content_type="image/gif")},
        )
        self.assertEqual(response.status_code, 302)

        post = Post.objects.get(author=author, text="Image post")
        stored = StoredImage.objects.get(pk=post.image.name)
        self.assertEqual(bytes(stored.content), GIF)
        self.assertEqual(stored.size, len(GIF))

        response = self.client.get(post.image.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/gif")
        self.assertEqual(b"".join(response.streaming_content), GIF)
        self.assertEqual(self.client.get("/media/posts/missing.gif").status_code, 404)

    def test_legacy_image_import_is_repeatable(self):
        author = User.objects.create_user(username="legacy_author")
        Post.objects.create(text="Legacy image", author=author, image="posts/legacy.gif")

        with tempfile.TemporaryDirectory() as source_dir:
            path = Path(source_dir) / "posts" / "legacy.gif"
            path.parent.mkdir()
            path.write_bytes(GIF)
            call_command("import_media", source_dir)
            call_command("import_media", source_dir)

        self.assertEqual(bytes(StoredImage.objects.get(pk="posts/legacy.gif").content), GIF)
        self.assertEqual(StoredImage.objects.count(), 1)
