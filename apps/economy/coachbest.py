"""CoachZ best score, opened: the work that scored highest and the coach's read of it.

Every profile lists the best overall each coach has given the member (`skillzhub.best_scores`).
A number on a profile that leads nowhere is the dead end the cross-pollination rule forbids, so a
row opens this: the take behind the number, the work it was scored on when the viewer may open it,
and the coach's whole read — every dimension with its label, the verdict, what is working, what to
fix, HookZ / FeelZ and the caveat that says what one take can show.

Four rules hold it:

* **Who may see it is the member's own `coach_best` setting**, the one that already decides whether
  the number is on their card. The read is the reason behind that number, so it travels with it; a
  viewer the number is hidden from gets the same 404 as a member with no take, so this cannot be
  used to learn that a hidden score exists.
* **Everything is built from what the server stored** (`takescorez.share_payload` through
  `coachshare.read_view`, the same whitelist a post's read card uses), never from a request.
  The transcribed lyrics were never kept and the paid gear advice (`upgrades`) is not served.
* **"The work" is only ever something the viewer could already open.** A post goes through
  `can_view_post`; a YouTube link is a public address the member submitted as their take. A take
  recorded in the coach, a FileZ file or a journal entry is the member's own and is NOT handed to
  anybody else — the response says the read is all there is, rather than inventing a door. The
  owner looking at their own best also gets their kept recording.
* **Highest means the number the member was SHOWN**: the overall, then the exact score inside it,
  then — among equals — a take with work somebody can open, then the newest.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .instruments import INSTRUMENTS, WIT_KEYS
from .models import Post, TakeScore, can_view_post, profile_for

User = get_user_model()

# How many of the tied-best takes are looked at to pick one. A member with more than this many
# takes on exactly their best number gets the newest of them considered, which is the right end.
TIE_SCAN = 50

NO_WORK = ("This take was recorded in the coach and not posted, so there is no track to open — "
           "the coach's read is all of it.")
NOT_FOUND = "Nothing to show."


def _emoji(app_key):
    from .skillzhub import COACHES
    return next((e for k, e, _i in COACHES if k == app_key), "")


def _post_id(take):
    if take.source == "post" and str(take.ref).startswith("post:"):
        try:
            return int(str(take.ref).split(":", 1)[1])
        except ValueError:
            return None
    return None


def _posts_for(user, takes, viewer):
    """{take_id: Post} for every take whose work this viewer may open — the post it was coached
    from, or a post the member made carrying this take's read. Two queries for any number of takes."""
    by_id = {t.pk: _post_id(t) for t in takes}
    tokens = {t.share_token: t.pk for t in takes if t.share_token}
    posts = {p.pk: p for p in Post.objects.filter(pk__in=[i for i in by_id.values() if i])
             .select_related("author")}
    carried = {}
    if tokens:
        for p in Post.objects.filter(author=user, score__share_token__in=list(tokens)).select_related("author"):
            tok = (p.score or {}).get("share_token")
            if tok in tokens:
                carried.setdefault(tokens[tok], p)
    out = {}
    for t in takes:
        for p in (posts.get(by_id[t.pk]), carried.get(t.pk)):
            if p is not None and can_view_post(p, viewer):
                out[t.pk] = p
                break
    return out


def _exact(take):
    v = (take.read or {}).get("exact")
    return v if isinstance(v, (int, float)) else take.overall


def best_take(user, app_key, viewer):
    """(take, post_or_None) for this member's highest-scored take on this coach, or (None, None)."""
    rows = list(TakeScore.objects.filter(user=user, app_key=app_key, overall__isnull=False)
                .order_by("-overall", "-created_at")[:TIE_SCAN])
    if not rows:
        return None, None
    top = [t for t in rows if t.overall == rows[0].overall]
    posts = _posts_for(user, top, viewer)

    def rank(t):
        has = t.pk in posts or (t.source == "link" and bool(t.ref))
        return (_exact(t), has, t.created_at)
    take = max(top, key=rank)
    return take, posts.get(take.pk)


def work_of(take, post, viewer, request):
    """What the score was given to, as something the viewer can open — or None."""
    if post is not None:
        return {"kind": "post", "id": post.pk, "title": post.title,
                "media_url": post.media_url or "", "media_type": post.media_type or "",
                "url": f"/p/{post.pk}", "tab": "postz", "target": f"post-{post.pk}"}
    if take.source == "link" and str(take.ref).startswith("https://"):
        return {"kind": "link", "url": take.ref, "title": "The video it scored"}
    if viewer.pk == take.user_id:
        from .logz_outcomes import file_of
        f = file_of(take, request)
        if f.get("kept") and f.get("url"):
            return {"kind": "file", "url": f["url"], "title": f.get("name") or "Your kept take",
                    "media_type": "video" if str(f.get("content_type", "")).startswith("video") else "audio"}
    return None


def read_for(take):
    """The coach's read in the shape a post's read card renders (`coachshare.read_view`)."""
    from .coachshare import read_view
    from .takescorez import share_payload
    stored = {**share_payload(take), "app_key": take.app_key,
              "coached_by": take.user.username, "coached_at": take.created_at.isoformat(),
              # Label every dimension the take was actually scored on, lyric / mix / wit included,
              # so none is dropped for want of a flag a history row never carried.
              "rated_lyrics": True, "rated_mix": True,
              "rated_extras": [k for k in (take.scores or {}) if k in WIT_KEYS]}
    return read_view(stored)


def best_view(user, app_key, viewer, request):
    """The payload, or None when there is nothing this viewer may see."""
    from .visibility import can_see
    if app_key not in INSTRUMENTS or not can_see(profile_for(user), "coach_best", viewer):
        return None
    take, post = best_take(user, app_key, viewer)
    if take is None:
        return None
    work = work_of(take, post, viewer, request)
    out = {
        "app": app_key, "label": INSTRUMENTS[app_key]["label"], "emoji": _emoji(app_key),
        "username": user.username, "mine": viewer.pk == user.pk,
        "take": {"id": take.pk, "created_at": take.created_at.isoformat(), "genre": take.genre,
                 "style": take.style, "difficulty": take.difficulty},
        "coach": {"state": "shown", "read": read_for(take)},
        "work": work,
        "work_note": "" if work else NO_WORK,
        # Already public when the member chose to share it; never minted from here.
        "share_url": f"/s/{take.share_token}" if take.share_token else "",
    }
    return out


class CoachBestView(APIView):
    """GET /api/economy/coachbest/<username>/<app_key>/ — the take behind a profile's
    CoachZ best score, the work it was scored on, and the coach's read. Free; reads only."""

    permission_classes = [IsAuthenticated]

    def get(self, request, username, app_key):
        user = User.objects.filter(username__iexact=username).first()
        out = best_view(user, str(app_key).lower(), request.user, request) if user else None
        if out is None:
            return Response({"detail": NOT_FOUND}, status=status.HTTP_404_NOT_FOUND)
        return Response(out)
