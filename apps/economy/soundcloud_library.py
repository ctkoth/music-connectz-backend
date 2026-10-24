"""The manager for tracks already imported from SoundCloud.

`soundcloud_import.py` lands every track as a PRIVATE draft and keeps no token,
so there is no choosing at import time. Choosing lives here: look at the
imported posts, then set each one (or a batch) to public / restricted / private.

Nothing in this file posts anything itself. Every change goes through
`postz.change_visibility`, the same function PostZ's own edit uses, so there is
one price, one private-track consent rule and one place a charge is written.

NOTHING HERE HAS RUN AGAINST SOUNDCLOUD. It never talks to SoundCloud: it reads
what the import stored. Tests mock the import.

DECISIONS (see CLAUDE.md-style reasoning in the tests)
* Price: whatever `change_visibility` charges (the unpaid shortfall of the
  post's skill cost; an import has no skills, so usually 0). The preview calls
  `post_cost_cents` itself, never a copy of it. A batch is STRICT: an item whose
  cost cannot be covered is not published for part of its price; the batch stops.
* Dating: a call that publishes TWO OR MORE drafts dates them to their own
  SoundCloud release date (never later than they already are). A publish of one
  keeps its date, so it can't be used to bump a post to the top or to re-earn the
  fresh-post royalty boost. Without this, 200 posts imported together all sit at
  the same minute of the feed (the feed reads the newest 300 by created_at).
* No notification is sent: PostZ has never notified followers of a new post or
  a visibility change, and a batch must not start.
* No daily limit applies: DailySubmission counts scored/media posts at creation,
  and neither an embed-only import nor a visibility change is one.
"""
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Post, RESTRICTED_JOIN_REWARD_SPINAZ, wallet_for
from .postz import (JOIN_MIN_ACTIVE_SECONDS, JOIN_REWARD_DAILY_CAP_PER_AUTHOR,
                    VisibilityRefused, change_visibility, post_cost_cents)
from .soundcloud_import import has_private_track, import_cap, is_import_embed
from .catalog import limits_for
from .models import membership_for

PAGE_SIZE = 100
# Most items one apply call works through. A request-time bound (each item is
# its own transaction), NOT flood protection: dating is what keeps a batch from
# burying the feed. The client carries on in further calls.
MAX_PER_CALL = 100
# Most ids one preview/apply request may name.
MAX_IDS = 5000
BATCH_MIN = 2
VISIBILITIES = ("private", "restricted", "public")

DATING_SENTENCE = ("Publishing two or more at once dates each to the day you released it on "
                   "SoundCloud, so they sit where they belong in the feed instead of all landing "
                   "at the top. That also means the short edit window on those posts is already "
                   "over. Publishing a single track keeps its current date.")


def import_embed(post):
    for e in (post.embeds or []):
        if is_import_embed(e):
            return e
    return None


def _imported_posts(user):
    out = []
    qs = (Post.objects.filter(author=user).exclude(embeds=[])
          .only("id", "title", "visibility", "embeds", "created_at", "skills_used",
                "skill_cost_cents", "contributors"))
    for p in qs:
        if import_embed(p):
            out.append(p)
    return out


def _parse(v):
    try:
        return datetime.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


def _sc_url(e):
    """A public SoundCloud address, or "" — never a private track's secret."""
    if e.get("private_on_sc"):
        return ""
    if e.get("permalink"):
        return e["permalink"]
    try:
        inner = parse_qs(urlparse(e.get("url") or "").query).get("url", [""])[0]
        u = urlparse(inner)
        if u.scheme == "https" and u.hostname in ("soundcloud.com", "www.soundcloud.com"):
            return inner
    except ValueError:
        pass
    return ""


