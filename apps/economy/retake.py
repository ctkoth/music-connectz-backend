"""Retake reminders — the trial's way back.

The probable failure of this platform is not a crash, it is a stranger who
scores one take and is never seen again. The trial asked for nothing and so
had nothing to come back through: no account, no email, no push. And the
coach's real value is the CHANGE between two takes — "your breath control
went from 5 to 7" — which needs a second visit by definition.

So under the score there is one field: "email me this, and remind me to send
another take." No account. The schedule is fixed and stated before they type:

    now     the score, the verdict and the drill they were given
    day 3   send the same take again and see if it moved
    day 7   last reminder
    then    nothing

Rules, each of which is the codebase's existing rule pointed at email:

- **The claim token is the proof.** Only somebody holding a scored trial take
  can ask, and each take arms one reminder. That ties the abuse ceiling to the
  trial's own caps (one per browser, the per-address backstop and the global
  daily cap) instead of inventing a fourth limit.
- **No email set up means no field.** With no EMAIL_HOST, Django prints mail
  to the console. A form that answered "sent" then would be the "saved" lie
  this codebase has shipped twice, so `ready()` is published and the screen
  renders nothing when it is false, and the endpoint refuses rather than
  pretending.
- **Days count from the LATEST take.** A browser that comes back and scores
  again re-arms the schedule, so nobody is told on day 3 to do what they did
  on day 2.
- **The stop link works without signing in, and GET changes nothing.** Mail
  scanners open links — `ParcelUnsubscribeView`'s reasoning, followed exactly.
- **Joining stops it.** The emails pitch the free trial door; a member has the
  coach itself, and an email telling a member to use the no-account door is
  wrong advice.
- **A failed send never advances the schedule**, and three in a row stop it
  rather than retrying an address forever.
"""
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import escape
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import TRIAL_CLAIM_DAYS, RetakeReminder, TrialTake

DAY3, DAY7 = 3, 7
# One address may be armed this many times a day. Each needs its own scored
# take, so this only matters to somebody pointing many takes at one inbox —
# which is the case where the inbox's owner did not ask.
PER_EMAIL_PER_DAY = 3
MAX_FAILURES = 3

SCHEDULE = (f"Your score and drill now, a reminder to send another take on day {DAY3} "
            f"and day {DAY7}, then nothing. Every email has a one-click stop.")

_LABELS = {"singz": "SingZ", "rapz": "RapZ", "guitarz": "GuitarZ", "bassz": "BassZ",
           "keyz": "KeyZ", "drumz": "DrumZ", "violinz": "ViolinZ"}


def ready():
    """Can mail actually leave? The console backend is not a yes."""
    return bool(getattr(settings, "EMAIL_HOST", ""))


def offer():
    """What the score screen needs to render the field — or not to."""
    return {"ready": ready(), "schedule": SCHEDULE, "days": [DAY3, DAY7]}


def _label(app_key):
    return _LABELS.get(app_key, app_key)


def _api_base():
    return (getattr(settings, "API_PUBLIC_URL", "") or "https://admin.musicconnectz.net").rstrip("/")


def stop_url(r):
    return f"{_api_base()}/api/economy/trial/remind/stop/?t={r.token}"


def retake_url(r, src):
    base = getattr(settings, "FRONTEND_URL", "https://musicconnectz.net").rstrip("/")
    return f"{base}/try/{r.app_key}?src={src}"


def _result(r):
    return (r.trial_take.result or {}) if r.trial_take_id and r.trial_take else {}


def _score_line(res):
    s = res.get("score")
    return f"{s}/10" if s is not None else "no score"


