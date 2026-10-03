"""Parcel Primate — a creator's newsletter to the people who follow them.

A campaign is composed like a post (subject + body) and sent to your audience
through up to three doors:
  • post    — one public PostZ from you, in the feed
  • message — a DM to each recipient, with an in-app notification
  • email   — an email to each recipient who ASKED for campaign email

The audience is your own follow graph — followers, fans or friends — never the
whole platform, and anybody blocked in either direction is left out.

What changed before this got a screen, because each was a way to turn a
newsletter into spam with our domain's name on it:

* **Email is opt-in, per recipient.** It used to email every follower's private
  address. Following somebody is consent to see their posts, not to get their
  mail, and the follower never gave the sender that address. So email goes
  only to members with `UserPreferences.campaign_email` on (default OFF) and
  notifications not switched off. The send screen states how many that is
  BEFORE you press send, so nobody discovers it on the receipt.
* **Every campaign email can be stopped from the email.** A signed one-click
  link (and List-Unsubscribe headers) turns it off without signing in. A mail
  with no way out is the definition of the thing spam filters exist for, and
  one sender doing it costs every member's mail its inbox.
* **How often is a ladder.** `catalog.PARCEL_PER_WEEK` — Free 1, Premium 7,
  StatZ 21 per rolling week — served with the form. Nothing capped it before:
  a member could DM 5,000 people in a loop.
* **The body answers to the tier's character limit**, like every other
  member-authored field.
* **Every send is kept** (`ParcelCampaign`), so the sender has a history, and
  the post it made is a link rather than a fact.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.mail import EmailMessage, get_connection
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import escape
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import PARCEL_PER_WEEK, over_char_limit
from .models import (
    Follow, Message, Notification, ParcelCampaign, Post, UserPreferences,
    blocked_user_ids, membership_for,
)

User = get_user_model()

MAX_RECIPIENTS = 5000
AUDIENCES = ("followers", "fans", "friends")
CHANNELS = ("post", "message", "email")
_SALT = "parcel-unsubscribe"


def _email_ready():
    return bool(getattr(settings, "EMAIL_HOST", ""))


def _audience_ids(user, audience):
    following = set(Follow.objects.filter(follower=user).values_list("following_id", flat=True))
    followers = set(Follow.objects.filter(following=user).values_list("follower_id", flat=True))
    ids = {"followers": followers, "fans": followers - following,
           "friends": followers & following}.get(audience, set())
    return ids - blocked_user_ids(user) - {user.id}


def _audience_users(user, audience):
    return list(User.objects.filter(id__in=_audience_ids(user, audience))
                .select_related("onboarding_preferences")[:MAX_RECIPIENTS])


def _wants_email(u):
    """Asked for campaign email, hasn't silenced notifications, has an address."""
    if not (getattr(u, "email", "") or "").strip():
        return False
    try:
        p = u.onboarding_preferences
    except UserPreferences.DoesNotExist:
        return False
    return bool(p.campaign_email and p.notifications_enabled)


def _email_count(ids):
    return (UserPreferences.objects.filter(user_id__in=ids, campaign_email=True, notifications_enabled=True)
            .exclude(user__email="").count())


def quota_for(user):
    tier = membership_for(user).tier
    per_week = PARCEL_PER_WEEK.get(tier, PARCEL_PER_WEEK["free"])
    since = timezone.now() - timedelta(days=7)
    sent = list(ParcelCampaign.objects.filter(sender=user, created_at__gte=since)
                .order_by("created_at").values_list("created_at", flat=True))
    left = max(0, per_week - len(sent))
    # When the oldest send in the window ages out, one more opens up — said as
    # a time so "0 left" is never a dead end without a date on it.
    next_at = (sent[0] + timedelta(days=7)).isoformat() if not left and sent else None
    return {"tier": tier, "per_week": per_week, "used": len(sent), "left": left, "next_at": next_at}


def unsubscribe_token(user):
    return signing.dumps({"u": user.id}, salt=_SALT)


