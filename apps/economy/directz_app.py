"""DirectZ — collaborative video works (ReelZ / EpisodeZ / MovieZ).

Each work names its contributors and the skills they bring (their worth), so the
CollabZ "everyone paid their worth" settlement applies. On submit the work gets
an AI craft rating; once 3+ real members rate it, their median takes over.
"""
import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .directz_craft import CRAFT_SCORES
from .models import (
    DirectZWork,
    DirectZRating,
    DIRECTZ_BANDS,
    directz_band_for,
    directz_display_rating,
    membership_for,
)

logger = logging.getLogger(__name__)

VALID_FMT = {"reelz", "episodez", "moviez"}

# What a DirectZ video can BE, served rather than typed into the client.
#
# `genre` and `video_type` have been on the model since it was written and have
# never been filled by anything, because no screen ever asked. Both are prompted
# now, and both lists live here so the composer and the validator cannot come
# apart — the music genres still live in the frontend's own genres.js, which is
# exactly the split this codebase has spent the week closing everywhere else.
#
# Two axes, deliberately not merged: video_type is what the video is FOR, genre
# is what it is LIKE. A promotional video can be a live performance; a music
# video can be a short film.
DIRECTZ_GENRES = [
    "Music Video", "Live Performance", "Behind the Scenes", "Lyric Video",
    "Documentary", "Short Film", "Dance", "Comedy", "Drama", "Interview",
    "Tutorial", "Trailer / Promo", "Experimental",
]
DIRECTZ_VIDEO_TYPES = ["Music", "Bio", "Promotional", "Educational", "Personal"]

# Human labels for the format bands. The seconds come from DIRECTZ_BANDS so the
# label and the rule it describes can never disagree.
FMT_LABEL = {"reelz": "ReelZ", "episodez": "EpisodeZ", "moviez": "MovieZ"}


