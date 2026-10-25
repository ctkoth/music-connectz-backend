"""BodieZ AI coach endpoints — who may ask and what is billed live here; what the
model is told lives in bodiez_ai.py.

  GET    bodiez/ai/              price, what each read is, the member's kept reads
  POST   bodiez/ai/read/         {scope: session|routine|muscle, id}   the log read
  POST   bodiez/ai/form/         multipart video, exercise_id, confirm, note   the form check
  GET    bodiez/ai/<id>/         reopen one (?export=txt for the download door)
  DELETE bodiez/ai/<id>/         remove one

Billed only after a usable answer (`gemini._bill`, a free daily prompt first).
An unreadable video is not charged and leaves no row.
"""
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import bodiez_ai as ai
from .gemini import _bill
from .models import BodieZAIRead, BodieZExercise
from django.db.models import Q


def _row(r):
    return {"id": r.id, "kind": r.kind, "kind_label": r.get_kind_display(), "scope": r.scope,
            "ref": r.ref, "title": r.title, "exercise_id": r.exercise_id, "result": r.result,
            "charged_cents": r.charged_cents, "created_at": r.created_at.isoformat()}


def _state(user):
    price = ai.price_state(user)
    return {
        **price,
        "scopes": list(ai.SCOPES),
        "form_scores": ai.FORM_SCORES, "form_means": ai.FORM_MEANS, "form_rule": ai.FORM_RULE,
        "read_caveat": ai.READ_CAVEAT, "form_caveat": ai.FORM_CAVEAT,
        "read_note": ("Reads what you logged and says what's working, what to change and what your next "
                      "session should be. No new score — it shows your Thorough rating."),
        "form_note": ("Watches one video of one set and scores setup, range, control, path and bracing, "
                      "with cues for the next set. The video is used for this read and not stored."),
        "cost_note": "One price per read. A read that can't be done is never charged.",
    }


def _unaffordable(price):
    return Response({**price, "detail": f"A read costs {price['cost_cents']} 🏷️ and today's free prompts "
                                        "are spent."}, status=status.HTTP_402_PAYMENT_REQUIRED)


class BodieZAIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        reads = BodieZAIRead.objects.filter(user=request.user)[:ai.LIST_MAX]
        return Response({**_state(request.user), "reads": [_row(r) for r in reads],
                         "total": BodieZAIRead.objects.filter(user=request.user).count()})


class BodieZAIReadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def post(self, request):
        scope = str(request.data.get("scope") or "")
        if scope not in ai.SCOPES:
            return Response({"detail": "Pick a workout, a routine or a muscle to read."},
                            status=status.HTTP_400_BAD_REQUEST)
        raw = request.data.get("id")
        if scope == "muscle":
            ref = str(raw or "")[:12]
        else:
            try:
                ref = int(raw)
            except (TypeError, ValueError):
                return Response({"detail": "Which one? That id isn't a number."},
                                status=status.HTTP_400_BAD_REQUEST)
        price = ai.price_state(request.user)
        if not price["configured"]:
            return Response({**price, "detail": "The AI coach isn't switched on yet. " + ai.NOT_CHARGED},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not price["affordable"]:
            return _unaffordable(price)
        result, why, facts = ai.read_log(request.user, scope, ref)
        if result is None:
            code = status.HTTP_400_BAD_REQUEST if facts is None else status.HTTP_502_BAD_GATEWAY
            return Response({**price, "detail": f"{why} {ai.NOT_CHARGED}"}, status=code)
        charged = _bill(request.user, note=f"BodieZ log read · {facts['title']}", count_daily=True) or 0
        row = BodieZAIRead.objects.create(user=request.user, kind="read", scope=scope, ref=str(ref),
                                          title=facts["title"][:120], result=result, charged_cents=charged)
        return Response({**_row(row), "charged": charged > 0})


class BodieZAIFormView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        price = ai.price_state(request.user)
        if str(request.data.get("confirm", "")).strip().lower() not in ("true", "1", "yes"):
            return Response({**price, "detail": "Confirm the video is you, or someone who said you could "
                                                "send it."}, status=status.HTTP_400_BAD_REQUEST)
        video = request.FILES.get("video")
        if not video:
            return Response({**price, "detail": "Attach a video of one set."},
                            status=status.HTTP_400_BAD_REQUEST)
        if video.size > price["max_mb"] * 1024 * 1024:
            return Response({**price, "detail": f"That video is over {price['max_mb']}MB. Trim it to one set."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            ex = BodieZExercise.objects.filter(Q(created_by__isnull=True) | Q(created_by=request.user)) \
                .get(id=int(request.data.get("exercise_id")))
        except (TypeError, ValueError, BodieZExercise.DoesNotExist):
            return Response({**price, "detail": "Pick which lift the video shows."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not price["configured"]:
            return Response({**price, "detail": "The AI coach isn't switched on yet. " + ai.NOT_CHARGED},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not price["affordable"]:
            return _unaffordable(price)
        note = str(request.data.get("note") or "")[:ai.NOTE_MAX]
        result, why, unreadable = ai.check_form(request.user, video, ex, note)
        if result is None:
            return Response({**price, "detail": f"Couldn't check that — {why}. {ai.NOT_CHARGED}"},
                            status=status.HTTP_502_BAD_GATEWAY)
        if unreadable:
            return Response({**price, "unreadable": result["unreadable"], "charged": False,
                             "detail": f"{result['unreadable']} {ai.NOT_CHARGED}"})
        charged = _bill(request.user, note=f"BodieZ form check · {ex.name}", count_daily=True) or 0
        row = BodieZAIRead.objects.create(user=request.user, kind="form", title=f"Form · {ex.name}"[:120],
                                          exercise=ex, result=result, charged_cents=charged)
        return Response({**_row(row), "charged": charged > 0})


class BodieZAIDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, read_id):
        row = BodieZAIRead.objects.filter(user=request.user, id=read_id).first()
        if not row:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if request.query_params.get("export") == "txt":
            name = "".join(c if c.isalnum() else "-" for c in row.title.lower()).strip("-")[:60] or "read"
            return Response({"filename": f"bodiez-{name}.txt", "content_type": "text/plain",
                             "text": ai.export_text(row)})
        return Response(_row(row))

    def delete(self, request, read_id):
        n, _ = BodieZAIRead.objects.filter(user=request.user, id=read_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT if n else status.HTTP_404_NOT_FOUND)
