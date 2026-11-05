"""One-time import of images from a legacy filesystem media directory."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from posts.models import Post, StoredImage


class Command(BaseCommand):
    help = "Copy images referenced by posts from an old media directory into PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument("source_dir", help="Root of the old media directory")

    def handle(self, *args, **options):
        source_dir = Path(options["source_dir"]).resolve()
        if not source_dir.is_dir():
            raise CommandError("Media directory does not exist: {}".format(source_dir))

        imported = 0
        names = Post.objects.exclude(image="").exclude(image__isnull=True).values_list(
            "image", flat=True
        ).distinct()
        for name in names:
            if StoredImage.objects.filter(pk=name).exists():
                continue
            source = (source_dir / name).resolve()
            if source_dir not in source.parents or not source.is_file():
                raise CommandError("Image is missing or outside media directory: {}".format(name))
            data = source.read_bytes()
            StoredImage.objects.create(name=name, content=data, size=len(data))
            imported += 1

        self.stdout.write("Imported {} referenced images into PostgreSQL.".format(imported))
