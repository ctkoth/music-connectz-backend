"""Rewrite profile JSON that is not in the shape the app reads.

Two things, both written by `POST /api/economy/profile/` back when it set
PROFILE_FIELDS straight off the request body:

  * a persona stored as the PRINTED form of a dict, which rendered as machine
    noise on the member's own card and dropped their priced skills out of
    everything that counts them;
  * a link whose URL is not a scheme we will render — a stored `javascript:`
    on a page a stranger can open.

Both are repaired on read as well (`personaz.personas_of` / `links_of`), so
nobody is broken and nothing dangerous is served while this has not been run.
What that cannot do is make the stored data true: until the rows are rewritten
every read pays for the repair, an admin looking at the column still sees it,
and anything querying the JSON directly still misses.

Dry by default, like `reconcile_uploads` — the only other command here that
touches member data. `--write` is the deliberate act.
"""
from django.core.management.base import BaseCommand

from apps.economy.models import Profile
from apps.economy.personaz import clean_persona, links_of, profile_needs_repair


class Command(BaseCommand):
    help = "Normalize stored PersonaZ entries and profile links (--write to save)."

    def add_arguments(self, parser):
        parser.add_argument("--write", action="store_true",
                            help="Save the repairs. Without it, only reports.")

    def handle(self, *args, **opts):
        write = opts["write"]
        checked = repaired = dropped_links = 0
        # `personas` and `links` are JSONFields and the broken shapes are not
        # queryable across both SQLite and Postgres, so this walks. It is one
        # pass over the profile table, run by hand, never on a request.
        for p in Profile.objects.iterator(chunk_size=200):
            if not (p.personas or p.links):
                continue
            checked += 1
            if not profile_needs_repair(p):
                continue
            repaired += 1
            personas = [clean_persona(x) for x in (p.personas or [])]
            links = links_of(p)
            gone = len(p.links or []) - len(links)
            dropped_links += max(0, gone)
            self.stdout.write(f"{p.user.username}:")
            for b, a in zip(p.personas or [], personas):
                if b != a:
                    self.stdout.write(f"    persona {b!r}\n      -> {a!r}")
            if gone > 0:
                # Named, not silently binned. A link that will not render is
                # still something the member typed, and they deserve to know it
                # went rather than wonder where it went.
                kept = {l["url"] for l in links}
                for l in (p.links or []):
                    url = l.get("url") if isinstance(l, dict) else l
                    if url not in kept:
                        self.stdout.write(f"    link REFUSED {url!r}")
            if write:
                p.personas, p.links = personas, links
                p.save(update_fields=["personas", "links"])
        verb = "Repaired" if write else "Would repair"
        self.stdout.write(self.style.SUCCESS(
            f"{checked} profile(s) checked. {verb} {repaired}"
            f" ({dropped_links} unrenderable link(s))."))
        if repaired and not write:
            self.stdout.write("Re-run with --write to save.")
