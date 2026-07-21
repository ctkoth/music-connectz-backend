"""DirectZ — collaborative video works (ReelZ / EpisodeZ / MovieZ).

Each work names its contributors and the skills they bring (their worth), so the
CollabZ "everyone paid their worth" settlement applies. On submit the work gets
an AI craft rating; once 3+ real members rate it, their median takes over.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    DirectZWork,
    DirectZRating,
    DIRECTZ_BANDS,
    directz_ai_rating,
    directz_band_for,
    directz_display_rating,
    membership_for,
)

VALID_FMT = {"reelz", "episodez", "moviez"}


def _work_dict(w, request):
    disp = directz_display_rating(w)
    my = DirectZRating.objects.filter(rater=request.user, work=w).values_list("score", flat=True).first()
    return {
        "id": w.id,
        "owner": w.owner.username,
        "mine": w.owner_id == request.user.id,
        "fmt": w.fmt,
        "video_type": w.video_type,
        "mood": w.mood,
        "title": w.title,
        "description": w.description,
        "duration_sec": w.duration_sec,
        "media_url": w.media_url,
        "media_type": w.media_type,
        "contributors": w.contributors,
        "created_at": w.created_at.isoformat(),
        "my_rating": my,
        **disp,  # rating, source (ai|users), ai_rating, user_median, count
    }


class DirectZWorksView(APIView):
    """GET the works feed; POST creates a work (AI-rated on submit)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        fmt = request.query_params.get("fmt")
        qs = DirectZWork.objects.select_related("owner").all()[:100]
        works = [_work_dict(w, request) for w in qs if not fmt or w.fmt == fmt]
        return Response({"works": works})

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
            "video_type": str(d.get("video_type", ""))[:40],
            "mood": str(d.get("mood", ""))[:32],
            "title": title,
            "description": str(d.get("description", ""))[:4000],
            "duration_sec": duration_sec,
            "media_url": str(d.get("media_url", "")).strip()[:500],
            "media_type": str(d.get("media_type", "")).strip()[:60],
            "contributors": contributors,
        }
        w = DirectZWork.objects.create(owner=request.user, ai_rating=directz_ai_rating(payload), **payload)
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
        DirectZRating.objects.update_or_create(rater=request.user, work=w, defaults={"score": score})
        return Response(_work_dict(w, request))