def compose(r, stage):
    """(subject, body) for one stage. Plain text: a reminder, not a newsletter."""
    res = _result(r)
    label = _label(r.app_key)
    score = _score_line(res)
    fixes = [str(f) for f in (res.get("fixes") or [])][:3]
    drill = str(res.get("next_drill") or "").strip()
    stop = f"\n\nStop these emails (one click, no sign-in): {stop_url(r)}\n"

    if stage == RetakeReminder.STAGE_SCORE:
        lines = [f"Your {label} take scored {score}."]
        if res.get("verdict"):
            lines.append(str(res["verdict"]))
        if fixes:
            lines.append("What cost you points:\n" + "\n".join(f"  - {f}" for f in fixes))
        if drill:
            lines.append(f"Your drill: {drill}")
        lines.append(f"In {DAY3} days we'll remind you to send the same take again, so you "
                     f"can see whether it moved. One more reminder on day {DAY7}, then nothing.")
        lines.append(f"Make a free account and every take is kept and tracked: "
                     f"{getattr(settings, 'FRONTEND_URL', '').rstrip('/')}/register")
        return f"Your {label} take: {score}", "\n\n".join(lines) + stop

    src = "retake_d3" if stage == RetakeReminder.STAGE_DAY3 else "retake_d7"
    link = retake_url(r, src)
    if stage == RetakeReminder.STAGE_DAY3:
        subject = f"Did your {label} take move? Last time: {score}"
        lead = (f"{DAY3} days ago your {label} take scored {score}. "
                f"Send the same take again and see whether the work showed up.")
    else:
        subject = f"Last reminder: your {label} take was {score}"
        lead = (f"A week ago your {label} take scored {score}. This is the last reminder — "
                f"one more take tells you whether you're moving.")
    lines = [lead]
    if drill:
        lines.append(f"The drill you were given: {drill}")
    lines.append(f"Free, no account: {link}")
    return subject, "\n\n".join(lines) + stop


