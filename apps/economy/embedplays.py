"""Plays on Music ConnectZ from an embedded SoundCloud player.

The post card frames SoundCloud's own player. SoundCloud's play count is theirs
and is never shown or mixed with this one: the number here says exactly what it
counts, "N plays on Music ConnectZ".

WHAT COUNTS (the substance rule: a play count must be a fact)
-------------------------------------------------------------
A play is a member who actually LISTENED: EMBED_PLAY_MIN_SECONDS (30) of
playback, reported by the client in heartbeats while the player is playing and
the tab is visible, at most once per member per post per day. The client only
reports; this module decides, and it does not take the client's word for time:
each heartbeat is clamped to its step cap AND to the wall clock since the
previous one (the method `record_listen` uses), so thirty seconds costs thirty
real seconds even when scripted.

NOT COUNTED
-----------
* the author's own listening (and co-owners'),
* a second account in a browser that already counted today (`anon_id`),
* more than EMBED_PLAY_PER_IP_POST counted plays on one post from one address in
  a day (a ceiling sized for a shared carrier address, not a one-per-address rule),
* anything past EMBED_PLAY_PER_USER_DAY counted plays by one member in a day,
* a post the viewer may not see, or an embed index that is not a SoundCloud
  player.

Nothing is paid for a play: no 🍥, no ⚡, no rating or skill moves.

`mcz_plays` on a post is a count of `EmbedPlay.counted` rows, batched for the
feed in ONE query and skipped altogether when no post in the batch has a
SoundCloud embed. `manage.py rebuild` is not needed: the count is derived from
the rows, not a stored counter, so it cannot drift.
"""
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .clientip import client_ip
from .models import EmbedPlay, Post, can_view_post, owns_post

EMBED_PLAY_MIN_SECONDS = 30
# Matches the client's flush interval; the first beat has no previous beat to
# be measured against, so this cap is what bounds it.
EMBED_PLAY_MAX_STEP_SEC = 10
EMBED_PLAY_PER_IP_POST = 5
EMBED_PLAY_PER_USER_DAY = 100


def has_soundcloud(post):
    return any(isinstance(e, dict) and e.get("type") == "soundcloud" for e in (post.embeds or []))


def plays_for(posts):
    """{post_id: counted plays} for posts that frame SoundCloud, one query for
    the lot, and none when none of them do."""
    ids = [p.id for p in posts if has_soundcloud(p)]
    if not ids:
        return {}
    return dict(EmbedPlay.objects.filter(post_id__in=ids, counted=True)
                .values_list("post_id").annotate(n=Count("id")))


def play_count(post):
    if not has_soundcloud(post):
        return 0
    return plays_for([post]).get(post.id, 0)


def _reply(row, post, **extra):
    return Response({"counted": bool(row and row.counted),
                     "seconds": row.seconds if row else 0,
                     "needed": EMBED_PLAY_MIN_SECONDS,
                     "plays": play_count(post), **extra})


class EmbedPlayView(APIView):
    """POST /api/economy/postz/<pk>/embed-play/ {index, seconds, anon_id}

    A heartbeat: "this player was playing for N more seconds". Answers with what
    the SERVER credited and whether this listener now counts."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        d = request.data or {}
        post = Post.objects.filter(pk=pk).first()
        if not post or not can_view_post(post, request.user):
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            idx = int(d.get("index"))
            embed = (post.embeds or [])[idx] if idx >= 0 else None
        except (TypeError, ValueError, IndexError):
            embed = None
        if not (isinstance(embed, dict) and embed.get("type") == "soundcloud"):
            return Response({"detail": "that is not a SoundCloud player on this post"},
                            status=status.HTTP_400_BAD_REQUEST)
        if owns_post(post, request.user):
            return _reply(None, post, reason="own")

        try:
            claimed = max(0, int(d.get("seconds") or 0))
        except (TypeError, ValueError):
            claimed = 0
        anon = str(d.get("anon_id") or "")[:40]
        ip = client_ip(request) or None
        now = timezone.now()
        today = timezone.localdate()

        with transaction.atomic():
            row, made = EmbedPlay.objects.select_for_update().get_or_create(
                post=post, user=request.user, day=today,
                defaults={"anon_id": anon, "ip": ip})
            if row.counted:
                return _reply(row, post)
            allowed = min(claimed, EMBED_PLAY_MAX_STEP_SEC)
            if not made:
                allowed = min(allowed, int(( now - row.updated_at).total_seconds()) + 1)
            row.seconds = min(row.seconds + allowed, 60 * 60)
            if row.seconds >= EMBED_PLAY_MIN_SECONDS:
                reason = self._refusal(row, post, request.user, anon, ip, today)
                if reason:
                    # Keep the seconds but never count; say why so the client
                    # stops reporting.
                    row.save(update_fields=["seconds", "updated_at"])
                    return _reply(row, post, reason=reason)
                row.counted = True
            row.save(update_fields=["seconds", "counted", "updated_at"])
        return _reply(row, post)

    @staticmethod
    def _refusal(row, post, user, anon, ip, today):
        counted = EmbedPlay.objects.filter(counted=True)
        if anon and counted.filter(post=post, day=today, anon_id=anon).exclude(user=user).exists():
            return "browser"
        if ip and counted.filter(post=post, day=today, ip=ip).count() >= EMBED_PLAY_PER_IP_POST:
            return "address"
        if counted.filter(user=user, day=today).count() >= EMBED_PLAY_PER_USER_DAY:
            return "daily"
        return ""
