"""JournalZ, the parts a real diary app has — calendar, insights, and prompts.

JournalZ already had the hard half: an entry that is private by default, a day
it is ABOUT rather than the day it was typed, moods, weather, free-text tags,
tagged people who are only ever notified on a share, a place whose coordinates
stay home unless you say otherwise, attachments, search, On This Day, export.

What it did not have is the part that makes a diary app a diary app rather than
a text box with a date: **a way to look at the whole thing.** A month you can
see. A year you can count. And a reason to open it today.

## Why these three, and why they are free

- **The calendar is how a diary is navigated.** Scrolling a list works for the
  last fortnight and fails completely at "what was I doing last March". Every
  cell is a door: a day you kept opens the entry, a day you missed opens the
  composer set to that date. An empty cell that does nothing is thirty dead
  ends a month.
- **Insights count what HAPPENED and nothing else.** Days kept, entries, moods,
  tags, the people you wrote about, the places. No "depth", no word-count
  badge, no streak score — a number on somebody's diary would be exactly the
  failure `directz_ai_rating` is in CLAUDE.md for. Every row here is a door
  too: a person opens their profile, a tag opens that search, a place opens
  the map.
- **All three are free at every tier.** Reading your own diary is not a
  capability we rent to you — the same argument that took the gate off LogZ.
  What Premium buys here stays what it already bought: On This Day, and export.

## The prompt is the part Diarium structurally cannot do

Every diary app on earth can ask "how was your day?". A generic prompt is a
blank page with a question mark on it, and the reason diaries get abandoned in
February is that opening one costs you the work of remembering what happened.

**Music ConnectZ already knows what happened.** The ledger records every
resource that moved and — since `Transaction.open_in` — where it moved. So the
prompt is drawn from the member's own day: the takes they recorded, the posts
they rated, the battle they entered, the SpinaZ that arrived and why. Each one
carries the words to start with AND the door back to the thing it is about.

That is the whole cross-pollination rule pointed at the one app most likely to
be a dead end: a diary you open to find it already knows you had a day.

Two rules the prompts keep:

- **Never invent a day.** A member who did nothing gets the plain opener, not a
  fabricated highlight. A prompt about a thing that did not happen is worse
  than a blank page, because now the app is wrong as well as empty.
- **A prompt is a suggestion, never a template that writes for you.** It hands
  over a first line and the link; the entry is still theirs to write. Anything
  further would be the app keeping the diary, which is not a feature, it is a
  different product.
"""
import calendar as _calendar
from collections import Counter
from datetime import date, timedelta

from django.db.models import Count
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .journalz import streak_days
from .models import JOURNAL_MOODS, JournalEntry, Transaction

MOOD_LABEL = dict(JOURNAL_MOODS)

# How far back insights read. Two years is enough to say something true about a
# habit and bounded enough that the query stays one scan.
INSIGHT_DAYS = 730

# The most rows a list of tags / people / places returns. A "top" list with
# four hundred entries is not a top list, it is the raw data again.
TOP_N = 12


def _month_bounds(raw):
    """(first, last) of the requested month. Defaults to this one.

    A bad or missing `?month=` is this month rather than an error: a calendar
    that 400s on a typo is a calendar you cannot page through with a keyboard.
    """
    today = timezone.localdate()
    try:
        year, month = str(raw or "").split("-")
        year, month = int(year), int(month)
        if not (1 <= month <= 12 and 1970 <= year <= 3000):
            raise ValueError
    except (TypeError, ValueError):
        year, month = today.year, today.month
    last = _calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