class Pricer:
    """post_cost_cents, asked once per distinct skills list."""

    def __init__(self, user):
        self.user, self.memo = user, {}

    def owed(self, p):
        if p.visibility != "private":
            return 0
        key = tuple(s for s in (p.skills_used or []) if isinstance(s, str))
        if key not in self.memo:
            self.memo[key] = post_cost_cents(self.user, list(key))[0]
        return max(0, self.memo[key] - p.skill_cost_cents)


def _row(p, pricer, energy):
    e = import_embed(p)
    owed = pricer.owed(p)
    can = owed <= energy
    return {
        "id": p.id, "title": p.title, "soundcloud_url": _sc_url(e),
        "artwork": e.get("artwork") or "",
        "visibility": p.visibility,
        "private_on_sc": bool(e.get("private_on_sc")),
        "imported_at": e.get("imported_at") or "",
        "released_at": e.get("released_at") or "",
        "created_at": p.created_at.isoformat(),
        "publish_cost": {"resource": "energy", "amount": owed},
        "can_publish": can,
        "why_not": "" if can else f"Publishing this one costs {owed} ⚡ and you have {energy}.",
    }


def _explain():
    return {
        "public": "Appears in the feed and on your profile. Anyone can open it and play it from "
                  "SoundCloud's own player.",
        "restricted": ("Only signed-in members can open it. When a different member opens it and "
                       f"stays {JOIN_MIN_ACTIVE_SECONDS} seconds, you earn {RESTRICTED_JOIN_REWARD_SPINAZ} \U0001f365 "
                       f"(once per member; up to {JOIN_REWARD_DAILY_CAP_PER_AUTHOR} \U0001f365 a day across your posts)."),
        "private": "Only you can see it. Nothing is sent to anyone.",
    }


def _sort(posts):
    def key(p):
        e = import_embed(p)
        return (_parse(e.get("released_at")) or p.created_at, p.id)
    return sorted(posts, key=key, reverse=True)


