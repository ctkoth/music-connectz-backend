"""JournalZ 📔 — the diary, and the first surface here whose default is silence.

WHY THIS IS NOT JUST PostZ WITH A DATE ON IT
--------------------------------------------
Every other app in Music ConnectZ publishes. You make a thing, the room rates
it, the rating moves your price. A diary inverts that, and the inversion is the
whole product: **an entry is private until the member deliberately shares it.**
So the three rules land here differently than they land anywhere else.

**The cost/gain paradigm.** Writing costs nothing, and saying "free" is not
enough — a free action that EARNS has to say what it earns, which is why
`/journalz/cost/` states the QuestZ daily an entry completes before the member
writes it, not after. The one action here that spends anything is sharing, and
it spends exactly what a post spends, quoted from `post_cost_cents` so the two
can never drift.

**Substance before the game layer.** Nothing scores a journal entry. No craft
rating, no "depth", no word-count badge — a number on somebody's diary would be
the exact failure `directz_ai_rating` is in CLAUDE.md for: a score you could get
a good one of without getting good at anything. What is counted here is counted
because it happened: days kept, entries written, tags used. A streak is honest
because it measures days you turned up, and it is labelled as that and nothing
more.

**Cross-pollination.** An entry is the most dead-endable thing in the app — you
write it and it sits there. So every entry carries `destinations`: publish it as
a post, rework the words in OCC, send the take on it to the coach, message
somebody you tagged. And the traffic runs the other way too: `crosspost.py` now
offers "Keep it in your journal" on every post.

TAGGING, AND THE ONE RULE THAT MAKES IT SAFE
--------------------------------------------
An entry tags members and a place the way a post does. On a PRIVATE entry those
tags are notes to yourself: nobody is notified, nobody else can read the entry,
and the coordinates never leave the author's account. `JournalEntry.people` is
what the author wrote down; `JournalMention` is what actually left, and rows are
only ever written in `_mention` — during a share. That separation is the privacy
promise made structural rather than remembered.
"""
from datetime import date, timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.contrib.auth import get_user_model

from .catalog import journal_limits_for, over_char_limit
from .features import can_use, gate_detail
from .instruments import profile_for_app
from .models import (
    JOURNAL_MAX_ITEMS,
    JOURNAL_MAX_PEOPLE,
    JOURNAL_MAX_TAGS,
    JOURNAL_MOODS,
    JOURNAL_MOOD_KEYS,
    JournalEntry,
    JournalMention,
    blocked_user_ids,
    clean_link,
    membership_for,
    notify,
    record_observation,
)

User = get_user_model()

MOOD_LABEL = dict(JOURNAL_MOODS)

# How many entries one list call will return. A diary is read a month at a time,
# not a year — the date filters below are how you reach further back, and they
# are free at every tier.
PAGE = 200

# The QuestZ daily an entry completes. Named here so the composer can quote the
# reward before anything is written, and imported by questz.py so the number
# lives in exactly one place.
QUEST_ID = "journal-1"


# ---- sanitizing -----------------------------------------------------------

def clean_tags(raw, cap):
    """Lowercased, de-duplicated, capped. Returns (tags, dropped).

    `dropped` is returned rather than swallowed because a save handler that
    quietly loses half a member's tags and answers "saved" is the worst bug
    class in this app, and it has shipped twice.
    """
    seen, out, dropped = set(), [], []
    for x in (raw if isinstance(raw, list) else [])[:JOURNAL_MAX_TAGS]:
        t = str(x or "").strip().lstrip("#").lower()[:40]
        if not t or t in seen:
            continue
        seen.add(t)
        (out if len(out) < cap else dropped).append(t)
    return out, dropped


def clean_people(author, raw, cap):
    """Usernames that resolve to real, unblocked members. Returns (names, dropped).

    Blocked in either direction is out: tagging somebody who blocked you would
    turn a share into a way past the block, and a diary is not an exception to
    that.
    """
    wanted, seen = [], set()
    for x in (raw if isinstance(raw, list) else [])[:JOURNAL_MAX_PEOPLE]:
        n = str(x or "").strip().lstrip("@")[:150]
        if not n or n.lower() in seen or n.lower() == author.username.lower():
            continue
        seen.add(n.lower())
        wanted.append(n)
    if not wanted:
        return [], []
    blocked = set(blocked_user_ids(author))
    found = {u.username.lower(): u for u in
             User.objects.filter(username__in=wanted).exclude(id__in=blocked)}
    out, dropped = [], []
    for n in wanted:
        u = found.get(n.lower())
        if u is None:
            dropped.append({"name": n, "why": "no member by that name, or they've blocked you"})
        elif len(out) < cap:
            out.append(u.username)
        else:
            dropped.append({"name": n, "why": f"over your tier's limit of {cap} people on an entry"})
    return out, dropped


