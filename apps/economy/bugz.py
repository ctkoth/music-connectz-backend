"""BugZ 🐞 — report what broke, attach the proof, get paid when it's fixed.

The screen has called `/api/bugz/` since it shipped and nothing served it, so
every report 404'd while the page advertised a 200 🍥 bounty. This is the
endpoint behind that promise.

Three decisions worth naming:

* **Evidence is optional but first-class.** A screenshot or a screen recording
  rides with the report. "It looked wrong" is the hardest bug to write down and
  the easiest to photograph, and most of triage is working out what the reporter
  actually saw. One field takes either kind — making somebody choose the right
  slot before they can tell you something is broken is friction on the one
  screen that exists to remove it.
* **The bounty is paid once and recorded.** `paid_at` means a report that gets
  reopened and squashed again can't pay twice, and the fixed 200 on the page
  stays the number that actually moves.
* **Everyone sees the queue.** A reporter who can't see their own report landing
  has no way to know it worked, and a public queue stops five people filing the
  same thing.
"""
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    BUG_BOUNTY_SPINAZ,
    BUG_MAX_MB,
    BugReport,
    pay_bug_bounty,
)


def bug_dict(bug, request=None):
    url = ""
    if bug.shot:
        try:
            url = request.build_absolute_uri(bug.shot.url) if request else bug.shot.url
        except ValueError:
            url = ""
    return {
        "id": bug.id,
        "title": bug.title,
        "body": bug.body,
        "reporter": bug.reporter.username,
        "status": bug.status,
        "app_key": bug.app_key,
        # The proof, and which kind it is, so the client renders <img> or
        # <video> rather than guessing from the file extension.
        "shot_url": url,
        "shot_type": bug.shot_type,
        "paid": bool(bug.paid_at),
        "bounty_spinaz": BUG_BOUNTY_SPINAZ,
        "created_at": bug.created_at.isoformat(),
        # Cross-pollination: a report that knows where it happened opens back
        # on the screen that broke, instead of dead-ending in a list.
        "open_in": bug.app_key or "",
    }


class BugzView(APIView):
    """GET the queue; POST a report, optionally with a screenshot or recording."""

    permission_classes = [IsAuthenticated]
    # Multipart for the evidence, JSON for a plain text report — the screen sent
    # JSON before this endpoint existed, and that has to keep working.
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        bugs = (BugReport.objects.select_related("reporter")
                .exclude(status=BugReport.STATUS_DECLINED)[:200])
        return Response({
            "bugs": [bug_dict(b, request) for b in bugs],
            "bounty_spinaz": BUG_BOUNTY_SPINAZ,
            "max_mb": BUG_MAX_MB,
        })

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()[:200]
        if not title:
            return Response({"detail": "Say what broke — a title is enough to start."},
                            status=status.HTTP_400_BAD_REQUEST)

        shot = request.FILES.get("shot") or request.FILES.get("file")
        shot_type = ""
        if shot:
            ct = (getattr(shot, "content_type", "") or "").lower()
            if ct.startswith("image/"):
                shot_type = "image"
            elif ct.startswith("video/"):
                shot_type = "video"
            else:
                return Response(
                    {"detail": "Attach a screenshot or a screen recording — image or video."},
                    status=status.HTTP_400_BAD_REQUEST)
            if shot.size > BUG_MAX_MB * 1024 * 1024:
                return Response(
                    {"detail": f"Keep the attachment under {BUG_MAX_MB}MB — a screenshot or a "
                               "short clip of the moment it broke is plenty.",
                     "max_mb": BUG_MAX_MB},
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        bug = BugReport.objects.create(
            reporter=request.user,
            title=title,
            body=str(d.get("body", ""))[:8000],
            app_key=str(d.get("app_key", ""))[:32],
            shot=shot or None,
            shot_type=shot_type,
        )
        return Response(bug_dict(bug, request), status=status.HTTP_201_CREATED)


class BugTriageView(APIView):
    """PATCH /api/bugz/<pk>/ — the owner moves a report and pays the bounty.

    Paying is a side effect of reaching `squashed`, not a separate button: a
    bounty that has to be remembered is a bounty that gets forgotten, and the
    screen promises it unconditionally.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        from .views import is_owner
        if not is_owner(request.user):
            return Response({"detail": "Only the platform owner triages BugZ."},
                            status=status.HTTP_403_FORBIDDEN)
        bug = BugReport.objects.filter(pk=pk).first()
        if not bug:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)

        wanted = str((request.data or {}).get("status", "")).strip().lower()
        valid = {c for c, _ in BugReport.STATUS_CHOICES}
        if wanted not in valid:
            return Response({"detail": "No such status.", "statuses": sorted(valid)},
                            status=status.HTTP_400_BAD_REQUEST)
        bug.status = wanted
        bug.save(update_fields=["status", "updated_at"])
        paid = pay_bug_bounty(bug, by=request.user)
        return Response({**bug_dict(bug, request), "just_paid": paid})
