"""A post, populated straight into a release.

The four things a post carries are the four things a distributor asks for:

    txt lyrics   → the lyric sheet
    audio song   → the master
    music video  → the video asset
    cover image  → the artwork

So none of it gets retyped. `POST /api/economy/postz/<pk>/distribute/` reads the
post's slots and fills the release from them; the only fields left are the ones
a post genuinely cannot know — the release date, the ISRC, the explicit flag.

Two rules this follows from the rest of the app:

**It says what's missing up front.** A release reports the assets it still
needs before anyone tries to send it, rather than being bounced at the far end
by a distributor's validator with a message nobody here wrote.

**It isn't a dead end.** A release points back at the post it came from, and
the post points forward at the release, so the trip is round.
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (TIER_FREE, CollabDeal, Post, Release, membership_for,
                     notify, profile_for)
from .postz import media_slots


# What a submission IS, said once and served with every list: Music ConnectZ
# does not upload to stores itself. A submission goes to the platform owner,
# who distributes it and credits the royalties back against it in RoyaltieZ.
# A screen that let "Submit" read as "it's on Spotify now" would be the
# substance rule with a release date attached.
HOW_IT_WORKS = ("Submitting sends the release to the Music ConnectZ team, who put it out to "
                "the stores and credit what it earns to your RoyaltieZ, tagged with this release.")

# Free sends one release a calendar month; Premium and StatZ, as many as they
# like. The ladder rule: a tier says how OFTEN, never whether — a Free member
# can always release.
FREE_PER_MONTH = 1


def quota_for(user):
    """{per_month, used, left} for this calendar month — per_month None = no cap."""
    tier = membership_for(user).tier
    if tier != TIER_FREE:
        return {"tier": tier, "per_month": None, "used": None, "left": None}
    now = timezone.now()
    used = Release.objects.filter(user=user, status=Release.STATUS_SUBMITTED,
                                  submitted_at__year=now.year, submitted_at__month=now.month).count()
    return {"tier": tier, "per_month": FREE_PER_MONTH, "used": used, "left": max(0, FREE_PER_MONTH - used)}


def release_dict(r):
    missing = r.missing()
    return {
        "id": r.id,
        "title": r.title,
        "artist_name": r.artist_name,
        "genre": r.genre,
        # The four assets, in the post's own slot names — the copy is a copy.
        "audio_url": r.audio_url,
        "video_url": r.video_url,
        "artwork_url": r.artwork_url,
        "lyrics": r.lyrics,
        "release_date": r.release_date.isoformat() if r.release_date else "",
        "isrc": r.isrc,
        "explicit": r.explicit,
        "status": r.status,
        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        # Said before anyone presses send, never after.
        "missing": missing,
        "ready": not missing,
        # Which fields a member may still change, answered from the model so a
        # form can grey the right boxes instead of guessing.
        "locked": (sorted(Release.LOCKED_ONCE_SUBMITTED)
                   if r.status == Release.STATUS_SUBMITTED else []),
        # Where it came from, so a release is never a dead end.
        # Posts live in PostZ and every post has its own address; the old
        # door named "social", which is SocialiZeZ, where no post is.
        "source_post": ({"id": r.source_post_id, "title": r.source_post.title,
                         "open_in": "postz", "url": f"/p/{r.source_post_id}"}
                        if r.source_post_id and r.source_post else None),
        "source_deal": ({"id": r.source_deal_id, "title": r.source_deal.title,
                         "open_in": "collabz", "target": f"deal-{r.source_deal_id}"}
                        if r.source_deal_id and r.source_deal else None),
        # None on the unsaved preview the GET returns — it hasn't been created,
        # and inventing a timestamp for it would be a small lie.
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def populate_from_post(release, post):
    """Copy the post's four slots onto the release.

    Only fills what's EMPTY. Someone who fixed a title on the release doesn't
    want it overwritten the next time they open the post — the post is where
    the assets come from, not an authority over edits made since.
    """
    slots = media_slots(post)
    for field, value in (
        ("title", post.title),
        ("genre", post.genre),
        ("audio_url", slots["audio"]),
        ("video_url", slots["video"]),
        ("artwork_url", slots["image"]),
        ("lyrics", slots["text"]),
    ):
        if value and not getattr(release, field):
            setattr(release, field, value)
    if not release.artist_name:
        p = profile_for(post.author)
        release.artist_name = (p.display_name or post.author.username)[:120]
    return release


class PostDistributeView(APIView):
    """GET the release for a post; POST creates it, populated from the post.

    GET answers before anything is created, so a Distribute button can say what
    the release will still need rather than finding out afterwards.
    """

    permission_classes = [IsAuthenticated]

    def _post(self, request, pk):
        return Post.objects.select_related("author").filter(pk=pk, author=request.user).first()

    def get(self, request, pk):
        post = self._post(request, pk)
        if not post:
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        existing = Release.objects.filter(source_post=post).first()
        if existing:
            return Response({"release": release_dict(existing), "exists": True})
        # A preview: what it WOULD be, without writing anything yet.
        preview = populate_from_post(Release(user=request.user, source_post=post), post)
        return Response({"release": release_dict(preview), "exists": False})

    def post(self, request, pk):
        post = self._post(request, pk)
        if not post:
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        r = Release.objects.filter(source_post=post).first()
        created = r is None
        if created:
            r = Release(user=request.user, source_post=post)
        # Re-populating an existing release only fills gaps — see the helper.
        populate_from_post(r, post)
        r.refresh_status()
        r.save()
        return Response(release_dict(r),
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ReleasesView(APIView):
    """GET every release of mine."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = (Release.objects.filter(user=request.user)
                .select_related("source_post", "source_deal")[:200])
        out = [release_dict(r) for r in rows]
        return Response({
            "releases": out,
            "ready": sum(1 for r in out if r["ready"] and r["status"] != Release.STATUS_SUBMITTED),
            # Stated once, from the model, so the client can't invent its own list.
            "required": [label for _, label in Release.REQUIRED],
            # Before the button, never after: how many you can still send this
            # month, and what sending actually does.
            "quota": quota_for(request.user),
            "how_it_works": HOW_IT_WORKS,
            "is_owner": bool(request.user.is_staff or request.user.is_superuser),
        })


