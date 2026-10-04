"""Push notifications — MCZ reaching a member when the app is closed.

Every notification here used to be in-app only: a reminder you can see only
after you have already opened the app cannot be what brings you back to it.
This sends the ones that are ABOUT YOU — your track was rated, somebody
messaged you, your habit is due — to the browsers you allowed.

Standard Web Push (VAPID). No third-party account: the browser's own push
service delivers it. Off until VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are set
on the server; until then `enabled` is False and the client offers nothing.

What keeps it from becoming the thing people switch off:

* **It rides on `Notification`, not beside it.** A post_save signal pushes the
  row notify() just wrote, so every existing call site gets push for free and
  nothing pushes that is not also in the in-app list. `bulk_create` does not
  fire the signal, which is deliberate — Parcel's campaign DMs are a
  broadcast, and a broadcast is not a reason to buzz somebody's phone.
* **Only kinds a member would want** are on by default (`KINDS`), and each can
  be muted. Likes and follows default OFF: they are frequent and rarely need
  you right now.
* **A daily cap and quiet hours, in the member's own timezone.** The app
  reports the browser's IANA zone once a session; until it has, US Eastern
  (`DEFAULT_TZ`) is assumed.
* **A dead subscription is deleted** the first time the push service answers
  404/410, so a reinstalled browser does not leave a ghost that fails forever.
* **Sending never blocks the request that caused it**: it runs after commit
  on a short-lived thread, and every failure is swallowed. A rating must not
  500 because a phone was offline.
"""
import hashlib
import json
import logging
import threading
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification, PushLog, PushSubscription, UserPreferences

logger = logging.getLogger(__name__)

DAILY_CAP = 3
# When a member's own timezone isn't known yet: US Eastern (New York /
# Connecticut), where most of this platform's members are — Corey's call.
# Quiet hours and the 6pm habit reminder both use it, so an unknown zone gets
# a sensible American evening instead of UTC's, which is the middle of the
# night in the US.
DEFAULT_TZ = "America/New_York"
# key: (label, on by default). Notification kinds not listed never push.
KINDS = {
    "rate": ("Someone rated your work", True),
    "comment": ("Comments on your posts", True),
    "message": ("Direct messages", True),
    "pay": ("Money in or out", True),
    "partnerz": ("PartnerZ and collabs", True),
    "habit_reminder": ("Your habit reminders", True),
    "join": ("Someone joined your restricted post", False),
    "like": ("Likes", False),
    "follow": ("New followers", False),
    "system": ("Everything else from Music ConnectZ", False),
}
TITLES = {
    "rate": "New rating", "comment": "New comment", "message": "New message",
    "pay": "Payment", "partnerz": "PartnerZ", "habit_reminder": "Habit reminder",
    "join": "Restricted post", "like": "New like", "follow": "New follower",
    "system": "Music ConnectZ",
}


def enabled():
    return bool(getattr(settings, "VAPID_PUBLIC_KEY", "") and getattr(settings, "VAPID_PRIVATE_KEY", ""))


def _prefs(user):
    p, _ = UserPreferences.objects.get_or_create(user=user)
    return p


def is_on(prefs, kind):
    if kind not in KINDS:
        return False
    muted = set(prefs.push_muted or [])
    # A kind that is off by default is stored as "+kind" when switched on, so
    # one list carries both directions and a new default never needs a
    # migration of everybody's row.
    return f"+{kind}" in muted if not KINDS[kind][1] else kind not in muted


def tz_of(prefs):
    """The member's own timezone if the browser told us, else US Eastern."""
    try:
        return ZoneInfo(prefs.push_tz) if prefs.push_tz else ZoneInfo(DEFAULT_TZ)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def _quiet_now(prefs, now=None):
    local = (now or timezone.now()).astimezone(tz_of(prefs))
    a, b, h = prefs.quiet_start, prefs.quiet_end, local.hour
    if a == b:
        return False
    return a <= h < b if a < b else (h >= a or h < b)


def url_for(n):
    """Where tapping the push lands — the thing it is about, not the home screen."""
    item = n.item_id or ""
    if item.startswith("post:"):
        return f"/p/{item.split(':', 1)[1]}"
    if n.kind == "message" or item.startswith("dm:"):
        return "/message"
    if item.startswith("habit:"):
        return "/journal"
    if item.startswith("sonday:"):
        return "/sonday"
    if n.actor_id and n.kind in ("follow", "like"):
        return f"/u/{n.actor.username}"
    return "/"


def should_send(user, kind, now=None):
    """Why a push would NOT go to this member right now, or None if it would."""
    prefs = _prefs(user)
    if not prefs.notifications_enabled:
        return "notifications off"
    if not is_on(prefs, kind):
        return "kind muted"
    if _quiet_now(prefs, now):
        return "quiet hours"
    since = (now or timezone.now()) - timedelta(hours=24)
    if PushLog.objects.filter(user=user, sent_at__gte=since).count() >= DAILY_CAP:
        return "daily cap"
    return None


def deliver(user, payload, kind="system"):
    """Send `payload` to every subscription of `user`. Returns devices reached."""
    if not enabled():
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("pywebpush is not installed; push is off")
        return 0
    reached = 0
    for sub in PushSubscription.objects.filter(user=user):
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=json.dumps(payload),
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
                ttl=60 * 60 * 12,
            )
            reached += 1
            PushSubscription.objects.filter(pk=sub.pk).update(last_ok=timezone.now())
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):
                sub.delete()
            else:
                logger.info("push to @%s failed: %s", user.username, e)
        except Exception:
            logger.exception("push to @%s failed", user.username)
    if reached:
        PushLog.objects.create(user=user, kind=kind)
    return reached