def clean_items(raw, cap):
    """Attachments in PostZ's shape, capped by tier. Returns (items, dropped)."""
    from .postz import clean_items as post_items
    items = post_items(raw)[:JOURNAL_MAX_ITEMS]
    return items[:cap], max(0, len(items) - cap)


def parse_day(raw):
    """A YYYY-MM-DD day, or today. Never the future: a diary records what
    happened, and an entry dated next Tuesday is a plan, which is TaskZ's job."""
    today = timezone.localdate()
    try:
        y, m, d = (int(x) for x in str(raw or "").split("-"))
        got = date(y, m, d)
    except (TypeError, ValueError):
        return today
    return min(got, today)


# ---- what a journal entry can go on to be ---------------------------------

FREE = {"resource": None, "amount": 0, "free_today": True, "affordable": True,
        "charged_on_failure": False}

# What the coach will listen to. Same two slots crosspost.py uses — text is not
# a performance and neither is a photograph.
COACHABLE = ("audio", "video")


def entry_media(e):
    """{slot: url} for the entry's attachments, one per kind, PostZ's shape."""
    slots = {"audio": "", "video": "", "image": "", "text": ""}
    for it in (e.items or []):
        kind = str(it.get("type") or "").lower()
        if kind not in slots or slots[kind]:
            continue
        slots[kind] = it.get("lyrics") if kind == "text" else (it.get("url") or "")
    return {k: v or "" for k, v in slots.items()}


def _take_kind(media):
    for kind in COACHABLE:
        if media.get(kind):
            return kind
    return ""


def carry(e, media):
    """The entry in the shape a destination fills its form from — the same keys
    `crosspost.carry` uses, so a destination doesn't care which app it came
    from."""
    return {
        "journal_id": e.id,
        "title": e.title or f"{e.day}",
        "description": e.body or "",
        "day": str(e.day),
        "tags": e.tags or [],
        "people": e.people or [],
        "place": e.place_name or "",
        "audio_url": media.get("audio", ""),
        "video_url": media.get("video", ""),
        "image_url": media.get("image", ""),
        "lyrics": media.get("text", ""),
    }


def destinations_for(e, user, media, share_cost=None):
    """Where this entry can go next, what each does, and the price up front.

    Written to the same contract as `crosspost.destinations_for`: a destination
    that cannot do anything with the entry is never `available`, and it says
    what it is MISSING rather than disappearing — a member looking at a
    words-only entry should read that the coach wants a recording, not conclude
    SingZ is broken.
    """
    take = _take_kind(media)
    words = bool((e.body or "").strip() or media.get("text"))
    no_take = [] if take else ["a recording — attach audio or video to this entry"]
    # An entry somebody shared with you is readable, and that is ALL it is.
    # Publishing it, coaching the take on it or feeding it to your own OCC are
    # all things only its author gets to do — the server already refuses each of
    # them, and a door that can only end in a refusal has to say so on the row
    # rather than after the tap. This is the same rule the release door on a
    # post follows: "your own post — a release is the author's to start".
    mine = e.author_id == user.id
    not_yours = [] if mine else [f"your own entry — this one is @{e.author.username}'s"]
    out = [{
        "app": "postz",
        "label": "Publish it as a post",
        "target": "journalz-share",
        "action": "share",
        "what": "Put this entry up as a PostZ — the words, the attachments and the "
                "place come with it. Everyone you tagged is told, once, at that "
                "point and not before.",
        "needs": not_yours + ([] if (e.title or words or take)
                             else ["something written or attached"]),
        "cost": share_cost or FREE,
        "gain": {"what": "reach, ratings and comments on what you wrote"},
        "carry": carry(e, media),
        "warn": ("This entry is private. Publishing changes that — the words leave "
                 "your diary." if e.is_private else ""),
    }, {
        "app": "occ",
        "label": "Rework it in OCC",
        "target": "occ-workz",
        "action": "seed",
        "what": "Open the entry in WorkZ with its words already in — turn a page of "
                "the diary into a verse, a bio, a pitch. Nothing is written back "
                "unless you ask for it.",
        "needs": not_yours + ([] if words else ["words to work on — write the entry first"]),
        "cost": FREE,
        "gain": {"what": "a WorkZ draft; keeping it is free"},
        "carry": carry(e, media),
    }]
    for app_key in ("singz", "rapz"):
        p = profile_for_app(app_key)
        out.append({
            "app": app_key,
            "label": f"Coach the take in {p['label']}",
            "target": "bosstake-mic",
            "action": "coach",
            "what": f"Send the {take or 'take'} on this entry to the {p['coach']} — "
                    "scored, with one drill to run next.",
            "needs": not_yours + no_take,
            # Quoted by the coach itself before it spends anything. Repeating a
            # PromptZ price here would be a second copy of a number that moves
            # during a session, and a stale quote is the same lie as no quote.
            "cost": None,
            "gain": {"what": "a scored take with a drill to run next"},
            "carry": carry(e, media),
            "coach_kind": take,
        })
    out.append({
        "app": "messagez",
        "label": "Send it to someone you tagged",
        "target": "messagez-compose",
        "action": "message",
        "what": "Message the people on this entry with what you wrote, without "
                "publishing it to anyone else.",
        # The author's, like the rest: forwarding somebody else's entry to the
        # people THEY tagged is not a handoff, it's a repost with their name on
        # it and none of their say-so.
        "needs": not_yours + ([] if (e.people or []) else ["somebody tagged on the entry"]),
        "cost": FREE,
        "gain": {"what": "the words reach exactly who you meant"},
        "carry": carry(e, media),
    })
    out.append({
        "app": "habitz",
        "label": "See what you keep writing about",
        "target": "habitz-list",
        "action": "open",
        "what": "Your repeated tags, tallied — HabitZ only records this while you "
                "have it switched on, and switching it off forgets what it kept.",
        "needs": [],
        "cost": FREE,
        "gain": {"what": "the patterns in a year of entries"},
        "carry": carry(e, media),
    })
    for d in out:
        d["available"] = not d["needs"]
    return out


