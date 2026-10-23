"""The writing coach: written lyrics scored like a performed take.

A rap or sung take could have its lyrics scored, but only while performed — nothing
could score words on a page. This reads the text itself on the SAME five lyric
dimensions the voice coach uses (instruments.LYRIC_SCORE), so a written verse and a
performed one are measured on one scale.

Same rules as the coach: one number per dimension with its reason and the fix, the
scale anchored (5-7 ordinary, never a reference record), the overall not the weakest
facet, priced before the press and not charged for an unreadable answer, XP for
doing it. Any dimension under FIX_BELOW (Corey's 6) is handed to the Sentence
ConnectZ fixer for that dimension, WITH the member's words — this coach has them.
"""
import json
import logging

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import ai_cost
from .gemini import _bill, _key, generate_content
from .instruments import LYRIC_SCORE
from .models import WriteScore, can_afford_ai, daily_prompt_covers, daily_prompt_state

logger = logging.getLogger(__name__)

FIX_BELOW = 6
MAX_CHARS = 6000
# Lyric dimension -> the Sentence ConnectZ fixer that writes for it.
FIXER_FOR = {"rhyme": "rhymes", "punchlines": "punchlines", "story": "storybeats",
             "imagery": "imagery", "freshness": "freshangles"}


def prompt(text):
    dims = "\n".join(f'- "{k}": {v}' for k, v in LYRIC_SCORE.items())
    return (
        "You are a lyric-writing coach for a developing songwriter or rapper. Score the WRITTEN "
        "lyrics below — the words on the page, not a performance.\n"
        f"Dimensions:\n{dims}\n"
        "THE SCALE, for every number: 1-2 not yet working, 3-4 a real attempt mostly getting away, "
        "5-7 solid and ordinary (6 is normal for a developing writer), 8-9 strong, 10 exceptional. "
        "Never compare to famous released songs.\n"
        "The overall is NOT an average and never the weakest facet: weigh it the way a listener "
        "would, where a real strength can carry one fixable weak area. Writing that is weak "
        "throughout still scores low.\n"
        "Answer ONLY with JSON: {\"score\": <overall 1-10 number>, \"verdict\": <one sentence>, "
        "\"scores\": {<each key above>: <1-10 integer>}, \"reasons\": {<each key>: <one sentence: why that "
        "number, quoting a line where you can>}, \"fixes\": {<each key>: <one sentence: the one change>}, "
        "\"strengths\": [<up to 2 short strings>]}. If there are no lyrics to read, answer {\"score\": null}.\n\n"
        f"LYRICS:\n{text}"
    )


def parse(raw):
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        d = json.loads(raw[start:end])
    except Exception:
        return None
    if d.get("score") is None:
        return None
    scores = {}
    for k in LYRIC_SCORE:
        try:
            scores[k] = max(1, min(10, int(round(float((d.get("scores") or {}).get(k))))))
        except (TypeError, ValueError):
            return None                      # a dimension missing is an unreadable answer
    try:
        overall = max(1.0, min(10.0, float(d["score"])))
    except (TypeError, ValueError):
        return None
    reasons, fixes = d.get("reasons") or {}, d.get("fixes") or {}
    return {
        "score": round(overall), "score_exact": round(overall, 1),
        "verdict": str(d.get("verdict") or "")[:300],
        "strengths": [str(x)[:140] for x in (d.get("strengths") or [])][:2],
        "dimensions": [{"key": k, "label": LYRIC_SCORE[k], "score": scores[k],
                        "why": str(reasons.get(k) or "")[:300], "fix": str(fixes.get(k) or "")[:300],
                        **({"fixer": FIXER_FOR[k]} if scores[k] < FIX_BELOW and k in FIXER_FOR else {})}
                       for k in LYRIC_SCORE],
    }


def price_for(user):
    cost = ai_cost("standard")
    _, allowance, left = daily_prompt_state(user)
    return {"cost_cents": cost, "free_today": bool(left > 0 and daily_prompt_covers(cost)),
            "daily_remaining": left, "affordable": can_afford_ai(user, cost) or left > 0,
            "configured": bool(_key()), "max_chars": MAX_CHARS, "fix_below": FIX_BELOW,
            "dimensions": LYRIC_SCORE,
            "caveat": "One read of the words on the page. How they land performed is the voice coach's job."}


class WriteCoachView(APIView):
    """GET /api/economy/writecoach/ — price, limits and the dimensions; history.
    POST {text, title?} — score it."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = WriteScore.objects.filter(user=request.user)[:20]
        return Response({**price_for(request.user),
                         "history": [{"id": r.id, "title": r.title, "overall": r.overall, "scores": r.scores,
                                      "created_at": r.created_at.isoformat()} for r in rows]})

    def post(self, request):
        from apps.skillz.models import TrainingProfile
        from .vocalcoach import coach_xp_base
        text = str(request.data.get("text") or "").strip()
        if not text:
            return Response({"detail": "Write or paste some lyrics first."}, status=status.HTTP_400_BAD_REQUEST)
        if len(text) > MAX_CHARS:
            return Response({"detail": f"Up to {MAX_CHARS:,} characters in one read — score a verse at a time."},
                            status=status.HTTP_400_BAD_REQUEST)
        key = _key()
        if not key:
            return Response({"detail": "The writing coach isn't switched on yet."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        p = price_for(request.user)
        if not p["affordable"]:
            return Response({"detail": "Not enough PromptZ or balance for this one.", "cost_cents": p["cost_cents"]},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        body = {"contents": [{"parts": [{"text": prompt(text)}]}],
                "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"}}
        try:
            resp, _ = generate_content("text", body, key=key, timeout=60, label="WriteCoach")
        except requests.RequestException:
            return Response({"detail": "Couldn't reach the coach. Nothing was charged — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        raw = ""
        if resp is not None and resp.status_code == 200:
            try:
                raw = "".join(str(x.get("text", "")) for x in resp.json()["candidates"][0]["content"]["parts"])
            except Exception:
                raw = ""
        out = parse(raw)
        if out is None:
            return Response({"detail": "The coach couldn't read lyrics in that. Nothing was charged."},
                            status=status.HTTP_502_BAD_GATEWAY)
        charged = _bill(request.user, "WriteCoach · lyrics", count_daily=True)
        if charged is None:
            return Response({"detail": "Not enough PromptZ or balance for this one.", "cost_cents": p["cost_cents"]},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        row = WriteScore.objects.create(
            user=request.user, title=str(request.data.get("title") or "")[:120], text=text,
            overall=out["score_exact"], scores={d["key"]: d["score"] for d in out["dimensions"]},
            read={k: out[k] for k in ("verdict", "strengths", "dimensions")})
        try:
            prof, _ = TrainingProfile.objects.get_or_create(user=request.user, app_key="sentencez")
            out["xp_awarded"] = prof.add_xp(coach_xp_base(out["score_exact"]))
            prof.save(update_fields=["xp"])
        except Exception:                                  # pragma: no cover
            logger.exception("WriteCoach XP failed")
        return Response({**out, "id": row.id, "charged_cents": charged, "fix_below": FIX_BELOW},
                        status=status.HTTP_201_CREATED)
