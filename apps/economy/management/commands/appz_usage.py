"""Real per-app usage, off the same tables the apps themselves write.

`manage.py appz_usage` exists because "let's cut some apps" is a decision
this codebase's own CLAUDE.md refuses to let a model guess at from vibes —
it's the same substance rule the platform holds every score to, pointed at
the roster instead of a take: a cut list built from "this app feels quiet"
could get a good answer without the app actually being quiet. So it counts
real rows instead: how many actions each app's own model recorded, by how
many distinct members, in the last 30 and 90 days, and how long it's been
since the last one.

Deliberately NOT run against a local dev database — a fresh SQLite has zero
of everything and would recommend cutting the whole platform. Run this
against the real database (Render's shell, or DATABASE_URL pointed at
production) and read the OUTPUT, don't trust an empty local run.

Some tabs have no model to count at all — MetZ, TunerZ and ChordZ are pure
client-side audio tools with no server round trip, VybeZ is a live search
with no rows of its own, StatsZ/LogZ/RoyaltieZ are read-only dashboards over
other apps' data. Those are printed as "not measurable this way" rather than
zero, because a zero here would say "nobody uses it" about something that
was never going to write a row in the first place — the same "empty
measurement vs. a bad one" distinction FunnelZ's own `pct: None` already
draws, applied to usage instead of conversion.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from apps.economy import models as m
from apps.lessonz import models as lessonz_models
from apps.mimez import models as mimez_models

# app_key -> (queryset, user_field, created_field). One line per measurable
# app; anything not listed here is a tool with no server-side row (see the
# module docstring) and is reported separately, not as a silent zero.
APPS = {
    "postz": (m.Post.objects, "author", "created_at"),
    "playlistz": (m.Playlist.objects, "owner", "created_at"),
    "social": (m.Follow.objects, "follower", "created_at"),
    "soundcloudengagementz": (m.SoundCloudEngagement.objects, "user", "created_at"),
    "specz": (m.SpecZPurchase.objects, "user", "created_at"),
    "adz": (m.AdView.objects, "user", "created_at"),
    "offerz": (m.OfferDismissal.objects, "user", "created_at"),
    "directz": (m.DirectZWork.objects, "owner", "created_at"),
    "callz": (m.Call.objects, "caller", "created_at"),
    "messagez": (m.Message.objects, "sender", "created_at"),
    "keyconnectz": (m.KeyTranslation.objects, "user", "created_at"),
    "occ": (m.OccTask.objects, "user", "created_at"),
    "royaltiez": (m.RoyaltyEntry.objects, "user", "created_at"),
    "gamez": (m.Game.objects, "user", "created_at"),
    "journalz": (m.JournalEntry.objects, "author", "created_at"),
    "habitz": (m.Habit.objects, "user", "created_at"),
    "lilith": (m.LilithTask.objects, "user", "created_at"),
    "collabz": (m.CollabDeal.objects, "initiator", "created_at"),
    "venuez": (m.VenueBooking.objects, "visitor", "created_at"),
    "battlez": (m.BattleEntry.objects, "user", "created_at"),
    "groupz": (m.GroupMember.objects, "member", "added_at"),
    "lessonz": (lessonz_models.LessonBooking.objects, "student", "created_at"),
    "mimez": (mimez_models.MimeZSubmission.objects, "user", "created_at"),
}

# The seven instrument coaches share one model (TakeScore, keyed by
# app_key), so they get their own pass rather than a queryset each — a drummer
# and a singer write the same table, split by the column that already tells
# them apart.
INSTRUMENT_KEYS = ["singz", "rapz", "guitarz", "bassz", "keyz", "violinz", "drumz"]

NOT_MEASURABLE = {
    "onboardz": "steps live on Profile/Post/Habit, already counted there",
    "vybez": "live search, no rows of its own",
    "coachz": "hub screen over the instrument coaches below",
    "profilez": "every member has one; edits aren't logged as events",
    "statsz": "read-only dashboard over other apps' data",
    "membershipz": "tier is on Membership, not a repeated action",
    "logz": "read-only ledger view",
    # Not "quiet" — BROKEN. The frontend calls POST/GET /api/labelz/ and
    # /api/labelz/contracts/ and neither route is mounted anywhere in this
    # backend (checked: no match in music_connectz/urls.py or any app's
    # urls.py). Every load of this tab 404s. Its usage number isn't low,
    # it's undefined — nobody could have used it since whenever the route
    # was removed or never finished. Worth Corey's eyes before "cut" or
    # "fix the route" gets decided either way.
    "labelz": "BROKEN — no /api/labelz/ route exists; every load 404s",
    "opportunitiez": "a filtered directory over Profile rows, not a repeated action — nothing to count",
    "soundz": "a sound-pack preference on Profile, not a repeated action — nothing to count",
    "metz": "client-only audio tool, no server round trip",
    "tunerz": "client-only audio tool, no server round trip",
    "chordz": "client-only audio tool, no server round trip",
    "keyz_instrument": "shadowed by keyconnectz key above — see INSTRUMENT_KEYS",
}


class Command(BaseCommand):
    help = "Real per-app usage counts, for deciding what to cut — not a guess."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Machine-readable output.")

    def handle(self, *args, **opts):
        now = timezone.now()
        d30, d90 = now - timedelta(days=30), now - timedelta(days=90)
        rows = []

        for app_key, (qs, user_field, created_field) in APPS.items():
            rows.append(self._row(app_key, qs, user_field, created_field, d30, d90))

        for app_key in INSTRUMENT_KEYS:
            qs = m.TakeScore.objects.filter(app_key=app_key)
            rows.append(self._row(app_key, qs, "user", "created_at", d30, d90))

        rows.sort(key=lambda r: r["all_time"], reverse=True)

        if opts["json"]:
            import json
            self.stdout.write(json.dumps({"generated_at": now.isoformat(),
                                          "rows": rows,
                                          "not_measurable": NOT_MEASURABLE}, default=str, indent=2))
            return

        self.stdout.write(f"Per-app usage as of {now:%Y-%m-%d %H:%M} UTC\n")
        self.stdout.write(f"{'app_key':<24}{'all-time':>10}{'90d rows':>10}{'90d ppl':>9}"
                          f"{'30d rows':>10}{'30d ppl':>9}  last activity")
        self.stdout.write("-" * 100)
        for r in rows:
            last = r["last_activity"].strftime("%Y-%m-%d") if r["last_activity"] else "never"
            self.stdout.write(
                f"{r['app_key']:<24}{r['all_time']:>10}{r['d90_rows']:>10}{r['d90_people']:>9}"
                f"{r['d30_rows']:>10}{r['d30_people']:>9}  {last}"
            )

        self.stdout.write("\nNot measurable this way (not zero — see reason):")
        for key, why in NOT_MEASURABLE.items():
            self.stdout.write(f"  {key:<24}{why}")

        self.stdout.write(
            "\nThis is the ONLY input a cut decision should use — read it against the "
            "current member count (2 on record as of this session) before concluding "
            "anything is dead. Two members can only ever produce a handful of rows "
            "regardless of whether an app is good; a real cut list needs either more "
            "traffic first or Corey's own judgement about apps nobody has been pointed "
            "at yet (onboarding, the dock, funnel offers never surface most of these)."
        )

    def _row(self, app_key, qs, user_field, created_field, d30, d90):
        all_time = qs.count()
        last = qs.order_by(f"-{created_field}").values_list(created_field, flat=True).first()
        d90_qs = qs.filter(**{f"{created_field}__gte": d90})
        d30_qs = qs.filter(**{f"{created_field}__gte": d30})
        return {
            "app_key": app_key,
            "all_time": all_time,
            "d90_rows": d90_qs.count(),
            "d90_people": d90_qs.values(user_field).distinct().count(),
            "d30_rows": d30_qs.count(),
            "d30_people": d30_qs.values(user_field).distinct().count(),
            "last_activity": last,
        }