class LibraryView(APIView):
    """GET /api/economy/soundcloud/library/?page=1&visibility=&q=&ids=1"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        posts = _sort(_imported_posts(user))
        counts = {"total": len(posts), **{v: 0 for v in VISIBILITIES}, "private_on_sc": 0}
        for p in posts:
            counts[p.visibility] = counts.get(p.visibility, 0) + 1
            if import_embed(p).get("private_on_sc"):
                counts["private_on_sc"] += 1
        vis = request.query_params.get("visibility", "")
        q = (request.query_params.get("q") or "").strip().lower()
        sel = [p for p in posts if (not vis or p.visibility == vis) and (not q or q in p.title.lower())]
        if request.query_params.get("ids") in ("1", "true"):
            return Response({"ids": [p.id for p in sel][:MAX_IDS * 2], "matching": len(sel)})
        try:
            page = max(1, int(request.query_params.get("page") or 1))
        except ValueError:
            page = 1
        chunk = sel[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        energy = max(0, wallet_for(user).energy or 0)
        pricer = Pricer(user)
        tier = membership_for(user).tier
        cap = import_cap(tier)
        return Response({
            "rows": [_row(p, pricer, energy) for p in chunk],
            "page": page, "page_size": PAGE_SIZE, "matching": len(sel),
            "pages": max(1, -(-len(sel) // PAGE_SIZE)),
            "counts": counts,
            "energy": energy,
            "explain": _explain(),
            "dating": DATING_SENTENCE,
            "max_per_call": MAX_PER_CALL,
            # The ladder, read from the catalogue: None = the whole library.
            "import": {"tier": tier, "max_tracks": cap, "whole_catalogue": cap is None,
                       "ladder": {t: limits_for(t)["soundcloud_import"] for t in ("free", "premium", "statz")}},
        })


def _ids(d):
    raw = d.get("ids")
    out, seen = [], set()
    for i in raw if isinstance(raw, list) else []:
        try:
            i = int(i)
        except (TypeError, ValueError):
            continue
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out[:MAX_IDS]


def _load(user, ids):
    by_id = {}
    for i in range(0, len(ids), 400):
        for p in Post.objects.filter(author=user, id__in=ids[i:i + 400]).only(
                "id", "title", "visibility", "embeds", "created_at", "skills_used",
                "skill_cost_cents", "contributors"):
            if import_embed(p):
                by_id[p.id] = p
    return by_id


def _target(d):
    v = str(d.get("visibility") or "").strip().lower()
    return v if v in VISIBILITIES else None


def _plan(user, ids, by_id, target, confirm):
    """Walk the request in order, exactly as apply will."""
    pricer = Pricer(user)
    have = max(0, wallet_for(user).energy or 0)
    left = have
    items, stopped = [], None
    for n, i in enumerate(ids):
        p = by_id.get(i)
        if not p:
            items.append({"id": i, "outcome": "ignored", "reason": "Not one of your imported tracks."})
            continue
        if stopped:
            items.append({"id": i, "title": p.title, "outcome": "not_attempted", "reason": stopped})
            continue
        if p.visibility == target:
            items.append({"id": i, "title": p.title, "outcome": "already",
                          "reason": f"Already {target}.", "cost": 0})
            continue
        leaving = p.visibility == "private" and target != "private"
        if leaving and has_private_track(p) and not confirm:
            items.append({"id": i, "title": p.title, "outcome": "needs_consent", "cost": 0,
                          "reason": "Private on SoundCloud: publishing shares its secret link. "
                                    "Tick the box to include it."})
            continue
        owed = pricer.owed(p) if leaving else 0
        if owed > left:
            stopped = (f"Stopped: the next track costs {owed} ⚡ and you have {left}.")
            items.append({"id": i, "title": p.title, "outcome": "insufficient", "cost": owed, "reason": stopped})
            continue
        left -= owed
        items.append({"id": i, "title": p.title, "outcome": "would_publish" if leaving else "would_change",
                      "cost": owed, "reason": ""})
    return items, have, stopped


class PreviewView(APIView):
    """POST .../library/preview/ {ids, visibility, confirm_private_secret?} — no writes."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        target = _target(d)
        if not target:
            return Response({"detail": "Choose public, restricted or private."},
                            status=status.HTTP_400_BAD_REQUEST)
        ids = _ids(d)
        by_id = _load(request.user, ids)
        confirm = bool(d.get("confirm_private_secret"))
        items, have, stopped = _plan(request.user, ids, by_id, target, confirm)
        go = [x for x in items if x["outcome"] in ("would_publish", "would_change")]
        publishing = [x for x in go if x["outcome"] == "would_publish"]
        total = sum(x["cost"] for x in go)
        needs = [{"id": x["id"], "title": x["title"]} for x in items if x["outcome"] == "needs_consent"]
        # What the batch would cost if every consenting track were included.
        all_items, _, _ = _plan(request.user, ids, by_id, target, True)
        cost_all = sum(x["cost"] for x in all_items if x["outcome"] in ("would_publish", "would_change"))
        batch = len(publishing) >= BATCH_MIN
        per_call_cut = len(go) > MAX_PER_CALL
        sentence = _sentence(target, len(go), len(publishing), total, have, needs, stopped,
                             sum(1 for x in items if x["outcome"] == "already"), batch)
        return Response({
            "visibility": target,
            "would_change": len(go), "would_publish": len(publishing),
            "cost": {"resource": "energy", "amount": total},
            "cost_if_private_tracks_included": {"resource": "energy", "amount": cost_all},
            "energy": have,
            "affordable_all": stopped is None,
            "affordable_count": len(go),
            "needs_consent": needs,
            "confirmed_private": confirm,
            "already": sum(1 for x in items if x["outcome"] == "already"),
            "ignored": sum(1 for x in items if x["outcome"] == "ignored"),
            "limits": {"per_call": MAX_PER_CALL, "daily": None,
                       "cut_short_by": "funds" if stopped else ("per_call" if per_call_cut else None)},
            "dating": {"mode": "released" if batch else "kept", "sentence": DATING_SENTENCE},
            "failed_attempts_charged": False,
            "items": items[:MAX_PER_CALL * 2],
            "detail": sentence,
        })