def send(r, stage):
    """Send one stage. True if it went. Never raises."""
    subject, body = compose(r, stage)
    msg = EmailMessage(subject, body, to=[r.email], headers={
        # One-click unsubscribe (RFC 8058). The POST stops it, like the button.
        "List-Unsubscribe": f"<{stop_url(r)}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    })
    try:
        return msg.send(fail_silently=False) > 0
    except Exception:  # noqa: BLE001 — SMTP raises a zoo; any of them is "not sent"
        return False


def rearm_for(take):
    """A browser with a live reminder scored again: count the days from now.

    Best-effort. A reminder must never be the reason a take fails to save.
    """
    if not take.anon_id or not take.scored:
        return
    try:
        (RetakeReminder.objects
         .filter(anon_id=take.anon_id, app_key=take.app_key, stopped_at__isnull=True,
                 stage__gte=RetakeReminder.STAGE_SCORE)
         .update(trial_take=take, armed_at=timezone.now(), stage=RetakeReminder.STAGE_SCORE))
    except Exception:  # noqa: BLE001
        pass


def stop_for_member(user):
    """They joined — the trial-door emails are now wrong advice. Best-effort."""
    email = (getattr(user, "email", "") or "").strip()
    if not email:
        return
    try:
        RetakeReminder.objects.filter(email__iexact=email, stopped_at__isnull=True).update(
            stopped_at=timezone.now(), stop_reason="joined")
    except Exception:  # noqa: BLE001
        pass


def due(now=None):
    """Live reminders whose next stage has come round, as (reminder, stage)."""
    now = now or timezone.now()
    live = RetakeReminder.objects.filter(stopped_at__isnull=True).select_related("trial_take")
    for r in live.filter(stage=RetakeReminder.STAGE_SCORE, armed_at__lte=now - timedelta(days=DAY3)):
        yield r, RetakeReminder.STAGE_DAY3
    for r in live.filter(stage=RetakeReminder.STAGE_DAY3, armed_at__lte=now - timedelta(days=DAY7)):
        yield r, RetakeReminder.STAGE_DAY7


def run_due(now=None):
    """Send everything due. Returns (sent, failed). The cron calls this."""
    sent = failed = 0
    for r, stage in list(due(now)):
        if send(r, stage):
            r.stage, r.failures = stage, 0
            r.save(update_fields=["stage", "failures"])
            sent += 1
        else:
            r.failures += 1
            fields = ["failures"]
            if r.failures >= MAX_FAILURES:
                r.stopped_at, r.stop_reason = timezone.now(), "failed"
                fields += ["stopped_at", "stop_reason"]
            r.save(update_fields=fields)
            failed += 1
    return sent, failed


class RetakeRemindView(APIView):
    """POST /api/economy/trial/remind/ {claim_token, email, anon_id?}

    Sends the score now and arms the day-3 / day-7 reminders. GET answers
    whether the field should render at all.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response(offer())

    def post(self, request):
        if not ready():
            return Response({"detail": "Email isn't switched on here yet, so we can't send this. "
                                       "Make a free account and your take is kept instead.",
                             "ready": False}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        email = str(request.data.get("email") or "").strip()[:254]
        try:
            validate_email(email)
        except ValidationError:
            return Response({"detail": "That doesn't look like an email address."},
                            status=status.HTTP_400_BAD_REQUEST)

        token = str(request.data.get("claim_token") or "").strip()[:64]
        cutoff = timezone.now() - timedelta(days=TRIAL_CLAIM_DAYS)
        take = TrialTake.objects.filter(token=token, created_at__gte=cutoff).first() if token else None
        if not take or not take.scored:
            return Response({"detail": "That take has expired, or never got a score — "
                                       "score one first and this will send it."},
                            status=status.HTTP_400_BAD_REQUEST)

        existing = RetakeReminder.objects.filter(trial_take=take).first()
        if existing and existing.email.lower() == email.lower() and existing.stopped_at is None:
            # Pressed twice. Already sent; sending again is how a button
            # becomes spam.
            return Response({"sent": True, "email": existing.email, "schedule": SCHEDULE})

        since = timezone.now() - timedelta(hours=24)
        if RetakeReminder.objects.filter(email__iexact=email, created_at__gte=since).count() \
                >= PER_EMAIL_PER_DAY:
            return Response({"detail": "That address has had enough from us today. Try tomorrow."},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)

        r = existing or RetakeReminder(trial_take=take, token=secrets.token_urlsafe(24))
        r.email, r.app_key = email, take.app_key
        r.anon_id = str(request.data.get("anon_id") or take.anon_id or "").strip()[:64]
        r.armed_at, r.stage, r.failures = timezone.now(), 0, 0
        r.stopped_at, r.stop_reason = None, ""
        r.save()

        if not send(r, RetakeReminder.STAGE_SCORE):
            # Nothing armed: a reminder schedule hanging off an email that
            # never arrived would be reminding them of something they never got.
            r.stopped_at, r.stop_reason = timezone.now(), "failed"
            r.save(update_fields=["stopped_at", "stop_reason"])
            return Response({"detail": "We couldn't send to that address. Check it and try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        r.stage = RetakeReminder.STAGE_SCORE
        r.save(update_fields=["stage"])
        return Response({"sent": True, "email": r.email, "schedule": SCHEDULE},
                        status=status.HTTP_201_CREATED)


_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Music ConnectZ email</title><style>body{{font-family:system-ui,sans-serif;background:#07060d;color:#eee;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;padding:16px}}main{{max-width:420px}}
button{{background:#22d3ee;color:#000;border:0;border-radius:8px;padding:10px 16px;font-weight:700;cursor:pointer}}</style>
</head><body><main><h1>Music ConnectZ</h1>{body}</main></body></html>"""


class RetakeStopView(APIView):
    """The stop link in every reminder. GET asks, POST stops — a mail scanner
    opening the link must not unsubscribe anybody."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def _reminder(self, request):
        t = str(request.query_params.get("t") or (request.data or {}).get("t") or "").strip()[:64]
        return RetakeReminder.objects.filter(token=t).first() if t else None

    def get(self, request):
        r = self._reminder(request)
        if not r:
            return HttpResponse(_PAGE.format(body="<p>That link isn't valid any more.</p>"), status=400)
        if r.stopped_at:
            return HttpResponse(_PAGE.format(body="<p>Already stopped. Nothing more is coming.</p>"))
        return HttpResponse(_PAGE.format(body=(
            "<p>Stop the retake reminders?</p>"
            f'<form method="post"><input type="hidden" name="t" value="{escape(r.token)}">'
            '<button type="submit">Stop them</button></form>')))

    def post(self, request):
        r = self._reminder(request)
        if not r:
            return HttpResponse(_PAGE.format(body="<p>That link isn't valid any more.</p>"), status=400)
        if not r.stopped_at:
            r.stopped_at, r.stop_reason = timezone.now(), "unsubscribed"
            r.save(update_fields=["stopped_at", "stop_reason"])
        return HttpResponse(_PAGE.format(body="<p>Done — no more reminders.</p>"))