def unsubscribe_url(request, user):
    base = request.build_absolute_uri("/api/economy/parcel/unsubscribe/")
    return f"{base}?t={unsubscribe_token(user)}"


def _campaign_dict(c):
    return {
        "id": c.id, "subject": c.subject, "body": c.body, "audience": c.audience,
        "channels": c.channels, "recipients": c.recipients, "messaged": c.messaged,
        "emailed": c.emailed, "created_at": c.created_at,
        "post": {"id": c.post_id, "url": f"/p/{c.post_id}"} if c.post_id else None,
    }


class ParcelCampaignView(APIView):
    """GET: who each audience reaches and through which door, the weekly count,
    and past sends. POST: send one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        me = request.user
        audiences = {}
        for a in AUDIENCES:
            ids = _audience_ids(me, a)
            n = min(len(ids), MAX_RECIPIENTS)
            audiences[a] = n
        reach = {a: {"people": audiences[a],
                     "email": _email_count(list(_audience_ids(me, a))[:MAX_RECIPIENTS])}
                 for a in AUDIENCES}
        history = ParcelCampaign.objects.filter(sender=me)[:20]
        return Response({
            # `audiences` keeps the shape it shipped with; `reach` is the
            # per-door breakdown the send screen states before you press it.
            "audiences": audiences,
            "reach": reach,
            "email_ready": _email_ready(),
            "max_recipients": MAX_RECIPIENTS,
            "quota": quota_for(me),
            "history": [_campaign_dict(c) for c in history],
            "email_rule": "Email only reaches followers who turned on campaign email "
                          "in their settings. Everyone else gets your post and DM.",
        })

    def post(self, request):
        me = request.user
        d = request.data or {}
        subject = str(d.get("subject", "")).strip()[:160]
        body = str(d.get("body", "")).strip()
        audience = str(d.get("audience", "followers")).lower()
        channels = d.get("channels") or ["post"]
        if not isinstance(channels, (list, tuple)):
            channels = [channels]
        if not subject:
            return Response({"detail": "subject required"}, status=status.HTTP_400_BAD_REQUEST)
        if audience not in AUDIENCES:
            return Response({"detail": f"audience must be one of {list(AUDIENCES)}"}, status=status.HTTP_400_BAD_REQUEST)
        channels = [c for c in CHANNELS if c in channels]
        if not channels:
            return Response({"detail": "pick at least one channel: post | message | email"}, status=status.HTTP_400_BAD_REQUEST)
        tier = membership_for(me).tier
        cap = over_char_limit(body, tier)
        if cap:
            return Response({"detail": f"That campaign is over your {cap:,}-character limit — upgrade in MembershipZ for more room.",
                             "char_limit": cap}, status=status.HTTP_400_BAD_REQUEST)
        q = quota_for(me)
        if q["left"] <= 0:
            return Response({
                "detail": f"You've sent {q['used']} campaign{'s' if q['used'] != 1 else ''} this week — "
                          f"your tier sends {q['per_week']} a week.",
                "quota": q,
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        recipients = _audience_users(me, audience)
        out = {"recipients": len(recipients), "posted": 0, "messaged": 0, "emailed": 0,
               "email_ready": _email_ready()}
        post = None

        if "post" in channels:
            post = Post.objects.create(author=me, title=subject, description=body,
                                       media_type="campaign", visibility="public")
            out["posted"] = 1
            out["post"] = {"id": post.id, "url": f"/p/{post.id}"}

        if "message" in channels and recipients:
            dm_body = f"📣 {subject}\n\n{body}".strip()
            Message.objects.bulk_create([Message(sender=me, recipient=r, body=dm_body) for r in recipients])
            # One insert for every notification rather than one per recipient.
            Notification.objects.bulk_create([
                Notification(user=r, actor=me, kind="message", text=f"📣 {subject}"[:280]) for r in recipients
            ])
            out["messaged"] = len(recipients)

        if "email" in channels:
            targets = [r for r in recipients if _wants_email(r)]
            out["email_eligible"] = len(targets)
            if not _email_ready():
                out["email_note"] = "Email isn't switched on for the platform yet. Your post and DMs still went out."
            elif targets:
                out["emailed"] = self._send_emails(request, me, subject, body, targets)

        c = ParcelCampaign.objects.create(
            sender=me, subject=subject, body=body, audience=audience, channels=channels,
            recipients=len(recipients), messaged=out["messaged"], emailed=out["emailed"], post=post)
        out["campaign"] = _campaign_dict(c)
        out["quota"] = quota_for(me)
        return Response(out, status=status.HTTP_201_CREATED)

    @staticmethod
    def _send_emails(request, sender, subject, body, targets):
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
        sent = 0
        try:
            conn = get_connection(fail_silently=True)
            msgs = []
            for r in targets:
                unsub = unsubscribe_url(request, r)
                text = (
                    f"{body or subject}\n\n"
                    f"— @{sender.username}, on Music ConnectZ\n\n"
                    f"You're getting this because you follow @{sender.username} and turned on "
                    f"campaign email. Stop all campaign email with one click: {unsub}"
                )
                m = EmailMessage(subject=subject, body=text, from_email=from_email, to=[r.email],
                                 headers={"List-Unsubscribe": f"<{unsub}>",
                                          "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"})
                msgs.append(m)
            sent = conn.send_messages(msgs) or 0
        except Exception:
            sent = 0
        return sent


class ParcelEmailPrefView(APIView):
    """GET/POST /api/economy/parcel/email-pref/ — your own campaign-email switch."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        p, _ = UserPreferences.objects.get_or_create(user=request.user)
        return Response({"campaign_email": p.campaign_email, "has_email": bool(request.user.email)})

    def post(self, request):
        p, _ = UserPreferences.objects.get_or_create(user=request.user)
        p.campaign_email = bool(request.data.get("campaign_email"))
        p.save(update_fields=["campaign_email", "updated_at"])
        return Response({"campaign_email": p.campaign_email, "has_email": bool(request.user.email)})


