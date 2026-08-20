"""Send a post you already published to the coach, and get it scored.

The Boss Take coach listens to a take before it becomes anything. This is the
same coach, pointed at work that is already up: a member posts a track, wonders
why it isn't landing, and until now had nowhere to take that question. PostZ
showed them a median and a like count and stopped — a read-only surface, which
`CLAUDE.md` calls an unfinished one.

Three rules it inherits rather than reinvents:

**The score is not the post's rating.** `rating` on a post is the median of
what MEMBERS scored it. This is one model's opinion of the recording, kept in
`coach_rating` and rendered on its own line. Blending them would hide a
machine's number inside a count of people.

**It measures the recording.** `score_take` sends the actual audio or video, so
the number moves because the performance moved. It is not derived from how
complete the post's form is — that is the `directz_ai_rating` failure this
codebase already had to remove once.

**The price is on the button.** GET answers what this member pays before they
press anything, and a take the coach can't read is never billed.

Author-only, and on demand. A post is somebody's work: whether a machine grades
it is theirs to decide, and the prompt is theirs to spend.
"""
import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import ai_cost
from .directz_app import _find_upload, craft_price
from .instruments import DIFFICULTIES, INSTRUMENTS, profile_for_app
from .models import Post, charge_ai_usage, owns_post
from .vocalcoach import MAX_MB, score_take

logger = logging.getLogger(__name__)

# Which coach a post gets when the author doesn't name one. A post carries the
# skills that went into it, and those already name the instrument — asking a
# member to pick "SingZ" for a post tagged Vocals is asking them to say it
# twice. Falls through to the generic InstrumentZ profile, never to a guess.
_SKILL_HINTS = (
    ("singz", ("vocal", "sing", "voice", "topline", "harmon")),
    ("rapz", ("rap", "mc", "verse", "bars", "flow")),
    ("guitarz", ("guitar",)),
    ("bassz", ("bass",)),
    ("keyz", ("key", "piano", "synth", "organ")),
    ("drumz", ("drum", "percussion")),
    ("violinz", ("violin", "strings", "fiddle", "cello", "viola")),
)


def coach_for_post(post, asked=""):
    """Which instrument coach scores this post.

    `asked` wins — the author knows what they played, and a rap verse over a
    guitar loop is tagged both. Otherwise infer from the skills on the post,
    which is the same information stated once instead of twice.
    """
    asked = (asked or "").strip().lower()
    # INSTRUMENTS is the list, not a second copy of it — a profile added there
    # is askable here the same day, and no list can drift from the other.
    if asked in INSTRUMENTS:
        return asked
    haystack = " ".join(str(s) for s in (post.skills_used or [])).lower()
    for app_key, words in _SKILL_HINTS:
        if any(w in haystack for w in words):
            return app_key
    # No signal is not a reason to invent one. The generic profile scores
    # timing, tone, technique, dynamics and cleanliness — true of any
    # instrument, and never a dimension the recording can't support.
    return "instrumentz"


def post_upload(post):
    """The Upload row behind a post's media, or None.

    Looked up against the post's OWNERS — the author and anyone credited —
    rather than against whoever is asking. `_find_upload` scopes to the caller
    on purpose, because there the URL arrives from the client and an unscoped
    lookup would let anyone read another member's file by pasting its address.
    Here the URL comes off the post row and the caller has already passed
    `owns_post`, so scoping to the caller would only break the case it is
    meant to protect: a credited collaborator, sending work that is theirs, on
    a file the author happened to upload.
    """
    from django.contrib.auth import get_user_model

    owners = [post.author]
    names = [c.get("username") for c in (post.contributors or []) if c.get("username")]
    if names:
        owners += list(get_user_model().objects.filter(username__in=names))
    for owner in owners:
        found = _find_upload(owner, post.media_url)
        if found is not None:
            return found
    return None


