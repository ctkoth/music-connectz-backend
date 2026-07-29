"""OmviardZ API — the guided tour, one highlighted option at a time.

    GET  /api/omviardz/tour/          the whole tour for this member's track
    GET  /api/omviardz/step/<key>/    one step (for a deep link into the tour)
    POST /api/omviardz/answer/        answer a step -> Corey explains, tour advances
    POST /api/omviardz/skip/          bail out (remembered, so it stops re-opening)
    POST /api/omviardz/reset/         run it again from the top

Reading the tour is open to anyone: an unauthenticated visitor gets the full
spec including every option's written explanation, which is enough to render the
whole walkthrough client-side (and enough for Play Store screenshots before
anyone signs up). Answering requires a login — that's the endpoint that can
reach the model, and an open LLM endpoint is somebody else's bill.
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import tour as spec
from .models import progress_for
from .voice import explain


def _option_payload(opt):
    return {
        "key": opt["key"],
        # What the member types to pick it — matches Corey's '#1' convention in OCC.
        "reply": f"#{opt['key']}",
        "label": opt["label"],
        # The written answer travels with the option so a tap renders instantly
        # (and still renders with no network). A live reply replaces it.
        "explain": opt.get("explain", ""),
        "highlight": opt.get("highlight"),
        "route": opt.get("route"),
        "sets_track": opt.get("sets_track"),
    }


def _step_payload(step_key, index=None, total=None):
    step = spec.get_step(step_key)
    if not step:
        return None
    return {
        "key": step_key,
        "index": index,
        "total": total,
        "screen": step.get("screen"),
        "route": step.get("route"),
        "title": step.get("title"),
        "blurb": step.get("blurb"),
        "highlight": step.get("highlight"),
        "input": step.get("input", {"kind": "choice"}),
        "terminal": bool(step.get("terminal")),
        "options": [_option_payload(o) for o in step.get("options", [])],
    }


def _track_payload(track):
    keys = spec.track_steps(track)
    total = len(keys)
    return [_step_payload(k, index=i + 1, total=total) for i, k in enumerate(keys)]


class TourView(APIView):
    """GET the tour. ``?track=money`` previews a track you're not on."""

    permission_classes = [AllowAny]

    def get(self, request):
        prog = progress_for(request.user) if request.user.is_authenticated else None
        track = request.query_params.get("track") or (prog.track if prog else spec.TRACK_DEFAULT)
        if track not in spec.TRACKS:
            track = spec.TRACK_DEFAULT

        keys = spec.track_steps(track)
        # Resume where they were — unless that step isn't on this track (they
        # switched), in which case start it from the top.
        resume = prog.step_key if prog and prog.step_key in keys else keys[0]
        return Response(
            {
                "app": "omviardz",
                "name": "OmviardZ",
                "tagline": "Corey walks you through it — one highlighted option at a time.",
                "voice": "corey-gpt",
                "free": True,
                "track": track,
                "tracks": spec.TRACK_LABELS,
                "design": spec.DESIGN,
                "facts": spec.tier_facts(),
                "steps": _track_payload(track),
                "resume": resume,
                "progress": prog.as_dict() if prog else None,
            }
        )


class StepView(APIView):
    """GET one step — for deep-linking straight into a tour step."""

    permission_classes = [AllowAny]

    def get(self, request, key):
        prog = progress_for(request.user) if request.user.is_authenticated else None
        track = prog.track if prog else spec.TRACK_DEFAULT
        keys = spec.track_steps(track)
        payload = _step_payload(
            key,
            index=(keys.index(key) + 1) if key in keys else None,
            total=len(keys),
        )
        if not payload:
            return Response({"detail": "No such step."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"step": payload, "design": spec.DESIGN})


class AnswerView(APIView):
    """POST {step, choice, text} -> Corey explains the option, tour advances.

    ``choice`` is the single character the member replied with ("1" or "#1") or
    the option label the client sent when they tapped the row. ``text`` is free
    typing — it's answered on its own terms when the model is available, and
    politely handed back to the options when it isn't.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data or {}
        prog = progress_for(request.user)

        step_key = str(data.get("step") or prog.step_key or spec.first_step()).strip()
        step = spec.get_step(step_key)
        if not step:
            return Response({"detail": "No such step."}, status=status.HTTP_404_NOT_FOUND)

        choice = str(data.get("choice") or "").strip()
        text = str(data.get("text") or "")
        if not choice and not text.strip():
            return Response(
                {"detail": "Pick an option (choice) or say something (text)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        option = spec.get_option(step_key, choice) if choice else None
        if choice and not option:
            return Response(
                {
                    "detail": f"'{choice}' isn't an option on this step.",
                    "options": [f"#{o['key']}" for o in step.get("options", [])],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Step one is the branch: the answer picks the whole route from here.
        if option and option.get("sets_track") in spec.TRACKS:
            prog.track = option["sets_track"]

        reply, source = explain(
            step,
            option,
            text=text,
            track=prog.track,
            facts=spec.tier_facts(),
            slang=bool(data.get("slang")),
            suggest=bool(data.get("suggest")),
        )

        # Typing without picking keeps you on the step — you asked a question,
        # you didn't answer one. Only a real choice advances the tour.
        next_key = None
        if option:
            prog.record(step_key, choice=option["key"], label=option["label"], text=text)
            next_key = option.get("goto") or spec.next_step_key(prog.track, step_key)
            if next_key and not spec.get_step(next_key):
                next_key = None
            prog.step_key = next_key or step_key
            if not next_key or step.get("terminal"):
                prog.completed_at = prog.completed_at or timezone.now()
        prog.save()

        keys = spec.track_steps(prog.track)
        return Response(
            {
                "step": step_key,
                "choice": option["key"] if option else None,
                "explain": {
                    "text": reply,
                    "source": source,          # "corey-gpt" live, or "builtin"
                    "voice": "corey-gpt",
                    "cost_cents": 0,           # the tour is free, always
                },
                # What to spotlight now: the option's own control when they
                # picked one, otherwise stay on the step's target.
                "highlight": (option.get("highlight") if option else None) or step.get("highlight"),
                "route": (option.get("route") if option else None) or step.get("route"),
                "next": _step_payload(
                    next_key,
                    index=(keys.index(next_key) + 1) if next_key in keys else None,
                    total=len(keys),
                ) if next_key else None,
                "progress": prog.as_dict(),
            }
        )


class SkipView(APIView):
    """POST — stop the tour. Remembered so it doesn't ambush them next launch."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        prog = progress_for(request.user)
        prog.skipped = True
        prog.save(update_fields=["skipped", "updated_at"])
        return Response({"skipped": True, "progress": prog.as_dict()})


class ResetView(APIView):
    """POST — run it again from the top, answers cleared."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        prog = progress_for(request.user)
        prog.track = spec.TRACK_DEFAULT
        prog.step_key = spec.first_step()
        prog.done_keys = []
        prog.answers = {}
        prog.skipped = False
        prog.completed_at = None
        prog.save()
        return Response({"progress": prog.as_dict(), "resume": prog.step_key})