def push_notification(n):
    """The push for one in-app Notification row, if it should go."""
    if not enabled() or not PushSubscription.objects.filter(user_id=n.user_id).exists():
        return 0
    if should_send(n.user, n.kind):
        return 0
    return deliver(n.user, {
        "title": TITLES.get(n.kind, "Music ConnectZ"),
        "body": n.text,
        "url": url_for(n),
        "tag": f"{n.kind}:{n.item_id or n.id}",
    }, kind=n.kind)


def _run_async(fn, *args):
    if getattr(settings, "PUSH_SYNC", False):
        fn(*args)
        return
    threading.Thread(target=fn, args=args, daemon=True).start()


@receiver(post_save, sender=Notification)
def _on_notification(sender, instance, created, **kwargs):
    if not created or instance.kind not in KINDS or not enabled():
        return
    nid = instance.pk

    def go():
        try:
            n = Notification.objects.select_related("user", "actor").get(pk=nid)
            push_notification(n)
        except Exception:
            logger.exception("push for notification %s failed", nid)
    transaction.on_commit(lambda: _run_async(go))


# ---- endpoints -------------------------------------------------------------

def _state(user):
    prefs = _prefs(user)
    return {
        "enabled": enabled(),
        "public_key": getattr(settings, "VAPID_PUBLIC_KEY", "") if enabled() else "",
        "devices": PushSubscription.objects.filter(user=user).count(),
        "kinds": [{"key": k, "label": label, "on": is_on(prefs, k)} for k, (label, _) in KINDS.items()],
        "quiet": {"start": prefs.quiet_start, "end": prefs.quiet_end,
                  "tz": prefs.push_tz or DEFAULT_TZ, "tz_guessed": not prefs.push_tz},
        "daily_cap": DAILY_CAP,
        "notifications_enabled": prefs.notifications_enabled,
    }


class PushView(APIView):
    """GET /api/economy/push/ — whether push is on, your devices and switches."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_state(request.user))


class PushSubscribeView(APIView):
    """POST {subscription: PushSubscription.toJSON(), tz} — add this browser.
    DELETE {endpoint} — remove it."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not enabled():
            return Response({"detail": "Push notifications aren't switched on for the platform yet."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        sub = request.data.get("subscription") or {}
        endpoint = str(sub.get("endpoint") or "").strip()
        keys = sub.get("keys") or {}
        p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
        if not endpoint.startswith("https://") or not p256dh or not auth:
            return Response({"detail": "That isn't a browser push subscription."}, status=status.HTTP_400_BAD_REQUEST)
        h = hashlib.sha256(endpoint.encode()).hexdigest()
        PushSubscription.objects.update_or_create(
            endpoint_hash=h,
            defaults={"user": request.user, "endpoint": endpoint, "p256dh": p256dh[:200], "auth": auth[:100]})
        tz = str(request.data.get("tz") or "").strip()[:64]
        if tz:
            try:
                ZoneInfo(tz)
                p = _prefs(request.user)
                p.push_tz = tz
                p.save(update_fields=["push_tz", "updated_at"])
            except Exception:
                pass
        return Response(_state(request.user), status=status.HTTP_201_CREATED)

    def delete(self, request):
        endpoint = str((request.data or {}).get("endpoint") or "").strip()
        if endpoint:
            PushSubscription.objects.filter(
                user=request.user, endpoint_hash=hashlib.sha256(endpoint.encode()).hexdigest()).delete()
        else:
            PushSubscription.objects.filter(user=request.user).delete()
        return Response(_state(request.user))


class PushPrefsView(APIView):
    """POST {kinds: {key: bool}, quiet_start, quiet_end} — your switches."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        p = _prefs(request.user)
        muted = set(p.push_muted or [])
        for k, on in (request.data.get("kinds") or {}).items():
            if k not in KINDS:
                continue
            default_on = KINDS[k][1]
            muted.discard(k)
            muted.discard(f"+{k}")
            if default_on and not on:
                muted.add(k)
            elif not default_on and on:
                muted.add(f"+{k}")
        p.push_muted = sorted(muted)
        fields = ["push_muted"]
        # The app sends the browser's zone once a session, so reminders and
        # quiet hours are local even for members who never turned push on.
        tz = str(request.data.get("tz") or "").strip()[:64]
        if tz:
            try:
                ZoneInfo(tz)
                p.push_tz = tz
                fields.append("push_tz")
            except Exception:
                pass
        for f in ("quiet_start", "quiet_end"):
            if f in request.data:
                try:
                    v = int(request.data[f])
                except (TypeError, ValueError):
                    return Response({"detail": f"{f} must be an hour 0-23."}, status=status.HTTP_400_BAD_REQUEST)
                if not 0 <= v <= 23:
                    return Response({"detail": f"{f} must be an hour 0-23."}, status=status.HTTP_400_BAD_REQUEST)
                setattr(p, f, v)
                fields.append(f)
        p.save(update_fields=fields + ["updated_at"])
        return Response(_state(request.user))


class PushTestView(APIView):
    """POST — send yourself a test push. Not counted against the daily cap."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not enabled():
            return Response({"detail": "Push notifications aren't switched on for the platform yet."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        n = 0
        try:
            from pywebpush import webpush  # noqa: F401
            n = _deliver_uncounted(request.user, {
                "title": "Music ConnectZ", "body": "Push is working on this device. 🎧",
                "url": "/", "tag": "test"})
        except ImportError:
            pass
        return Response({"reached": n})


def _deliver_uncounted(user, payload):
    reached = deliver(user, payload, kind="test")
    if reached:
        PushLog.objects.filter(user=user, kind="test").delete()
    return reached