class PostCoachView(APIView):
    """GET → what a coached read costs, before it costs it.
       POST → score the post's media and store the coach's read on it.

    Author-only in both directions. `owns_post` rather than `post.author`, so a
    collab post is every credited member's to send — the work belongs to all of
    them and so does the decision.
    """

    permission_classes = [IsAuthenticated]

    def _post_or_none(self, request, pk):
        post = Post.objects.filter(pk=pk).first()
        if post is None or not owns_post(post, request.user):
            # One answer for "no such post" and "not yours" on purpose: the
            # difference is only useful to somebody enumerating other people's
            # posts.
            return None
        return post

    def get(self, request, pk):
        post = self._post_or_none(request, pk)
        if post is None:
            return Response({"detail": "That post isn't yours to coach."},
                            status=status.HTTP_404_NOT_FOUND)
        price = craft_price(request.user)
        app_key = coach_for_post(post, request.query_params.get("app_key"))
        profile = profile_for_app(app_key)
        upload = post_upload(post)
        # Why it CAN'T run, before the member presses and pays to find out.
        blocked = ""
        if not post.media_url:
            blocked = "there's no audio or video on this post to listen to"
        elif upload is None:
            blocked = "the file behind this post couldn't be found"
        elif upload.size_bytes > MAX_MB * 1024 * 1024:
            blocked = (f"that file is {upload.size_bytes / (1024 * 1024):.0f}MB — over the "
                       f"{MAX_MB}MB the coach can hear in one go")
        elif not price["configured"]:
            blocked = "the coach isn't configured yet"
        return Response({
            "cost_cents": ai_cost("standard"),
            "free_today": price["free_today"],
            "daily_remaining": price["daily_prompts_left"],
            "daily_allowance": price["daily_prompts"],
            "affordable": price["affordable"],
            "configured": price["configured"],
            # A read the coach couldn't produce is never billed — charging
            # happens only after a usable result parses.
            "charged_on_failure": False,
            "allowed": bool(price["affordable"] and not blocked),
            "blocked_because": blocked,
            "max_mb": MAX_MB,
            # The dimensions THIS post will be scored on, so the client renders
            # the chips from the server and they can't drift from what the
            # model is actually asked for.
            "app_key": app_key,
            "label": profile["label"],
            "coach": profile["coach"],
            "scores": profile["scores"],
            "difficulties": DIFFICULTIES,
            "caveat": profile["caveat"],
            # What is already on the post, so the button can say "score it" or
            # "score it again" rather than both.
            "rated": post.coach_rating is not None,
            "coach_rating": post.coach_rating,
            "coach_note": post.coach_note,
            # Nothing is a dead end: the read is a coaching result, and the
            # place to act on it is the app that trains the thing.
            "open_in": app_key,
        })

    def post(self, request, pk):
        post = self._post_or_none(request, pk)
        if post is None:
            return Response({"detail": "That post isn't yours to coach."},
                            status=status.HTTP_404_NOT_FOUND)

        price = craft_price(request.user)
        if not price["configured"]:
            return Response({"detail": "The coach isn't configured — set GEMINI_API_KEY on the backend."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not price["affordable"]:
            # Checked BEFORE the call, so we never buy a read we can't bill for.
            return Response({"detail": "Not enough PromptZ / balance for a coached read.",
                             "cost_cents": price["cost_cents"]},
                            status=status.HTTP_402_PAYMENT_REQUIRED)

        if not post.media_url:
            return Response({"detail": "There's no audio or video on this post for the coach to hear."},
                            status=status.HTTP_400_BAD_REQUEST)
        upload = post_upload(post)
        if upload is None:
            return Response({"detail": "The file behind this post couldn't be found."},
                            status=status.HTTP_404_NOT_FOUND)
        if upload.size_bytes > MAX_MB * 1024 * 1024:
            return Response({"detail": f"That file is {upload.size_bytes / (1024 * 1024):.0f}MB — over "
                                       f"the {MAX_MB}MB the coach can hear in one go."},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        app_key = coach_for_post(post, request.data.get("app_key"))
        difficulty = str(request.data.get("difficulty") or "builder").lower()
        try:
            upload.file.open("rb")
            payload, err = score_take(
                app_key, upload.file, upload.content_type,
                # The post's own genre and skills, not a second form. The
                # member already told us what this is.
                genre=post.genre or "unspecified",
                target=request.data.get("range"),
                difficulty=difficulty if difficulty in DIFFICULTIES else "builder",
            )
        finally:
            try:
                upload.file.close()
            except Exception:                                # pragma: no cover
                pass

        if err:
            body, code = err
            # Say why on the post too, so the answer survives the member
            # closing the panel — and so an empty rating is explained rather
            # than looking like a zero.
            post.coach_note = str(body.get("detail", ""))[:200]
            post.save(update_fields=["coach_note"])
            return Response(body, status=code)

        # Billed only now. A post the coach couldn't read costs nothing, the
        # same rule the Boss Take bills on. count_daily, because this is a flat
        # model run and the tier's free daily prompts are exactly what that
        # allowance is for.
        charged = charge_ai_usage(
            request.user, price["cost_cents"],
            note=f"{profile_for_app(app_key)['label']} coach — read on a post",
            count_daily=True)
        profile = profile_for_app(app_key)
        read = {**payload, "app_key": app_key,
                "label": profile["label"],
                # The labels travel WITH the read. A post keeps its coach's
                # score for as long as it exists, and a dimension renamed in
                # instruments.py next year must not silently relabel a score
                # that was never given on that dimension.
                "scores_labels": profile["scores"],
                "caveat": profile["caveat"],
                "rated_at": timezone.now().isoformat()}
        post.coach_rating = payload["score"]
        post.coach = read
        post.coach_note = ""
        post.save(update_fields=["coach_rating", "coach", "coach_note"])
        return Response({
            **read,
            # 0 when a free daily prompt covered it — the caller cannot state
            # the price honestly if this reports the nominal cost either way.
            "cost_cents": 0 if price["free_today"] else price["cost_cents"],
            "charged": charged is not None,
            "post_id": post.id,
            "open_in": app_key,
        })