class ReleaseDetailView(APIView):
    """PATCH the fields a post can't know; DELETE drops the draft."""

    permission_classes = [IsAuthenticated]

    def _get(self, request, pk):
        return (Release.objects.filter(pk=pk, user=request.user)
                .select_related("source_post", "source_deal").first())

    def patch(self, request, pk):
        r = self._get(request, pk)
        if not r:
            return Response({"detail": "release not found"}, status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        # A sent release stays editable — stores take an updated cover, a new
        # video and corrected lyrics long after release, so refusing every edit
        # would be stricter than the shops we send to. Only the two fields that
        # identify the recording are locked, and the refusal names them.
        if r.status == Release.STATUS_SUBMITTED:
            blocked = [label for f, label in Release.LOCKED_ONCE_SUBMITTED.items()
                       if f in d and str(d[f] or "") != getattr(r, f)]
            if blocked:
                return Response(
                    {"detail": f"That release is already out, so {' and '.join(blocked)} "
                               "can't change — swapping it would make it a different record "
                               "under the same name. Everything else is still editable.",
                     "locked": sorted(Release.LOCKED_ONCE_SUBMITTED),
                     "editable_after_release": True},
                    status=status.HTTP_409_CONFLICT,
                )
        for f, cap in (("title", 160), ("artist_name", 120), ("genre", 40),
                       ("audio_url", 500), ("video_url", 500), ("artwork_url", 500),
                       ("isrc", 15)):
            if f in d:
                setattr(r, f, str(d[f] or "")[:cap])
        if "lyrics" in d:
            r.lyrics = str(d["lyrics"] or "")
        if "explicit" in d:
            r.explicit = bool(d["explicit"])
        if "release_date" in d:
            raw = str(d["release_date"] or "").strip()
            if not raw:
                r.release_date = None
            else:
                from datetime import date
                try:
                    r.release_date = date.fromisoformat(raw)
                except ValueError:
                    return Response({"detail": "Use YYYY-MM-DD for the release date."},
                                    status=status.HTTP_400_BAD_REQUEST)
        r.refresh_status()
        r.save()
        return Response(release_dict(r))

    def delete(self, request, pk):
        r = self._get(request, pk)
        if not r:
            return Response({"detail": "release not found"}, status=status.HTTP_404_NOT_FOUND)
        if r.status == Release.STATUS_SUBMITTED:
            return Response({"detail": "That release has already gone out."},
                            status=status.HTTP_409_CONFLICT)
        # The post is untouched. Dropping a release is dropping the paperwork,
        # not the work.
        r.delete()
        return Response({"deleted": True, "note": "The post is still up."})


class ReleaseSubmitView(APIView):
    """POST .../submit/ — mark it sent.

    It refuses an incomplete release BY NAME. Being told "cover art" here beats
    a distributor rejecting it tomorrow with a code.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        r = (Release.objects.filter(pk=pk, user=request.user)
             .select_related("source_post", "source_deal").first())
        if not r:
            return Response({"detail": "release not found"}, status=status.HTTP_404_NOT_FOUND)
        if r.status == Release.STATUS_SUBMITTED:
            return Response({"detail": "That one has already gone out.", **release_dict(r)},
                            status=status.HTTP_409_CONFLICT)
        missing = r.missing()
        if missing:
            return Response(
                {"detail": f"Not ready yet — it still needs {', '.join(missing)}.",
                 "missing": missing},
                status=status.HTTP_400_BAD_REQUEST,
            )
        q = quota_for(request.user)
        if q["per_month"] is not None and q["left"] <= 0:
            return Response(
                {"detail": f"Free sends {q['per_month']} release a month and this month's is used. "
                           "It stays ready here — send it next month, or Premium sends as many as you like.",
                 "quota": q, "upgrade": {"tab": "membershipz", "target": "membershipz-plans"}},
                status=status.HTTP_403_FORBIDDEN,
            )
        r.status = Release.STATUS_SUBMITTED
        r.submitted_at = timezone.now()
        r.save(update_fields=["status", "submitted_at", "updated_at"])
        # The owner distributes it, so the owner is told — a queue nobody is
        # told about is a release that sits.
        from .views import platform_owner
        owner = platform_owner()
        if owner and owner.id != request.user.id:
            notify(owner, "system", f"@{request.user.username} sent a release: “{r.title}”",
                   actor=request.user, item_id=f"release:{r.id}")
        return Response({**release_dict(r), "quota": quota_for(request.user)})


class ReleaseQueueView(APIView):
    """GET /api/economy/distributez/queue/ — OWNER: every submitted release,
    oldest first, with whose it is. Crediting what one earned goes through
    RoyaltyAccrueView with its release_id, which already applies any
    IntelligenceZ cut."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (request.user.is_staff or request.user.is_superuser):
            return Response({"detail": "Only the platform owner sees the release queue."},
                            status=status.HTTP_403_FORBIDDEN)
        rows = (Release.objects.filter(status=Release.STATUS_SUBMITTED)
                .select_related("user", "source_post", "source_deal").order_by("submitted_at")[:300])
        return Response({"releases": [{**release_dict(r), "username": r.user.username} for r in rows]})


def populate_from_deal(release, deal):
    """Fill a release from a collab. Same rule as a post: gaps only.

    A deal is where the finished master usually lands, which is why this is the
    route that matters most. The credit line is every participant, because a
    collab released under one name is the argument the escrow existed to avoid.
    """
    for field, value in (
        ("title", deal.title),
        ("audio_url", deal.media_url if deal.media_type == "audio" else ""),
        ("video_url", deal.media_url if deal.media_type == "video" else ""),
        ("artwork_url", deal.image_url),
        ("lyrics", deal.lyrics),
    ):
        if value and not getattr(release, field):
            setattr(release, field, value)
    if not release.artist_name:
        names = [p.get("username") for p in (deal.participants or []) if p.get("username")]
        release.artist_name = ", ".join(names)[:120]
    return release


class CollabDistributeView(APIView):
    """GET / POST /api/economy/collab/<pk>/distribute/ — a deal becomes a release.

    Open to any participant, not just the initiator: everyone on the deal made
    the record, so anyone on it can start the paperwork.
    """

    permission_classes = [IsAuthenticated]

    def _deal(self, request, pk):
        deal = CollabDeal.objects.filter(pk=pk).first()
        if not deal:
            return None
        mine = (deal.initiator_id == request.user.id
                or any(p.get("username") == request.user.username
                       for p in (deal.participants or [])))
        return deal if mine else None

    def get(self, request, pk):
        deal = self._deal(request, pk)
        if not deal:
            return Response({"detail": "deal not found"}, status=status.HTTP_404_NOT_FOUND)
        existing = Release.objects.filter(source_deal=deal).first()
        if existing:
            return Response({"release": release_dict(existing), "exists": True})
        preview = populate_from_deal(Release(user=request.user, source_deal=deal), deal)
        return Response({"release": release_dict(preview), "exists": False})

    def post(self, request, pk):
        deal = self._deal(request, pk)
        if not deal:
            return Response({"detail": "deal not found"}, status=status.HTTP_404_NOT_FOUND)
        r = Release.objects.filter(source_deal=deal).first()
        created = r is None
        if created:
            r = Release(user=request.user, source_deal=deal)
        populate_from_deal(r, deal)
        r.refresh_status()
        r.save()
        return Response(release_dict(r),
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