def _clean_choice(value, allowed):
    """Match a supplied value against a served list, case-insensitively.

    Drops anything unrecognised rather than refusing it — the same rule
    `gamez.clean_genre` follows. A video with no genre is fine; a 400 because
    somebody typed a genre we don't happen to list is not.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = {choice.lower(): choice for choice in allowed}
    return lowered.get(text.lower(), "")


def _mmss(seconds):
    """A band bound in words, for a picker option."""
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds >= 3600:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}"
    if seconds >= 60:
        return f"{seconds // 60}min"
    return f"{seconds}s"


def directz_formats():
    """The three formats with their length bands, ready for a picker.

    The band is part of the OPTION, so a member reads the constraint while
    choosing rather than discovering it after they've uploaded — the same rule
    the app applies to prices.
    """
    return [
        {"key": key, "name": FMT_LABEL.get(key, key),
         "min_sec": lo, "max_sec": hi,
         "length": f"{_mmss(lo)}–{_mmss(hi)}"}
        for key, (lo, hi) in DIRECTZ_BANDS.items()
    ]


def _find_upload(user, media_url):
    """The member's own Upload row behind a media URL, or None.

    Scoped to `user` deliberately. The URL arrives from the client, and a lookup
    that searched every Upload would let somebody rate — and read — a file
    belonging to another member by pasting its address.
    """
    from .models import Upload

    url = str(media_url or "").strip()
    if not url:
        return None
    # Match on the stored path's tail rather than the full URL: MEDIA_URL
    # differs between local, Render and any CDN in front of it, so comparing
    # whole URLs would work in exactly one environment.
    tail = url.split("?")[0].rsplit("/", 1)[-1]
    if not tail:
        return None
    return Upload.objects.filter(user=user, file__endswith=tail).order_by("-id").first()


def craft_price(user):
    """What a craft rating costs this member, and whether they can have one.

    Priced like a Boss Take, because it is the same thing: a member's own media
    sent to a model that judges it. `ai_cost("standard")` is the coach's rate,
    reused rather than a second number.
    """
    from .catalog import ai_cost
    from .directz_craft import _key
    from .models import can_afford_ai, daily_prompt_state
    from .vocalcoach import MAX_MB

    cost = ai_cost("standard")
    allowance, _, daily_left = daily_prompt_state(user)
    return {
        "cost_cents": cost,
        "daily_prompts": allowance,
        "daily_prompts_left": daily_left,
        # A free daily prompt covers it before any balance is touched, so
        # affordability has to know about the allowance — the coach's own gate
        # was refusing members who had prompts left and an empty wallet.
        "free_today": bool(cost) and daily_left > 0,
        "affordable": bool(not cost or daily_left > 0 or can_afford_ai(user, cost)),
        "configured": bool(_key()),
        # The rater's ceiling, PUBLISHED — so the tickbox can say it before it
        # is ticked. Without this the screen could not state the limit even if
        # it wanted to: a 100MB video was posted with the box ticked and the
        # refusal arrived afterwards, as a note on the finished work. The same
        # failure the Boss Take coach had, in the app next door.
        #
        # Note this is NOT the member's tier upload limit. The post keeps the
        # whole video; only the rater is bounded, because it watches the file
        # inside one request.
        "max_mb": MAX_MB,
        "max_mb_why": (
            f"The rater watches the whole video in one request, which caps out "
            f"around {MAX_MB}MB. It isn't your tier's upload limit — the post keeps "
            "the full video either way; only the rating needs a shorter cut."
        ),
        "max_mb_is_tier_limit": False,
        # A video the rater can't watch is never billed — see _apply_craft_rating,
        # which returns before charge_ai_usage. Worth saying, not just doing.
        "charged_on_failure": False,
    }


def _apply_craft_rating(work, user):
    """Watch the work's video and store the score, or store why we couldn't.

    Never raises: a rating that fails is a work with no rating, not a failed
    post. The member's video is already saved by the time this runs, and losing
    it because a third-party API was slow would be the worse outcome by far.

    Charged on the coach's terms — only once a usable result exists, and the
    day's free prompts first. When it shipped this cost nothing and said
    nothing, which is unbounded Gemini spend on the platform's key and the
    cost/gain rule broken by the code that enforces it everywhere else.
    """
    from .directz_craft import rate_video, too_big
    from .models import charge_ai_usage

    price = craft_price(user)
    if not price["affordable"]:
        # Checked BEFORE the call, so we never buy a rating we can't bill for.
        # The work still posts — a rating is a bonus, not the post.
        work.ai_rating = None
        work.craft = {}
        work.rating_note = (f"a craft rating costs {price['cost_cents']} 🏷️ and "
                            "today's free prompts are spent")
        work.save(update_fields=["ai_rating", "craft", "rating_note"])
        return

    upload = _find_upload(user, work.media_url)
    if upload is None:
        note = "no video attached" if not work.media_url else "the video couldn't be found"
    elif too_big(upload.size_bytes):
        # Said plainly rather than worked around. A MovieZ is one to three hours
        # and will not fit the inline path — and rating a three-hour film from
        # its metadata is the exact thing this replaced.
        from .vocalcoach import MAX_MB
        note = (f"that video is {upload.size_bytes / (1024 * 1024):.0f}MB — over the "
                f"{MAX_MB}MB the rater can watch in one go")
    else:
        try:
            upload.file.open("rb")
            payload, why = rate_video(
                upload.file, upload.content_type,
                fmt=work.fmt, genre=work.genre,
                length=f"{work.duration_sec}s" if work.duration_sec else "")
        except Exception:                                    # pragma: no cover
            logger.exception("DirectZ craft: rating %s failed", work.pk)
            payload, why = None, "the rater couldn't read that file"
        finally:
            try:
                upload.file.close()
            except Exception:                                # pragma: no cover
                pass
        if payload:
            # Billed only now — a video the rater couldn't read is never
            # charged, the same rule vocalcoach.py bills on. count_daily,
            # because this is a flat model run and the tier's free prompts are
            # exactly what that allowance is for.
            charged = charge_ai_usage(
                user, price["cost_cents"],
                note=f"DirectZ craft rating — {work.fmt}", count_daily=True)
            work.ai_rating = payload["score"]
            work.craft = {**payload, "cost_cents": 0 if charged is None else price["cost_cents"]}
            work.rating_note = ""
            work.save(update_fields=["ai_rating", "craft", "rating_note"])
            return
        note = why

    work.ai_rating = None
    work.craft = {}
    work.rating_note = str(note)[:200]
    work.save(update_fields=["ai_rating", "craft", "rating_note"])


def _work_dict(w, request):
    disp = directz_display_rating(w)
    my = DirectZRating.objects.filter(rater=request.user, work=w).values_list("score", flat=True).first()
    return {
        "id": w.id,
        "owner": w.owner.username,
        "mine": w.owner_id == request.user.id,
        "fmt": w.fmt,
        "video_type": w.video_type,
        "genre": w.genre,
        "mood": w.mood,
        "title": w.title,
        "description": w.description,
        "duration_sec": w.duration_sec,
        "media_url": w.media_url,
        "media_type": w.media_type,
        "contributors": w.contributors,
        "created_at": w.created_at.isoformat(),
        "my_rating": my,
        # What the score is actually made of — framing, editing, lighting, sound,
        # story — so a member can see it was earned rather than assigned.
        "craft": w.craft or {},
        "craft_scores": CRAFT_SCORES,
        # Why there is no rating, when there isn't. The screen shows this
        # instead of a number rather than beside one.
        "rating_note": w.rating_note,
        **disp,  # rating, source (ai|users|None), ai_rating, user_median, count
    }


class DirectZWorksView(APIView):
    """GET the works feed; POST creates a work (AI-rated on submit)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        fmt = request.query_params.get("fmt")
        qs = DirectZWork.objects.select_related("owner").all()[:100]
        works = [_work_dict(w, request) for w in qs if not fmt or w.fmt == fmt]
        return Response({
            "works": works,
            # The composer's vocabulary, served. A client that hardcoded these
            # would drift from the validator below the first time either moved.
            "formats": directz_formats(),
            "genres": DIRECTZ_GENRES,
            "video_types": DIRECTZ_VIDEO_TYPES,
            # The price of a craft rating, before the box that asks for one.
            # It shipped costing nothing and saying nothing, which is the
            # cost/gain rule broken by the app that enforces it.
            "craft": {
                **craft_price(request.user),
                "scores": CRAFT_SCORES,
                "note": ("A craft rating sends your video to a model that watches "
                         "it and scores framing, editing, lighting, sound and "
                         "storytelling. A video it can't read isn't charged."),
            },
        })

    def post(self, request):
        d = request.data
        fmt = str(d.get("fmt", "reelz")).lower()
        if fmt not in VALID_FMT:
            return Response({"detail": f"fmt must be one of {sorted(VALID_FMT)}"}, status=status.HTTP_400_BAD_REQUEST)
        title = str(d.get("title", "")).strip()[:160]
        if not title:
            return Response({"detail": "title required"}, status=status.HTTP_400_BAD_REQUEST)
        duration_sec = int(d.get("duration_sec") or 0)
        # Time-gate: a given category only accepts videos within its length band.
        if duration_sec > 0:
            lo, hi = DIRECTZ_BANDS.get(fmt, (0, 10 ** 9))
            if not (lo <= duration_sec <= hi):
                fits = directz_band_for(duration_sec)
                return Response(
                    {"detail": f"That length doesn't fit {fmt}. "
                               + (f"It fits {fits}." if fits else "It's outside all DirectZ length bands (30s–3h)."),
                     "code": "duration_out_of_band", "fmt": fmt, "fits": fits, "duration_sec": duration_sec},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        contributors = d.get("contributors") or []
        payload = {
            "fmt": fmt,
            # Matched against the served lists rather than stored as typed, so
            # the feed can group by them. Unrecognised drops to "" instead of
            # 400 — see _clean_choice.
            "video_type": _clean_choice(d.get("video_type"), DIRECTZ_VIDEO_TYPES),
            "genre": _clean_choice(d.get("genre"), DIRECTZ_GENRES),
            "mood": str(d.get("mood", ""))[:32],
            "title": title,
            "description": str(d.get("description", ""))[:4000],
            "duration_sec": duration_sec,
            "media_url": str(d.get("media_url", "")).strip()[:500],
            "media_type": str(d.get("media_type", "")).strip()[:60],
            "contributors": contributors,
        }
        w = DirectZWork.objects.create(owner=request.user, **payload)
        # Opt-in, and off by default. The rating comes from watching the video
        # — which costs real money on the platform's key — so posting must not
        # quietly become a paid action. A member who wants one asks for one,
        # having been shown the price by the GET above.
        if d.get("craft_rating"):
            _apply_craft_rating(w, request.user)
        else:
            w.rating_note = "no craft rating asked for"
            w.save(update_fields=["rating_note"])
        return Response(_work_dict(w, request), status=status.HTTP_201_CREATED)


class DirectZRateView(APIView):
    """Rate a work 1-10. Real ratings take over the AI seed once 3+ land."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            score = int(request.data.get("score"))
        except (TypeError, ValueError):
            return Response({"detail": "score (1-10) required"}, status=status.HTTP_400_BAD_REQUEST)
        if not (1 <= score <= 10):
            return Response({"detail": "score must be 1-10"}, status=status.HTTP_400_BAD_REQUEST)
        w = DirectZWork.objects.filter(pk=pk).select_related("owner").first()
        if not w:
            return Response({"detail": "work not found"}, status=status.HTTP_404_NOT_FOUND)
        if w.owner_id == request.user.id:
            return Response({"detail": "can't rate your own work"}, status=status.HTTP_400_BAD_REQUEST)
        _, created = DirectZRating.objects.update_or_create(rater=request.user, work=w, defaults={"score": score})
        if created:
            from .models import reward_for_rating
            reward_for_rating(request.user, "DirectZ")
        return Response(_work_dict(w, request))