def _sentence(target, n_go, n_pub, total, have, needs, stopped, already, batch):
    if target == "private":
        s = f"Making {n_go} private is free." if n_go else "Nothing to change."
    elif not n_go:
        s = "Nothing to publish yet."
    else:
        s = (f"Setting {n_go} to {target} costs −{total} ⚡ (you have {have}) "
             f"— {n_pub} of them are leaving private." if total else
             f"Setting {n_go} to {target} costs nothing.")
    if needs:
        s += (f" {len(needs)} {'is' if len(needs) == 1 else 'are'} private on SoundCloud — "
              "publishing shares the secret link; tick to include them.")
    if already:
        s += f" {already} already {'is' if already == 1 else 'are'} {target}."
    if stopped:
        s += " " + stopped
    return s


class ApplyView(APIView):
    """POST .../library/apply/ — per item, one transaction each, in order."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        user = request.user
        target = _target(d)
        if not target:
            return Response({"detail": "Choose public, restricted or private."},
                            status=status.HTTP_400_BAD_REQUEST)
        ids = _ids(d)
        confirm = bool(d.get("confirm_private_secret"))
        todo, rest = ids[:MAX_PER_CALL], ids[MAX_PER_CALL:]
        by_id = _load(user, todo)
        # Decided before the loop so the whole call is either a batch or not.
        plan, _, _ = _plan(user, todo, by_id, target, confirm)
        leaving = sum(1 for x in plan if x["outcome"] == "would_publish")
        backdate = leaving >= BATCH_MIN
        results, charged, stopped = [], 0, ""
        for i in todo:
            p = by_id.get(i)
            if not p:
                results.append({"id": i, "result": "ignored", "reason": "Not one of your imported tracks."})
                continue
            if stopped:
                results.append({"id": i, "title": p.title, "result": "not_attempted", "reason": stopped})
                continue
            if p.visibility == target:
                results.append({"id": i, "title": p.title, "result": "skipped", "reason": f"Already {target}.",
                                "visibility": p.visibility})
                continue
            e = import_embed(p)
            try:
                out = change_visibility(
                    user, p, target, share_private_track=confirm, strict_funds=True,
                    backdate_to=_parse(e.get("released_at")) if backdate else None)
            except VisibilityRefused as r:
                if r.status == status.HTTP_409_CONFLICT:
                    results.append({"id": i, "title": p.title, "result": "skipped",
                                    "reason": "Private on SoundCloud: needs your confirmation to share its secret link.",
                                    "needs_consent": True, "visibility": p.visibility})
                else:
                    stopped = r.payload["detail"]
                    results.append({"id": i, "title": p.title, "result": "skipped", "reason": stopped,
                                    "visibility": p.visibility})
                continue
            charged += out["charged"]
            results.append({"id": i, "title": p.title, "result": "published" if out["was"] == "private" and target != "private" else "changed",
                            "visibility": target, "charged": out["charged"],
                            "dated_to_release": out["backdated"], "reason": ""})
        for i in rest:
            results.append({"id": i, "result": "not_attempted",
                            "reason": f"At most {MAX_PER_CALL} are done per request; send the rest again."})
        done = sum(1 for r in results if r["result"] in ("published", "changed"))
        return Response({
            "visibility": target, "results": results,
            "published": sum(1 for r in results if r["result"] == "published"),
            "changed": done,
            "skipped": sum(1 for r in results if r["result"] == "skipped"),
            "not_attempted": sum(1 for r in results if r["result"] == "not_attempted"),
            "charged": {"resource": "energy", "amount": charged},
            "stopped": stopped, "dated_to_release": backdate,
            "energy": max(0, wallet_for(user).energy or 0),
        })
