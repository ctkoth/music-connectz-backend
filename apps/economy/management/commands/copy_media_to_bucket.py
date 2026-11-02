"""Copy every file the database names from the old disk into the storage now in force.

Switching uploads to a bucket (S3_BUCKET_NAME + keys) changes where the app LOOKS,
not where the bytes ARE. Every `Upload` row names a key like `uploads/12/take.wav`;
with the bucket on, that key is asked of the bucket, and the files that were sitting
on the persistent disk are not there. Without this step the switch would do to
every file uploaded since the disk was mounted what the old ephemeral disk did to
the earlier ones.

    python manage.py copy_media_to_bucket                 # report only
    python manage.py copy_media_to_bucket --write         # copy what is missing
    python manage.py copy_media_to_bucket --source /var/mcz-media

Rules, all in the spirit of `reconcile_uploads`:

- **Dry by default.** `--write` is the only thing that uploads.
- **It never overwrites and never deletes.** A key the destination already holds is
  left alone, and nothing is ever removed from the source: the disk stays the
  second copy until a person decides it can go.
- **Keys are kept exactly**, so no database row changes. A destination that stores
  a file under a DIFFERENT key than the one asked for is reported and counted as a
  failure rather than quietly breaking the row.
- **It finds every file field, not just Upload** (avatars, covers, FaceZ images…),
  by walking the models, the way account erasure does.
- **A source file that is not there is reported, not guessed at** — those are the
  already-lost ones, and `reconcile_uploads` is what marks them.
"""
import os

from django.apps import apps
from django.conf import settings
from django.core.files import File
from django.core.files.storage import FileSystemStorage, default_storage
from django.core.management.base import BaseCommand
from django.db import models


def file_fields():
    """Every (model, field) that holds a file."""
    out = []
    for model in apps.get_models():
        for f in model._meta.get_fields():
            if isinstance(f, models.FileField):
                out.append((model, f))
    return out


class Command(BaseCommand):
    help = "Copy files named in the database from the old disk into the current storage (bucket)."

    def add_arguments(self, parser):
        parser.add_argument("--write", action="store_true",
                            help="Actually upload. Without it nothing is changed.")
        parser.add_argument("--source", default="",
                            help="Directory the files are on now (default: MEDIA_ROOT).")
        parser.add_argument("--limit", type=int, default=0,
                            help="Stop after this many copies (0 = all).")

    def handle(self, *args, **opts):
        source = FileSystemStorage(location=opts["source"] or str(settings.MEDIA_ROOT))
        dest = default_storage
        if isinstance(dest, FileSystemStorage) and os.path.abspath(dest.location) == os.path.abspath(source.location):
            self.stderr.write(self.style.ERROR(
                "The destination is the same folder as the source — the bucket is not in force "
                "(S3_BUCKET_NAME unset?), so there is nothing to copy to."))
            return

        copied = already = missing = failed = 0
        bytes_copied = 0
        for model, field in file_fields():
            qs = model.objects.exclude(**{field.name: ""}).exclude(**{f"{field.name}__isnull": True})
            for obj in qs.iterator(chunk_size=200):
                name = getattr(obj, field.name).name
                if not name:
                    continue
                try:
                    if dest.exists(name):
                        already += 1
                        continue
                except Exception as exc:
                    failed += 1
                    self.stderr.write(f"  ? {model.__name__} {obj.pk} {name}: destination error — {exc}")
                    continue
                if not source.exists(name):
                    missing += 1
                    continue
                size = source.size(name)
                if not opts["write"]:
                    copied += 1
                    bytes_copied += size
                    continue
                if opts["limit"] and copied >= opts["limit"]:
                    break
                try:
                    with source.open(name, "rb") as fh:
                        saved = dest.save(name, File(fh))
                    if saved != name:
                        failed += 1
                        self.stderr.write(f"  ! {model.__name__} {obj.pk}: stored as {saved}, not {name} — row would break")
                        continue
                    copied += 1
                    bytes_copied += size
                except Exception as exc:
                    failed += 1
                    self.stderr.write(f"  ! {model.__name__} {obj.pk} {name}: {exc}")

        verb = "copied" if opts["write"] else "would copy"
        self.stdout.write(self.style.SUCCESS(
            f"{copied} file(s) {verb} ({bytes_copied / (1024 * 1024):.1f} MB). "
            f"{already} already in the destination. {missing} not on the source (already lost). "
            f"{failed} failed."))
        if not opts["write"] and copied:
            self.stdout.write("Re-run with --write to copy. Nothing is deleted from the source either way.")