# ---- serializing ----------------------------------------------------------

# "nobody counted", as distinct from "counted, and it is zero" — the same
# distinction crosspost.py draws for a take's size, and for the same reason: a
# list resolves every count in ONE query and passes the answer down, while a
# single-entry response passes nothing and has it read here. Without this the
# diary ran a COUNT per row, which is two hundred queries to print a number
# that is usually zero.
_UNSET = object()


def mention_counts(entries):
    """{entry_id: how many people were told} for a page, in ONE query."""
    return dict(JournalMention.objects
                .filter(entry_id__in=[e.id for e in entries])
                .values_list("entry_id")
                .annotate(n=Count("id")))


def entry_dict(e, user, share_cost=None, with_destinations=True, mentions=_UNSET):
    """One entry, for the member reading it.

    A reader who is not the author gets the place NAME and never the
    coordinates unless the author turned `place_exact` on. The redaction is here
    rather than in the view because there is more than one way to reach an entry
    — yours, tagged-in, and a share quote — and a privacy rule that has to be
    remembered at three call sites is a rule that gets forgotten at one.
    """
    mine = e.author_id == user.id
    media = entry_media(e)
    exact = mine or e.place_exact
    return {
        "id": e.id,
        "author": e.author.username,
        "mine": mine,
        "day": str(e.day),
        "title": e.title,
        "body": e.body,
        "mood": e.mood,
        "mood_label": MOOD_LABEL.get(e.mood, ""),
        "weather": e.weather,
        "tags": e.tags or [],
        "people": e.people or [],
        "place": {
            "name": e.place_name,
            "lat": e.place_lat if exact else None,
            "lng": e.place_lng if exact else None,
            "exact": bool(e.place_exact),
            # Said on the row, not in a settings screen nobody opens.
            "note": ("Only the place name travels when you share this — the "
                     "coordinates stay in your diary."
                     if (mine and e.place_name and not e.place_exact) else ""),
        },
        "items": e.items or [],
        "media": media,
        # What was playing while this got written — a pointer, not an
        # attachment; see the field's own comment on the model.
        "link": e.link or {},
        "visibility": e.visibility,
        "private": e.is_private,
        "shared_post_id": e.shared_post_id,
        # How many of the tagged people have actually been told. On a private
        # entry this is zero and stays zero, which is the point.
        "mentions_sent": (e.mentions.count() if mentions is _UNSET else mentions) if mine else 0,
        "created_at": e.created_at.isoformat(),
        "edited_at": e.edited_at.isoformat() if e.edited_at else None,
        "open_in": "postz",
        "destinations": destinations_for(e, user, media, share_cost) if with_destinations else [],
    }


def streak_days(user, when=None):
    """Consecutive days ending today with an entry.

    Today not counting yet is deliberate and matches QuestZ: a streak is a
    record of days you turned up, and today is not over. It is a count of days,
    never a claim about the writing — see the substance note at the top.
    """
    today = (when or timezone.localdate())
    days = set(JournalEntry.objects.filter(author=user).values_list("day", flat=True))
    n, cursor = 0, today
    while True:
        if cursor not in days:
            if cursor == today:
                cursor -= timedelta(days=1)
                continue
            break
        n += 1
        cursor -= timedelta(days=1)
    return n