class JournalCalendarView(APIView):
    """GET ?month=YYYY-MM — the month, day by day, with a door on every cell.

    Free at every tier. Navigating your own diary is not a capability we rent
    to you; it is the diary.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        first, last = _month_bounds(request.query_params.get("month"))
        rows = (JournalEntry.objects
                .filter(author=request.user, day__gte=first, day__lte=last)
                .order_by("day", "created_at")
                .values("id", "day", "title", "mood", "visibility"))

        by_day = {}
        for r in rows:
            by_day.setdefault(r["day"], []).append(r)

        today = timezone.localdate()
        days = []
        for n in range((last - first).days + 1):
            d = first + timedelta(days=n)
            kept = by_day.get(d, [])
            first_entry = kept[0] if kept else None
            days.append({
                "day": d.isoformat(),
                "dow": d.weekday(),                 # 0 = Monday, for the grid
                "kept": bool(kept),
                "count": len(kept),
                "future": d > today,
                "today": d == today,
                "entry_id": first_entry["id"] if first_entry else None,
                "title": (first_entry["title"] if first_entry else "") or "",
                "mood": (first_entry["mood"] if first_entry else "") or "",
                "mood_label": MOOD_LABEL.get((first_entry or {}).get("mood"), ""),
                # Every cell leads somewhere: a kept day to what you wrote, a
                # missed one to writing it. A grid of thirty dead ends is not
                # navigation, it is wallpaper.
                "open_in": "journalz",
                "action": "read" if kept else ("write" if d <= today else "none"),
            })

        # Which way the arrows go. Computed here so the client never has to
        # know how long a month is or which one comes before January.
        prev_month = (first - timedelta(days=1)).strftime("%Y-%m")
        next_month = (last + timedelta(days=1)).strftime("%Y-%m")

        return Response({
            "month": first.strftime("%Y-%m"),
            "label": first.strftime("%B %Y"),
            "first_dow": first.weekday(),
            "days": days,
            "kept_this_month": sum(1 for d in days if d["kept"]),
            "days_in_month": len(days),
            "prev_month": prev_month,
            "next_month": next_month,
            "moods": [{"key": k, "label": v} for k, v in JOURNAL_MOODS],
        })


class JournalInsightsView(APIView):
    """GET — what your diary actually contains. Counts only, all of them doors.

    Nothing here is scored. Days kept is days you turned up; a tag count is how
    often you used the word. Every figure is a thing that happened, which is
    the only kind of number this app is willing to put on somebody's diary.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        since = timezone.localdate() - timedelta(days=INSIGHT_DAYS)
        rows = list(JournalEntry.objects
                    .filter(author=request.user, day__gte=since)
                    .values("day", "mood", "tags", "people", "place_name",
                            "visibility", "items"))

        days = {r["day"] for r in rows}
        moods = Counter(r["mood"] for r in rows if r["mood"])
        tags = Counter(t for r in rows for t in (r["tags"] or []) if t)
        people = Counter(str(p).lower() for r in rows for p in (r["people"] or []) if p)
        places = Counter(r["place_name"] for r in rows if r["place_name"])

        shared = sum(1 for r in rows if r["visibility"] != JournalEntry.VIS_PRIVATE)
        with_media = sum(1 for r in rows if r["items"])

        return Response({
            "window_days": INSIGHT_DAYS,
            "entries": len(rows),
            "days_kept": len(days),
            "streak": streak_days(request.user),
            "longest_streak": _longest_streak(days),
            "shared": shared,
            "private": len(rows) - shared,
            "with_attachments": with_media,
            # Mood is a distribution, never an average. "Your average mood is
            # 3.2" is a number nobody can act on and a claim nobody made.
            "moods": [
                {"key": k, "label": MOOD_LABEL.get(k, k), "count": n,
                 "open_in": "journalz", "filter": {"mood": k}}
                for k, n in moods.most_common()
            ],
            "tags": [
                {"tag": t, "count": n, "open_in": "journalz", "filter": {"tag": t}}
                for t, n in tags.most_common(TOP_N)
            ],
            # A person in your diary opens their profile. This is the row that
            # would most obviously be a dead end and most obviously shouldn't.
            "people": [
                {"username": u, "count": n, "open_in": "social",
                 "filter": {"person": u}}
                for u, n in people.most_common(TOP_N)
            ],
            "places": [
                {"place": p, "count": n, "open_in": "journalz"}
                for p, n in places.most_common(TOP_N)
            ],
            "note": "Everything here is counted because it happened. Nothing "
                    "in your diary is scored, and nothing ever will be.",
        })


