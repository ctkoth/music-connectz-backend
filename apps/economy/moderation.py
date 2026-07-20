"""Moderation: report content + block users. Store-required trust & safety."""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import get_user_model

from .models import Report, Block, blocked_user_ids

User = get_user_model()
VALID_REASONS = {r[0] for r in Report.REASONS}


def _is_owner(user):
    return bool(user and (user.is_superuser or user.is_staff))


class ReportView(APIView):
    """POST {item, reason, note} files a report (one per user/item).
    GET lists open reports — owner only (the moderation queue)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        item = str((request.data or {}).get("item", "")).strip()[:160]
        if not item:
            return Response({"detail": "item required"}, status=status.HTTP_400_BAD_REQUEST)
        reason = str((request.data or {}).get("reason", "other")).lower()
        if reason not in VALID_REASONS:
            reason = "other"
        Report.objects.update_or_create(
            reporter=request.user, item_id=item,
            defaults={"reason": reason, "note": str((request.data or {}).get("note", ""))[:280]},
        )
        return Response({"reported": True, "item": item, "reports": Report.objects.filter(item_id=item, resolved=False).count()})

    def get(self, request):
        if not _is_owner(request.user):
            return Response({"detail": "owner only"}, status=status.HTTP_403_FORBIDDEN)
        rows = Report.objects.filter(resolved=False).select_related("reporter")[:100]
        return Response({"reports": [
            {"id": r.id, "item_id": r.item_id, "reason": r.reason, "note": r.note,
             "reporter": r.reporter.username, "created_at": r.created_at.isoformat()}
            for r in rows
        ]})


class BlockView(APIView):
    """POST {username, action: block|unblock}. GET lists who you've blocked."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = Block.objects.filter(blocker=request.user).select_related("blocked")
        return Response({"blocked": [b.blocked.username for b in rows]})

    def post(self, request):
        username = str((request.data or {}).get("username", "")).strip()
        action = str((request.data or {}).get("action", "block")).lower()
        target = User.objects.filter(username=username).first()
        if not target:
            return Response({"detail": "unknown user"}, status=status.HTTP_404_NOT_FOUND)
        if target.id == request.user.id:
            return Response({"detail": "can't block yourself"}, status=status.HTTP_400_BAD_REQUEST)
        if action == "unblock":
            Block.objects.filter(blocker=request.user, blocked=target).delete()
        else:
            Block.objects.get_or_create(blocker=request.user, blocked=target)
            # Blocking severs any follow relationship both ways.
            from .models import Follow
            Follow.objects.filter(follower=request.user, following=target).delete()
            Follow.objects.filter(follower=target, following=request.user).delete()
        return Response({"username": target.username, "blocked": action != "unblock"})
