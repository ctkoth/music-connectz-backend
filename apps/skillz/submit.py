"""Generic challenge submission for any gamified app.

Mounted by training_urlpatterns as  <app>/train/submit/  and  <app>/train/submissionz/.
Accepts work made in the app's in-app editor (ImageZ / SentenceZ / VideoZ) OR
imported from anywhere, scores it, and records a SkillZ attempt so it earns
XP / badges / leaderboard exactly like a drill.

Scoring: client-supplied score wins; else, if ANTHROPIC_API_KEY is set and we have
something gradable (an image URL, or text content), Claude rates it 0-100 against
the challenge prompt; else a "completed the work" baseline so the loop closes.
"""
import json
import re

import requests
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.agegate import YouthSafe

from .models import Drill, Submission
from .scoring import record_attempt

BASELINE = 72


def _ai_score(prompt, artifact_url="", content=""):
    key = settings.ANTHROPIC_API_KEY
    if not key:
        return None
    try:
        blocks = []
        if artifact_url.startswith("http") and re.search(r"\.(png|jpg|jpeg|webp|gif)(\?|$)", artifact_url, re.I):
            blocks.append({"type": "image", "source": {"type": "url", "url": artifact_url}})
        body_text = (f"You are an instructor scoring a student's submission for this challenge: "
                     f"\"{prompt}\". ")
        if content:
            body_text += f"Their work:\n\n{content[:4000]}\n\n"
        elif artifact_url and not blocks:
            body_text += f"Their work is at: {artifact_url}. "
        body_text += ("Reply with ONLY JSON: {\"score\": <0-100 int>, \"note\": \"<one sentence>\"}.")
        blocks.append({"type": "text", "text": body_text})
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=30,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          data=json.dumps({"model": "claude-sonnet-4-20250514",
                                           "max_tokens": 200,
                                           "messages": [{"role": "user", "content": blocks}]}))
        txt = "".join(b.get("text", "") for b in r.json().get("content", []))
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            data = json.loads(m.group(0))
            return max(0, min(100, int(data.get("score", BASELINE)))), data.get("note", "ai")
    except Exception:
        pass
    return None


class SubmitChallengeView(APIView):
    permission_classes = [YouthSafe]
    app_key = None

    def post(self, request):
        drill_id = request.data.get("drill")
        try:
            drill = Drill.objects.get(id=drill_id, track__app_key=self.app_key)
        except Drill.DoesNotExist:
            return Response({"detail": "challenge not found"}, status=status.HTTP_404_NOT_FOUND)

        source = request.data.get("source", "editor")
        artifact_url = request.data.get("artifact_url", "")
        content = request.data.get("content", "")
        notes = request.data.get("notes", "")
        client_score = request.data.get("score")

        basis = "self"
        if client_score is not None:
            try:
                score = max(0, min(100, int(client_score)))
            except (TypeError, ValueError):
                score, basis = BASELINE, "baseline"
        else:
            ai = _ai_score(drill.prompt or drill.title, artifact_url, content)
            if ai:
                score, basis = ai[0], "ai"
            else:
                score, basis = BASELINE, "baseline"

        result = record_attempt(request.user, drill, score)
        sub = Submission.objects.create(
            user=request.user, app_key=self.app_key, drill=drill, source=source,
            artifact_url=artifact_url, content=content, notes=notes,
            score=score, passed=result["passed"], xp_earned=result["xp_earned"])
        return Response({"submission_id": str(sub.id), "score": score,
                         "score_basis": basis, **result}, status=status.HTTP_201_CREATED)


class SubmissionListView(APIView):
    permission_classes = [YouthSafe]
    app_key = None

    def get(self, request):
        rows = Submission.objects.filter(user=request.user, app_key=self.app_key)
        drill = request.query_params.get("drill")
        if drill:
            rows = rows.filter(drill_id=drill)
        return Response([{
            "id": str(s.id), "drill": str(s.drill_id), "source": s.source,
            "artifact_url": s.artifact_url, "notes": s.notes, "score": s.score,
            "passed": s.passed, "xp_earned": s.xp_earned, "created_at": s.created_at,
        } for s in rows])
