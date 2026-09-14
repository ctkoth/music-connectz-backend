"""Pay out comment karma for comments nobody happened to open.

The lazy settle in `social.SocialView._payload` covers every comment somebody
reads, which is most of them. This covers the rest — a comment on a post that
went quiet still earned what it earned, and a reward that only arrives if
somebody revisits the thread is a reward the member cannot rely on.

Dry by default, like `reconcile_uploads` and `repair_profiles`: a command that
moves currency the first time it is run is one nobody runs twice.
"""
from django.core.management.base import BaseCommand

from apps.economy import karmaz
from apps.economy.models import Post, SocialComment


class Command(BaseCommand):
    help = "Settle karma on comments whose window has passed."

    def add_arguments(self, parser):
        parser.add_argument("--write", action="store_true",
                            help="Actually pay. Without it, only reports.")
        parser.add_argument("--limit", type=int, default=2000)

    def handle(self, *args, **opts):
        rows = list(SocialComment.objects.filter(karma_settled_at__isnull=True)
                    .select_related("user")[:opts["limit"]])
        due = [c for c in rows if karmaz.due(c)]
        self.stdout.write(f"{len(due)} comment(s) due of {len(rows)} unsettled.")

        # One query for every post named, rather than one per comment — the
        # sweep runs over the whole backlog and a per-row lookup there is the
        # same mistake as a per-card read on the feed.
        ids = set()
        for c in due:
            if str(c.item_id).startswith("post:"):
                try:
                    ids.add(int(c.item_id.split(":", 1)[1]))
                except (ValueError, IndexError):
                    continue
        authors = dict(Post.objects.filter(pk__in=ids).values_list("pk", "author_id"))

        paid = total = 0
        for c in due:
            pid = None
            if str(c.item_id).startswith("post:"):
                try:
                    pid = authors.get(int(c.item_id.split(":", 1)[1]))
                except (ValueError, IndexError):
                    pid = None
            if not opts["write"]:
                _, _, net = karmaz.karma_for(c.pk)
                self.stdout.write(f"  would settle comment {c.pk} by @{c.user.username} "
                                  f"— net {net}")
                continue
            got = karmaz.settle_comment(c, post_author_id=pid)
            if got and got["energy"]:
                paid += 1
                total += got["energy"]

        if opts["write"]:
            self.stdout.write(self.style.SUCCESS(
                f"Settled {len(due)}; {paid} paid, {total} ⚡ in total."))
        else:
            self.stdout.write("Dry run. Pass --write to pay.")