def _limits(user):
    return journal_limits_for(membership_for(user).tier)


def used_today(user, day):
    return JournalEntry.objects.filter(author=user, day=day).count()


def share_quote(user, skills=None):
    """What publishing costs, in the shape every other cost in this app uses.

    Taken from `post_cost_cents` rather than restated, because publishing IS
    posting: a journal entry that charged its own made-up price would be a
    second definition of what a post costs, and the two would drift within a
    release.
    """
    from .models import wallet_for
    from .postz import post_cost_cents
    total, lines = post_cost_cents(user, skills or [])
    w = wallet_for(user)
    return {
        "resource": "energy",
        "amount": total,
        "lines": lines,
        "energy": w.energy,
        "charged": min(total, max(0, w.energy)),
        "affordable": w.energy >= total,
        "free_today": total == 0,
        "charged_on_failure": False,
    }


# ---- the views ------------------------------------------------------------

class JournalCostView(APIView):
    """GET /api/economy/journalz/cost/ — the price and the gain, before writing.

    Writing is free. That is not the interesting half: a free action that EARNS
    has to say what it earns, so this states the QuestZ daily an entry completes
    and what it pays, alongside the tier's room and what the next tier up adds.
    A member should be able to read this screen and know exactly what today's
    entry costs them, gets them, and how much of it will fit.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .catalog import chars_unlimited, limits_for
        from .questz import BY_ID
        tier = membership_for(request.user).tier
        lim = _limits(request.user)
        day = parse_day(request.query_params.get("day"))
        quest = BY_ID.get(QUEST_ID) or {}
        return Response({
            "cost": {"resource": None, "amount": 0, "free_today": True,
                     "affordable": True, "charged_on_failure": False},
            # Stated up front, with the number, because "+15 ⚡ on your first
            # entry today" is the whole reason somebody starts a diary they
            # would otherwise mean to start on Monday.
            "gain": {
                "resource": "energy",
                "amount": quest.get("energy", 0),
                "quest_id": QUEST_ID,
                "app": "mimez", "target": "questz-daily",
                "what": f"Your first entry each day completes the {quest.get('title', 'daily')} "
                        f"QuestZ — claim it on the quest board.",
                "once_per_day": True,
            },
            "tier": tier,
            "limits": {**lim,
                       "char_limit": limits_for(tier)["char_limit"],
                       "char_limit_unlimited": chars_unlimited(tier)},
            "day": str(day),
            "used_today": used_today(request.user, day),
            "moods": [{"key": k, "label": v} for k, v in JOURNAL_MOODS],
            "streak": streak_days(request.user),
            "note": "Entries are private until you share one. Tagging somebody on a "
                    "private entry tells them nothing.",
        })


class JournalZView(APIView):
    """GET the member's diary; POST writes or edits an entry.

    Filters, all free at every tier: `?day=`, `?from=`/`?to=`, `?tag=`,
    `?person=`, `?mood=`, `?q=` (title and body), and `?view=tagged` for entries
    other members shared with you on.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = request.query_params
        view = (q.get("view") or "mine").lower()
        if view == "tagged":
            # Only what actually left somebody's diary. Reading `people` here
            # instead would show an entry that was never shared.
            qs = (JournalEntry.objects
                  .filter(mentions__user=request.user)
                  .exclude(author=request.user)
                  .exclude(visibility=JournalEntry.VIS_PRIVATE)
                  .exclude(author_id__in=blocked_user_ids(request.user)))
        else:
            qs = JournalEntry.objects.filter(author=request.user)
        qs = qs.select_related("author")

        if q.get("day"):
            qs = qs.filter(day=parse_day(q.get("day")))
        if q.get("from"):
            qs = qs.filter(day__gte=parse_day(q.get("from")))
        if q.get("to"):
            qs = qs.filter(day__lte=parse_day(q.get("to")))
        if q.get("mood") in JOURNAL_MOOD_KEYS:
            qs = qs.filter(mood=q.get("mood"))
        text = (q.get("q") or "").strip()
        if text:
            qs = qs.filter(Q(title__icontains=text) | Q(body__icontains=text))
        qs = qs.distinct()
        # Tag and person live in JSON columns, so they are matched in Python:
        # SQLite has no JSON containment operator, production is Postgres, and
        # a filter that only works on one of the two is exactly the gap
        # CLAUDE.md warns about under Testing.
        #
        # Scanned in a cursor and stopped at a full page, NOT applied to a page
        # already cut: filtering after the slice would search the newest 200
        # entries and quietly report "no entries tagged #bristol" to somebody
        # who has thirty, from the year before last. A search that silently
        # only looks at the top of the pile is worse than no search.
        tag = (q.get("tag") or "").strip().lstrip("#").lower()
        person = (q.get("person") or "").strip().lstrip("@").lower()
        if tag or person:
            entries = []
            for e in qs.iterator(chunk_size=200):
                if tag and tag not in (e.tags or []):
                    continue
                if person and person not in [str(x).lower() for x in (e.people or [])]:
                    continue
                entries.append(e)
                if len(entries) >= PAGE:
                    break
        else:
            entries = list(qs[:PAGE])

        # Read ONCE for the page, like the coach's price on the PostZ feed: it
        # reads the wallet and every row's share door quotes it.
        quote = share_quote(request.user)
        told = mention_counts(entries)
        rows = [entry_dict(e, request.user, share_cost=quote,
                           mentions=told.get(e.id, 0)) for e in entries]

        # Counts, not scores. Every number here is a tally of something that
        # happened — see the substance note at the top of this module.
        mine_all = JournalEntry.objects.filter(author=request.user)
        tally = {}
        for tags in mine_all.values_list("tags", flat=True):
            for t in (tags or []):
                tally[t] = tally.get(t, 0) + 1
        return Response({
            "entries": rows,
            "view": view,
            "count": len(rows),
            "streak": streak_days(request.user),
            "days_kept": mine_all.values("day").distinct().count(),
            "entries_kept": mine_all.count(),
            "tags": [{"tag": t, "count": n} for t, n in
                     sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[:40]],
            "moods": [{"key": k, "label": v} for k, v in JOURNAL_MOODS],
            "streak_note": "Days you turned up. It doesn't say anything about the "
                           "writing, and nothing here scores it.",
        })

    def post(self, request):
        d = request.data
        if d.get("entry_id") is not None:
            return self._edit(request, d)

        user = request.user
        tier = membership_for(user).tier
        lim = _limits(user)
        day = parse_day(d.get("day"))

        used = used_today(user, day)
        if used >= lim["per_day"]:
            return Response({
                "detail": f"That's {used} entries for {day} — your tier keeps "
                          f"{lim['per_day']} a day. Upgrade in MembershipZ for more, "
                          "or add to the entry you already wrote.",
                "used": used, "cap": lim["per_day"], "day": str(day),
                "required_tier": "premium",
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        body = str(d.get("body", ""))
        cap = over_char_limit(body, tier)
        if cap is not None:
            return Response({
                "detail": f"That's longer than your tier's {cap:,}-character limit. "
                          "Upgrade in MembershipZ, or split it across two entries.",
                "char_limit": cap, "length": len(body), "required_tier": "premium",
            }, status=status.HTTP_400_BAD_REQUEST)

        title = str(d.get("title", "")).strip()[:160]
        link = clean_link(d.get("link"))
        if not (title or body.strip() or d.get("items") or link):
            return Response({"detail": "An entry needs something in it — a title, "
                                       "some words, an attachment, or a linked track."},
                            status=status.HTTP_400_BAD_REQUEST)

        tags, tags_dropped = clean_tags(d.get("tags"), lim["tags"])
        people, people_dropped = clean_people(user, d.get("people"), lim["people"])
        items, items_dropped = clean_items(d.get("items"), lim["attachments"])
        vis = str(d.get("visibility", JournalEntry.VIS_PRIVATE)).lower()
        if vis not in dict(JournalEntry.VIS_CHOICES):
            vis = JournalEntry.VIS_PRIVATE

        e = JournalEntry.objects.create(
            author=user, day=day, title=title, body=body,
            mood=str(d.get("mood", ""))[:12] if d.get("mood") in JOURNAL_MOOD_KEYS else "",
            weather=str(d.get("weather", ""))[:40],
            tags=tags, people=people, items=items, link=link,
            place_name=str(d.get("place_name", ""))[:120],
            place_lat=_coord(d.get("place_lat")), place_lng=_coord(d.get("place_lng")),
            place_exact=bool(d.get("place_exact")),
            visibility=vis,
        )
        # Cross-pollination, in the direction CLAUDE.md's own example points:
        # what you keep writing about becomes something HabitZ can show you.
        # Silent unless the member switched that observation on themselves.
        for t in tags:
            record_observation(user, "habit", f"journal-tag:{t}",
                               label=f"Writes about “{t}”",
                               app_key="journalz", target="journalz:journalz-entries")
        # A share is the only thing that tells anybody they were tagged, so a
        # non-private entry written that way sends its mentions now.
        told = self._mention(e) if not e.is_private else []
        return Response({
            **entry_dict(e, user),
            # Never silently. A tag that didn't make it says so and says why.
            "dropped": {"tags": tags_dropped, "people": people_dropped,
                        "attachments": items_dropped},
            "notified": told,
        }, status=status.HTTP_201_CREATED)

    def _edit(self, request, d):
        """Edit an entry. Yours, at any age, and deliberately not on a window.

        The tier edit window exists so a POST can't be rewritten under people who
        already read and rated it. A private diary entry has no such readers —
        that is what it means for it to be private — so holding a member to four
        minutes on their own diary would be a rule protecting nobody. An entry
        that has been SHARED is a different thing, and the post it produced
        carries its own history under the post rules.
        """
        user = request.user
        e = JournalEntry.objects.filter(pk=d.get("entry_id"), author=user).first()
        if not e:
            return Response({"detail": "entry not found"}, status=status.HTTP_404_NOT_FOUND)
        tier = membership_for(user).tier
        lim = _limits(user)
        dropped = {"tags": [], "people": [], "attachments": 0}
        fields = []
        if "title" in d:
            e.title = str(d.get("title", "")).strip()[:160]
            fields.append("title")
        if "body" in d:
            body = str(d.get("body", ""))
            cap = over_char_limit(body, tier)
            if cap is not None:
                return Response({
                    "detail": f"That's longer than your tier's {cap:,}-character limit.",
                    "char_limit": cap, "length": len(body), "required_tier": "premium",
                }, status=status.HTTP_400_BAD_REQUEST)
            e.body = body
            fields.append("body")
        if "day" in d:
            e.day = parse_day(d.get("day"))
            fields.append("day")
        if "mood" in d:
            e.mood = d["mood"] if d.get("mood") in JOURNAL_MOOD_KEYS else ""
            fields.append("mood")
        if "weather" in d:
            e.weather = str(d.get("weather", ""))[:40]
            fields.append("weather")
        if "tags" in d:
            e.tags, dropped["tags"] = clean_tags(d.get("tags"), lim["tags"])
            fields.append("tags")
        if "people" in d:
            e.people, dropped["people"] = clean_people(user, d.get("people"), lim["people"])
            fields.append("people")
        if "items" in d:
            e.items, dropped["attachments"] = clean_items(d.get("items"), lim["attachments"])
            fields.append("items")
        if "link" in d:
            e.link = clean_link(d.get("link"))
            fields.append("link")
        for key, attr in (("place_name", "place_name"), ("place_exact", "place_exact")):
            if key in d:
                setattr(e, attr, str(d[key])[:120] if key == "place_name" else bool(d[key]))
                fields.append(attr)
        for key in ("place_lat", "place_lng"):
            if key in d:
                setattr(e, key, _coord(d[key]))
                fields.append(key)
        if "visibility" in d:
            vis = str(d.get("visibility", "")).lower()
            if vis in dict(JournalEntry.VIS_CHOICES):
                e.visibility = vis
                fields.append("visibility")
        e.edited_at = timezone.now()
        fields.append("edited_at")
        e.save(update_fields=sorted(set(fields)))
        # Widening an entry is a share: the people on it are told now, and the
        # `unique_together` on JournalMention is what stops a member who toggles
        # visibility twice from notifying them twice.
        told = [] if e.is_private else self._mention(e)
        return Response({**entry_dict(e, user), "dropped": dropped, "notified": told})

    @staticmethod
    def _mention(e):
        """Tell the people tagged on a NON-private entry, once each, ever.

        The only place in JournalZ that writes a JournalMention or sends a
        notification. Everything else can tag freely because this is the single
        door out.
        """
        if e.is_private:
            return []
        told = []
        for name in (e.people or []):
            u = User.objects.filter(username=name).first()
            if not u or u.id == e.author_id:
                continue
            _row, made = JournalMention.objects.get_or_create(entry=e, user=u)
            if not made:
                continue
            notify(u, "comment",
                   f"@{e.author.username} tagged you in a journal entry — "
                   f"“{e.title or e.day}” 📔",
                   actor=e.author, item_id=f"journal:{e.id}")
            told.append(u.username)
        return told


def _coord(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


class JournalEntryView(APIView):
    """GET one entry with its doors; DELETE removes it.

    An entry you were tagged in is readable here too — the same redaction
    `entry_dict` applies everywhere, so the coordinates on somebody else's
    entry are absent rather than filtered out by the client.
    """

    permission_classes = [IsAuthenticated]

    def _get_entry(self, request, pk):
        e = JournalEntry.objects.filter(pk=pk).select_related("author").first()
        if not e:
            return None
        if e.author_id == request.user.id:
            return e
        if e.is_private:
            return None
        if not JournalMention.objects.filter(entry=e, user=request.user).exists():
            return None
        return e

    def get(self, request, pk):
        e = self._get_entry(request, pk)
        if not e:
            return Response({"detail": "entry not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(entry_dict(e, request.user, share_cost=share_quote(request.user)))

    def delete(self, request, pk):
        e = JournalEntry.objects.filter(pk=pk, author=request.user).first()
        if not e:
            return Response({"detail": "entry not found"}, status=status.HTTP_404_NOT_FOUND)
        day, post_id = str(e.day), e.shared_post_id
        e.delete()
        return Response({
            "deleted": True, "id": pk, "day": day,
            # Deleting the diary entry does not unpublish the post it became —
            # said plainly, because a member who assumes it does has just left
            # something public they meant to take down.
            "shared_post_id": post_id,
            "note": ("The post you published from this entry is still up — "
                     "delete it in PostZ if you want it gone." if post_id else ""),
        })


class JournalShareView(APIView):
    """GET what publishing this costs and who it tells; POST does it.

    Two methods on purpose. The whole paradigm is that a price is stated before
    it is paid, and this is the one action in JournalZ that spends anything and
    the only one that tells another human being something. So the quote is a
    request a client can make without committing to anything, and it names the
    people who will be notified — by name, before they are.
    """

    permission_classes = [IsAuthenticated]

    def _entry(self, request, pk):
        return JournalEntry.objects.filter(pk=pk, author=request.user).select_related("author").first()

    def get(self, request, pk):
        e = self._entry(request, pk)
        if not e:
            return Response({"detail": "entry not found"}, status=status.HTTP_404_NOT_FOUND)
        skills = [s for s in (x.strip() for x in
                              (request.query_params.get("skills") or "").split(",")) if s]
        already = set(e.mentions.values_list("user__username", flat=True))
        return Response({
            "entry_id": e.id,
            "cost": share_quote(request.user, skills),
            "gain": {"what": "a PostZ others can rate and comment on, and the "
                             "people you tagged told once"},
            "will_notify": [n for n in (e.people or []) if n not in already],
            "already_notified": sorted(already),
            "place_shared": e.place_name or "",
            "coordinates_shared": bool(e.place_exact and e.place_lat is not None),
            "currently": e.visibility,
            "warn": ("This entry is private. Publishing it changes that — the "
                     "words leave your diary and the entry is marked shared."
                     if e.is_private else ""),
            "already_shared_post_id": e.shared_post_id,
        })

    def post(self, request, pk):
        e = self._entry(request, pk)
        if not e:
            return Response({"detail": "entry not found"}, status=status.HTTP_404_NOT_FOUND)
        if e.shared_post_id:
            return Response({
                "detail": "This entry is already published — edit the post in PostZ.",
                "post_id": e.shared_post_id,
            }, status=status.HTTP_409_CONFLICT)
        from .postz import create_post

        d = request.data
        vis = str(d.get("visibility", JournalEntry.VIS_PUBLIC)).lower()
        if vis == JournalEntry.VIS_PRIVATE:
            return Response({"detail": "Publishing to just yourself is what the entry "
                                       "already is. Pick public or members only."},
                            status=status.HTTP_400_BAD_REQUEST)
        media = entry_media(e)
        body = e.body or ""
        if e.place_name:
            body = f"{body}\n\n📍 {e.place_name}".strip()
        post, info, err = create_post(request.user, {
            "title": e.title or f"Journal — {e.day}",
            "description": body,
            "visibility": vis,
            "skills_used": d.get("skills_used") or [],
            "media_type": next((k for k in ("audio", "video", "image") if media.get(k)), ""),
            "media_url": next((media[k] for k in ("audio", "video", "image") if media.get(k)), ""),
            "items": e.items or [],
        })
        if err:
            # The entry is untouched when the post refuses — the daily submission
            # cap and the slot rule are the post's, and a diary entry silently
            # marked "shared" behind a 429 would be the worst of both.
            return Response(err[0], status=err[1])
        e.shared_post = post
        e.visibility = vis
        e.save(update_fields=["shared_post", "visibility"])
        told = JournalZView._mention(e)
        return Response({
            **entry_dict(e, request.user),
            "post_id": post.id,
            "notified": told,
            **info,
        }, status=status.HTTP_201_CREATED)


class JournalLookbackView(APIView):
    """GET /api/economy/journalz/lookback/ — this date, in every year you kept it.

    Premium, through the standard gate: `can_use` decides, `gate_detail` writes
    the refusal, and the client renders the lock from `/features/` rather than
    keeping its own copy of the rule.

    Gated rather than free because of what it is: it only exists for a member
    who already has years of entries, which means it is a reason to stay rather
    than a toll on starting. The diary itself is free, and a paywall on writing
    something down is one this app is not going to have.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tier = membership_for(request.user).tier
        if not can_use(tier, "journalz_lookback"):
            return Response({**gate_detail("journalz_lookback"),
                             # A gate that only says no is a dead end. Say what is
                             # behind it, so the upgrade is a decision and not a
                             # guess.
                             "preview": self._preview(request.user)},
                            status=status.HTTP_403_FORBIDDEN)
        day = parse_day(request.query_params.get("day") or str(timezone.localdate()))
        rows = [e for e in JournalEntry.objects.filter(
            author=request.user, day__month=day.month, day__day=day.day)
            .select_related("author") if e.day != day]
        told = mention_counts(rows)
        return Response({
            "day": f"{day.month:02d}-{day.day:02d}",
            "years": [entry_dict(e, request.user, with_destinations=False,
                                 mentions=told.get(e.id, 0)) for e in rows],
            "count": len(rows),
        })

    @staticmethod
    def _preview(user):
        """How many entries are waiting behind the gate, without showing one.
        A count is honest and a teaser is not — this says what upgrading opens
        for THIS member, which for a member with no history is nothing, and it
        says that too."""
        today = timezone.localdate()
        n = JournalEntry.objects.filter(author=user, day__month=today.month,
                                        day__day=today.day).exclude(day=today).count()
        return {"entries_on_this_date": n,
                "what": (f"You have {n} entr{'y' if n == 1 else 'ies'} written on this "
                         "date in other years." if n else
                         "Nothing on this date in another year yet — this one grows "
                         "as you keep it.")}


class JournalExportView(APIView):
    """GET /api/economy/journalz/export/?format=md|json — the whole journal out.

    Premium, same gate treatment. The line this walks: a member's own words are
    never held hostage — every entry is readable and searchable in the app at
    every tier, free forever. What Premium buys is the FILE: one document, dated,
    with the attachments listed, that you can keep somewhere this app isn't.

    `/account/export/` still exports everything for everybody, gate or no gate,
    because that is a data right and not a feature.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tier = membership_for(request.user).tier
        if not can_use(tier, "journalz_export"):
            n = JournalEntry.objects.filter(author=request.user).count()
            return Response({**gate_detail("journalz_export"),
                             "entries": n,
                             "what": f"{n} entr{'y' if n == 1 else 'ies'} would come out "
                                     "as one file.",
                             # Never leave somebody believing their words are
                             # locked up. They are not, and the door is here.
                             "always_free": "Your account export at "
                                            "/api/economy/account/export/ includes every "
                                            "entry at any tier — this is the formatted "
                                            "journal, not access to your own words."},
                            status=status.HTTP_403_FORBIDDEN)
        fmt = (request.query_params.get("format") or "md").lower()
        entries = list(JournalEntry.objects.filter(author=request.user)
                       .select_related("author").order_by("day", "created_at"))
        if fmt == "json":
            told = mention_counts(entries)
            return Response({
                "format": "json",
                "count": len(entries),
                "entries": [entry_dict(e, request.user, with_destinations=False,
                                       mentions=told.get(e.id, 0)) for e in entries],
            })
        return Response({
            "format": "md",
            "count": len(entries),
            "filename": f"journalz-{request.user.username}-{timezone.localdate()}.md",
            "markdown": _markdown(request.user, entries),
        })


def _markdown(user, entries):
    out = [f"# JournalZ — {user.username}", ""]
    for e in entries:
        out.append(f"## {e.day}" + (f" — {e.title}" if e.title else ""))
        meta = []
        if e.mood:
            meta.append(MOOD_LABEL.get(e.mood, e.mood))
        if e.weather:
            meta.append(e.weather)
        if e.place_name:
            meta.append(f"📍 {e.place_name}")
        if e.people:
            meta.append(" ".join(f"@{p}" for p in e.people))
        if meta:
            out.append("*" + " · ".join(meta) + "*")
        out.append("")
        if e.body:
            out.append(e.body)
            out.append("")
        if e.tags:
            out.append(" ".join(f"#{t}" for t in e.tags))
            out.append("")
        for it in (e.items or []):
            label = it.get("title") or it.get("type") or "attachment"
            if it.get("url"):
                out.append(f"- [{label}]({it['url']})")
        out.append("")
    return "\n".join(out)