_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Music ConnectZ email</title><style>body{{font-family:system-ui,sans-serif;background:#07060d;color:#eee;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;padding:16px}}main{{max-width:420px}}
button{{background:#22d3ee;color:#000;border:0;border-radius:8px;padding:10px 16px;font-weight:700;cursor:pointer}}</style>
</head><body><main><h1>Music ConnectZ</h1>{body}</main></body></html>"""


class ParcelUnsubscribeView(APIView):
    """The link in every campaign email. No sign-in needed.

    GET shows a button and changes nothing — mail scanners open links, and a
    stop that fired on a scanner's visit would unsubscribe people who never
    asked to. POST (the button, or a mail client's one-click) turns it off.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def _user(self, request):
        t = request.query_params.get("t") or (request.data or {}).get("t") or ""
        try:
            uid = signing.loads(t, salt=_SALT)["u"]
        except (signing.BadSignature, KeyError, TypeError):
            return None
        return User.objects.filter(pk=uid).first()

    def get(self, request):
        u = self._user(request)
        if not u:
            return HttpResponse(_PAGE.format(body="<p>That link isn't valid any more.</p>"), status=400)
        t = escape(request.query_params.get("t", ""))
        return HttpResponse(_PAGE.format(body=(
            f"<p>Stop all campaign email to @{escape(u.username)}?</p>"
            f'<form method="post"><input type="hidden" name="t" value="{t}"><button type="submit">Stop campaign email</button></form>'
            "<p style='opacity:.6;font-size:13px'>Messages and notifications in the app aren't affected.</p>")))

    def post(self, request):
        u = self._user(request)
        if not u:
            return HttpResponse(_PAGE.format(body="<p>That link isn't valid any more.</p>"), status=400)
        p, _ = UserPreferences.objects.get_or_create(user=u)
        if p.campaign_email:
            p.campaign_email = False
            p.save(update_fields=["campaign_email", "updated_at"])
        return HttpResponse(_PAGE.format(body=(
            "<p>Done — no more campaign email. You can turn it back on in Parcel Primate any time.</p>")))
