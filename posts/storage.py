"""Small PostgreSQL-backed storage for the blog's uploaded images."""

import os
import uuid
from io import BytesIO

from django.core.files.base import File
from django.core.files.storage import Storage
from django.urls import reverse


class DatabaseImageStorage(Storage):
    def _open(self, name, mode="rb"):
        from .models import StoredImage

        try:
            image = StoredImage.objects.get(pk=name)
        except StoredImage.DoesNotExist:
            raise FileNotFoundError(name)
        return File(BytesIO(bytes(image.content)), name=name)

    def _save(self, name, content):
        from .models import StoredImage

        directory = os.path.dirname(name)
        extension = os.path.splitext(name)[1].lower()[:10]
        unique_name = os.path.join(directory, uuid.uuid4().hex + extension).replace("\\", "/")
        data = content.read()
        StoredImage.objects.create(name=unique_name, content=data, size=len(data))
        return unique_name

    def exists(self, name):
        from .models import StoredImage

        return StoredImage.objects.filter(pk=name).exists()

    def delete(self, name):
        from .models import StoredImage

        if name:
            StoredImage.objects.filter(pk=name).delete()

    def size(self, name):
        from .models import StoredImage

        return StoredImage.objects.values_list("size", flat=True).get(pk=name)

    def url(self, name):
        return reverse("media_file", kwargs={"name": name})
