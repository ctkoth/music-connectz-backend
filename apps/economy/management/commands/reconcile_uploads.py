"""Ask storage which files are actually still there, and write the answer down.

The app learns about a missing file the hard way, one at a time, when somebody
tries to use it — the coach reaches for a take and finds nothing. That is the
right place to LEARN it, and a terrible place to learn it FIRST: the member
finds out about their own lost recording by being refused something they asked
for.

This goes and asks, deliberately, for everything at once. It is the only thing
in the codebase that walks storage: a read path must never do this (a feed of
100 posts would become 100 stat calls, or 100 HEAD requests against a bucket),
so the sweep is a command somebody runs, not something that happens quietly on
a request.

    python manage.py reconcile_uploads              # report only
    python manage.py reconcile_uploads --write      # stamp what it finds

Worth running after any deploy that lost a disk, and after restoring one — it
CLEARS the mark for files that came back, so a post stops saying its audio is
gone the moment the audio is not.
"""
from django.core.management.base import BaseCommand

from apps.economy.models import Upload, mark_upload_found, mark_upload_missing


class Command(BaseCommand):
    help = "Check every Upload against storage and record which files are gone."

    def add_arguments(self, parser):
        parser.add_argument(
            "--write", action="store_true",
            help="Stamp missing_since (and clear it for files that came back). "
                 "Without it, nothing is changed and the counts are a dry run.")
        parser.add_argument(
            "--user", default="", help="Limit to one username.")

    def handle(self, *args, **opts):
        qs = Upload.objects.all().order_by("pk")
        if opts["user"]:
            qs = qs.filter(user__username=opts["user"])

        gone, back, present, unreadable = [], 0, 0, 0
        for up in qs.iterator(chunk_size=500):
            if not up.file or not up.file.name:
                unreadable += 1
                continue
            try:
                there = up.file.storage.exists(up.file.name)
            except Exception as exc:                     # pragma: no cover
                # A backend that cannot answer is not a file that is missing.
                # Marking on an unreachable bucket would tell every member on
                # the platform their music was lost, which is worse than the
                # bug this command exists for.
                self.stderr.write(f"  ? upload {up.pk}: storage error — {exc}")
                unreadable += 1
                continue
            if there:
                present += 1
                if up.missing_since and opts["write"] and mark_upload_found(up):
                    back += 1
            elif not up.missing_since:
                gone.append(up)
                if opts["write"]:
                    mark_upload_missing(up)

        for up in gone[:50]:
            self.stdout.write(f"  gone: #{up.pk} {up.name} <{up.user_id}> {up.file.name}")
        if len(gone) > 50:
            self.stdout.write(f"  … and {len(gone) - 50} more")

        verb = "marked" if opts["write"] else "would mark"
        self.stdout.write(self.style.WARNING(
            f"{len(gone)} file(s) not in storage ({verb}). "
            f"{back} came back. {present} present. {unreadable} could not be checked."))
        if gone and not opts["write"]:
            self.stdout.write("Re-run with --write to record it. "
                              "Nothing is deleted either way — the row is the "
                              "record of what was lost.")
