"""Parcel Primate — Mailchimp-style campaigns for Music ConnectZ.

A campaign is composed like a post (subject + body) and blasted to your audience
across up to three channels that all follow the same post paradigm:
  • post    — publishes a public PostZ from you (shows in the feed)
  • message — sends each recipient a DM (+ in-app notification)
  • email   — emails each recipient who has an address on file

Audience is your own following graph (your subscribers), never the whole
platform — this is a creator reaching their fans, not spam. Blocked users are
excluded. Email only actually delivers when SMTP is configured (EMAIL_HOST);
otherwise it no-ops cleanly and the response says email isn't wired up yet.
"""
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Block, Follow, Message, Post, notify

# Cap a single blast so a campaign can't fan out unbounded.
MAX_RECIPIENTS = 5000
AUDIENCES = ("followers", "fans", "friends")


def _email_ready():
    return bool(getattr(settings, "EMAIL_HOST", ""))


def _audience_users(user, audience):
    """Resolve an audience to a list of User objects from the follow graph,
    excluding anyone who has blocked the sender."""
    following_ids = set(Follow.objects.filter(follower=user).values_list("following_id", flat=True))
    follower_ids = set(Follow.objects.filter(following=user).values_list("follower_id", flat=True))
    if audience == "followers":
        ids = follower_ids
    elif audience == "fans":
        ids = follower_ids - following_ids          # follow you, you don't follow back
    elif audience == "friends":
        ids = follower_ids & following_ids           # mutual
    else:
        ids = set()
    # Drop anyone who blocked the sender.
    blocked_by = set(Block.objects.filter(blocked=user, blocker_id__in=ids).values_list("blocker_id", flat=True))
    ids -= blocked_by
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return list(User.objects.filter(id__in=ids)[:MAX_RECIPIENTS])


class ParcelCampaignView(APIView):
    """GET audience sizes + email readiness; POST sends a campaign."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        sizes = {a: len(_audience_users(request.user, a)) for a in AUDIENCES}
        return Response({"audiences": sizes, "email_ready": _email_ready(), "max_recipients": MAX_RECIPIENTS})

    def post(self, request):
        d = request.data or {}
        subject = str(d.get("subject", "")).strip()[:160]
        body = str(d.get("body", "")).strip()
        audience = str(d.get("audience", "followers")).lower()
        channels = d.get("channels") or ["post"]
        if not subject:
            return Response({"detail": "subject required"}, status=status.HTTP_400_BAD_REQUEST)
        if audience not in AUDIENCES:
            return Response({"detail": f"audience must be one of {list(AUDIENCES)}"}, status=status.HTTP_400_BAD_REQUEST)
        channels = [c for c in channels if c in ("post", "message", "email")]
        if not channels:
            return Response({"detail": "pick at least one channel: post | message | email"}, status=status.HTTP_400_BAD_REQUEST)

        recipients = _audience_users(request.user, audience)
        out = {"recipients": len(recipients), "posted": 0, "messaged": 0, "emailed": 0, "email_ready": _email_ready()}

        # post channel — publishes one PostZ from the sender (post paradigm).
        if "post" in channels:
            Post.objects.create(
                author=request.user, title=subject, description=body,
                media_type="campaign", visibility="public",
            )
            out["posted"] = 1

        # message channel — a DM + notification to each recipient.
        if "message" in channels and recipients:
            dm_body = f"📣 {subject}\n\n{body}".strip()
            Message.objects.bulk_create([
                Message(sender=request.user, recipient=r, body=dm_body) for r in recipients
            ])
            for r in recipients:
                notify(r, "message", f"📣 {subject}", actor=request.user)
            out["messaged"] = len(recipients)

        # email channel — real email to recipients who have an address on file.
        if "email" in channels:
            targets = [(subject, body or subject, r.email) for r in recipients if getattr(r, "email", "")]
            if _email_ready() and targets:
                try:
                    from django.core.mail import send_mass_mail
                    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
                    send_mass_mail(
                        tuple((s, b, from_email, [addr]) for (s, b, addr) in targets),
                        fail_silently=True,
                    )
                    out["emailed"] = len(targets)
                except Exception:
                    out["emailed"] = 0
            else:
                out["emailed"] = 0
                if not _email_ready():
                    out["email_note"] = "Email isn't wired up yet — set EMAIL_HOST to send. Posts/DMs still went out."

        return Response(out, status=status.HTTP_201_CREATED)