def _longest_streak(days):
    """The longest run of consecutive kept days in the set. 0 for an empty one.

    Computed from the days themselves rather than stored, so it can never
    disagree with the entries — a cached streak that drifts from the diary is
    a number that lies about the one thing it measures.
    """
    if not days:
        return 0
    best = run = 1
    ordered = sorted(days)
    for prev, cur in zip(ordered, ordered[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        best = max(best, run)
    return best


# ---------------------------------------------------------------- the prompts
#
# Ordered by how much of a day they represent. A recorded take is a bigger
# thing to have happened than a SpinaZ credit, so it is offered first, and the
# list stops at MAX_PROMPTS rather than handing somebody a wall of suggestions
# when the point is to get them writing.
MAX_PROMPTS = 5

# Resource → the sentence that starts an entry about it. Deliberately a first
# LINE and not a paragraph: the app hands over an opener and the door, the
# member writes the day. Anything more would be the app keeping the diary.
_LEDGER_OPENERS = {
    Transaction.RES_ENERGY: "Spent the day's ⚡ on",
    Transaction.RES_SPINAZ: "Earned 🍥 today from",
    Transaction.RES_PROMPTZ: "Ran the AI on",
    Transaction.RES_XP: "Levelled something up:",
    Transaction.RES_MONEY: "Money moved today —",
}


class JournalPromptsView(APIView):
    """GET ?day=YYYY-MM-DD — reasons to write today, drawn from your own day.

    Every diary app can ask "how was your day?". A generic prompt is a blank
    page with a question mark on it, and it is why diaries get abandoned in
    February: opening one costs you the work of remembering.

    This app already knows. The ledger records every resource that moved and,
    since `Transaction.open_in`, where it moved — so the prompts are the
    member's actual day, each with the words to start and the door back.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .journalz import parse_day
        day = parse_day(request.query_params.get("day")) or timezone.localdate()
        start = timezone.make_aware(
            timezone.datetime.combine(day, timezone.datetime.min.time()))
        end = start + timedelta(days=1)

        already = JournalEntry.objects.filter(author=request.user, day=day).exists()

        moved = list(Transaction.objects
                     .filter(user=request.user, created_at__gte=start,
                             created_at__lt=end)
                     .order_by("-created_at")[:40]
                     .values("resource", "amount", "amount_cents", "note", "open_in"))

        prompts, seen = [], set()
        for t in moved:
            note = (t["note"] or "").strip()
            if not note or note.lower() in seen:
                continue
            seen.add(note.lower())
            opener = _LEDGER_OPENERS.get(t["resource"] or Transaction.RES_MONEY, "Today:")
            prompts.append({
                "kind": t["resource"] or "money",
                # The opener is a first line, not a filled-in entry.
                "opener": f"{opener} {note}.",
                "because": note,
                # Nothing is a dead end, including a prompt: the row that
                # suggested writing about a battle opens the battle.
                "open_in": t["open_in"] or "",
            })
            if len(prompts) >= MAX_PROMPTS:
                break

        return Response({
            "day": day.isoformat(),
            "already_written": already,
            "prompts": prompts,
            # A member who did nothing gets the plain opener, not a fabricated
            # highlight. A prompt about a thing that did not happen is worse
            # than a blank page — now the app is wrong as well as empty.
            "fallback": ("Add to today's entry." if already
                         else "Nothing moved today. Write it anyway — a quiet "
                              "day is still a day, and the streak counts it."),
            "note": "Drawn from what you actually did today. Nothing here is "
                    "invented, and none of it is written for you.",
        })
