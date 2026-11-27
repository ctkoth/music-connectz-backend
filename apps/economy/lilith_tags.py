"""Lilith tags: one more door on a task.

A task already carries one place it gets done (`app_key`/`target`, the
cross-pollination rule applied to a to-do list). Some work happens in several
places: record the take in SingZ, post it in PostZ, enter it in BattleZ. A tag
is one more door on the same task.

What holds it:

- **Owner-only, with no visibility setting.** The task's own rule: these are the
  member's notes about their own work. A "shared" or "public" option would
  promise a reader that nothing in the app shows.
- **Pays nothing and moves nothing.** No coin, no energy, no XP, no rating. A
  tag is a pointer; a pointer that paid would be a second way to be paid for one
  task.
- **The target must be something the screen can find.** The client writes it
  into a `[data-tour="…"]` selector, so a quote, bracket or space would make the
  lookup throw. The charset is the one the anchors already use (`singz:coach`,
  `lilith:logbook`).
- **Ten a task.** A short list of doors, not a second to-do list.

The server checks the SHAPE of the app key. The list of real tabs lives in the
frontend (src/tabList.js, guarded against App.jsx), and the picker only offers
those, so a tag can only be made toward a tab that exists.
"""
import re

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LilithTag, LilithTask

TAGS_PER_TASK = 10

# fullmatch, not match: `$` would accept a trailing newline.
_APP_KEY = re.compile(r"[a-z][a-z0-9_]{1,31}")
_TARGET = re.compile(r"[A-Za-z0-9_:.\-]{1,64}")


def clean_tag(d):
    """(app_key, target, error). A tag names a control, so both are required."""
    app = str(d.get("to_app_key") or "").strip()
    target = str(d.get("to_target") or "").strip()
    if not _APP_KEY.fullmatch(app):
        return None, None, "Pick the app this goes to."
    if not _TARGET.fullmatch(target):
        return None, None, ("The control can use letters, numbers, '_', ':', '.' and '-', "
                            "up to 64 characters.")
    return app, target, None


def _own_task(request, task_id):
    return LilithTask.objects.filter(pk=task_id, user=request.user).first()


def _tag_dict(t):
    return {"id": t.id, "to_app_key": t.to_app_key, "to_target": t.to_target,
            "created_at": t.created_at}


class LilithTagListView(APIView):
    """GET /api/economy/lilith/tags/?task_id=N — the tags on one of my tasks, oldest first.

    A bare list, not an envelope: the client renders it directly.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            task_id = int(request.query_params.get("task_id") or "")
        except ValueError:
            return Response({"detail": "Pick a task."}, status=400)
        if not _own_task(request, task_id):
            # The same answer for a task that does not exist and one that is someone else's.
            return Response({"detail": "No such task."}, status=404)
        tags = LilithTag.objects.filter(user=request.user, task_id=task_id)
        return Response([_tag_dict(t) for t in tags])


class LilithTagCreateView(APIView):
    """POST /api/economy/lilith/tag/ — {task_id, to_app_key, to_target}, on one of my tasks."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data if hasattr(request.data, "get") else {}
        try:
            task_id = int(d.get("task_id"))
        except (TypeError, ValueError):
            return Response({"detail": "Pick a task."}, status=400)
        task = _own_task(request, task_id)
        if not task:
            return Response({"detail": "No such task."}, status=404)
        app, target, err = clean_tag(d)
        if err:
            return Response({"detail": err}, status=400)
        if LilithTag.objects.filter(task=task).count() >= TAGS_PER_TASK:
            return Response({"detail": f"A task holds {TAGS_PER_TASK} tags. "
                                       "Remove one to add another."}, status=400)
        try:
            with transaction.atomic():
                tag = LilithTag.objects.create(user=request.user, task=task,
                                               to_app_key=app, to_target=target)
        except IntegrityError:
            return Response({"detail": "That tag is already on this task."}, status=400)
        return Response(_tag_dict(tag), status=status.HTTP_201_CREATED)


class LilithTagDetailView(APIView):
    """DELETE /api/economy/lilith/tag/<id>/ — remove one of my tags.

    Answers JSON, not an empty 204: the client refreshes its list only when it
    gets a body back, and an empty answer reads as "nothing happened".
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, tag_id):
        tag = LilithTag.objects.filter(pk=tag_id, user=request.user).first()
        if not tag:
            return Response({"detail": "No such tag."}, status=404)
        tag.delete()
        return Response({"deleted": tag_id})
