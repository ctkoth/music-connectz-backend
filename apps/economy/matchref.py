"""Inspiration (match a reference): the member's take, heard against a song they want to sound like.

A REFERENCE LISTEN (vocalcoach) reads somebody else's track and forgets it. This
is the other half, and the thing members actually asked for: send a famous
example AND your own take, and be told what separates them — in dimensions, in
EQ, in how-to, and in the lyrics.

Rules that hold it, each one the repo's existing rule applied here:

* **The reference is never kept.** Same as a reference listen: the upload is the
  request's own temporary file, never an `Upload` row, never in a quota, never
  served back, and any Files API copy is deleted. The member must have the right
  to analyse it (`REFERENCE_NOTICE` is shown beside the control).
* **Nothing is saved as the member's.** No TakeScore, no share card, no SkillZ
  XP, no skill rating: a gap to somebody else's record is not a measurement of
  the member, and a number the member could raise by copying a record would be
  the substance rule's failure case. `closeness` says how near the SOUND is; it
  never says the take is good or bad.
* **Lyrics: the direction, never the words.** The model is told to describe how
  the reference writes (rhyme habits, imagery, structure, point of view,
  density) and forbidden from quoting it. The member rewrites THEIR lines in
  Sentence ConnectZ with that direction. Reproducing a famous song's lyrics is
  not a feature.
* **EQ is by ear and says so.** Regions are server-owned (`EQ_REGIONS`) so an
  invented band becomes nothing instead of a label nobody wrote. The model
  cannot measure a spectrum; the screen says these are what was heard.
* **A failed run is not charged.** One standard AI price, stated on the control
  before it is pressed (`GET`), billed only after a usable parse.
"""
import logging

import requests
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import ai_cost
from .deadline import COACH_BUDGET_SECONDS, Deadline, Expired
from .gemini import _bill, _key, generate_content
from .instruments import profile_for_app, scores_for
from .models import can_afford_ai, daily_prompt_state
from . import vocalcoach as vc

logger = logging.getLogger(__name__)

# Where in the sound, in the words an engineer uses. Server-owned.
EQ_REGIONS = {
    "sub": ("Sub", "20-60 Hz"),
    "low": ("Low", "60-250 Hz"),
    "low_mid": ("Low-mid", "250-500 Hz"),
    "mid": ("Mid", "500 Hz-2 kHz"),
    "presence": ("Presence", "2-5 kHz"),
    "air": ("Air", "5-16 kHz"),
}
DIRECTIONS = ("more", "less", "close")
LABEL = "Inspiration"
NOTICE = ("Use music you have the right to analyse. The reference is read for this "
          "comparison only — it isn't posted, saved or counted toward your skills, and "
          "the file isn't kept. Your take isn't saved either unless you keep it elsewhere.")
EQ_NOTE = ("EQ notes are what the coach HEARD, not a measured spectrum — check them "
           "against your own meters and ears before you cut or boost.")
LYRIC_NOTE = ("This describes how the reference writes — never its words. Rewrite your "
              "own lines in Sentence ConnectZ with it.")


def _prompt(app_key, genre):
    p = profile_for_app(app_key)
    keys = list(scores_for(app_key))
    shape = ", ".join(f'"{k}": {{"take": <1-10>, "reference": <1-10>}}' for k in keys)
    regions = ", ".join(EQ_REGIONS)
    return f"""You are the Music ConnectZ {p['coach']}. You are given TWO recordings, \
in this order: first the MEMBER'S OWN TAKE, then a REFERENCE track they want to \
sound closer to. The reference is another artist's finished record; the take is \
a developing performance. Genre: {genre}.

Your job is the GAP, not a grade. Say what separates the take from the \
reference and what the member can do about it. Never tell the member their take \
is bad for not being a finished record, never call the reference perfect, and \
never invent detail you cannot hear. Production differences (room, mic, mix) \
belong in "eq" and "how_to", not in the performance readings.

If either file has no real performance (silence, talking, wrong file), set \
"unscorable" to one sentence saying which file and what you heard, and stop.

LYRICS: only if the recordings have words. Describe HOW the reference writes — \
rhyme habits, imagery, structure, point of view, line length, density — in your \
own words. NEVER quote, paraphrase line-by-line or reproduce any of the \
reference's lyrics. "lyric_direction" is an instruction the member's own writing \
can follow. If there are no words, leave it empty.

Return ONLY valid JSON, no markdown fence, in exactly this shape:
{{
  "unscorable": <null, or one sentence>,
  "closeness": <0-100 integer: how near the SOUND and approach of the take is to the reference>,
  "closeness_why": "<one sentence on what drives that number>",
  "scores": {{{shape}}},
  "summary": "<two sentences: the biggest gap and the easiest win>",
  "eq": [{{"region": "<one of: {regions}>", "direction": "<take needs: more | less | close>", "what": "<what you hear in each>", "how": "<the move: which control, which way, roughly how much>"}}, ...],
  "how_to": [{{"what": "<the gap>", "why": "<why the reference sounds the way it does>", "how": "<concrete steps>"}}, ...],
  "keep": "<what the take already does that the reference does too, or does better>",
  "lyric_direction": "<empty, or 2-4 sentences: how the reference writes, as an instruction for rewriting the member's own lines. No quotes from the reference.>"
}}"""


def _clean_eq(raw):
    out, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or len(out) == len(EQ_REGIONS):
            continue
        region = str(item.get("region", "")).strip().lower().replace("-", "_").replace(" ", "_")
        if region not in EQ_REGIONS or region in seen:
            continue
        direction = str(item.get("direction", "")).strip().lower()
        if direction not in DIRECTIONS:
            continue
        seen.add(region)
        label, hz = EQ_REGIONS[region]
        out.append({"region": region, "label": label, "hz": hz, "direction": direction,
                    "what": str(item.get("what", "")).strip()[:240],
                    "how": str(item.get("how", "")).strip()[:300]})
    return out


def _clean_scores(raw, keys):
    out = {}
    for k in keys:
        v = (raw or {}).get(k) if isinstance(raw, dict) else None
        if not isinstance(v, dict):
            continue
        t, r = vc._clamp(v.get("take")), vc._clamp(v.get("reference"))
        if t is not None and r is not None:
            out[k] = {"take": t, "reference": r}
    return out


def clean_reply(parsed, app_key):
    """The whitelist: anything the model adds beyond this never reaches a screen."""
    keys = list(scores_for(app_key))
    try:
        closeness = max(0, min(100, int(round(float(parsed.get("closeness"))))))
    except (TypeError, ValueError):
        closeness = None
    return {
        "closeness": closeness,
        "closeness_why": str(parsed.get("closeness_why", "")).strip()[:300],
        "scores": _clean_scores(parsed.get("scores"), keys),
        "summary": str(parsed.get("summary", "")).strip()[:500],
        "eq": _clean_eq(parsed.get("eq")),
        "how_to": vc.clean_practice(parsed.get("how_to")),
        "keep": str(parsed.get("keep", "")).strip()[:300],
        "lyric_direction": str(parsed.get("lyric_direction", "")).strip()[:600],
    }


class MatchReferenceView(APIView):
    """GET = the price and the rules before anything is sent; POST = the comparison."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    app_key = "singz"

    def get(self, request):
        profile = profile_for_app(self.app_key)
        cost = ai_cost("standard")
        _, _, daily_left = daily_prompt_state(request.user)
        return Response({
            "app_key": self.app_key, "label": profile["label"], "feature": LABEL,
            "cost_cents": cost, "free_today": daily_left > 0,
            "charged_on_failure": False, "saved": False,
            "scores": scores_for(self.app_key),
            "eq_regions": [{"key": k, "label": v[0], "hz": v[1]} for k, v in EQ_REGIONS.items()],
            "rates_lyrics": bool(profile.get("lyrics")),
            "notice": NOTICE, "eq_note": EQ_NOTE, "lyric_note": LYRIC_NOTE,
            "configured": bool(_key()),
        })

    def post(self, request):
        limited = vc.coach_rate_limit_check(request.user)
        if limited:
            return limited
        take, ref = request.FILES.get("take"), request.FILES.get("reference")
        if not take or not ref:
            return Response({"detail": "Send both: your take and the reference track."},
                            status=status.HTTP_400_BAD_REQUEST)
        kinds = []
        for f in (take, ref):
            ct = (getattr(f, "content_type", "") or "").lower()
            if not ct.startswith(("audio/", "video/")):
                return Response({"detail": "Both files must be audio or video."},
                                status=status.HTTP_400_BAD_REQUEST)
            if not vc.gemini_mime(ct):
                return Response({"detail": f"The coach can't read {ct}. Use m4a, mp3, wav, ogg or mp4."},
                                status=status.HTTP_400_BAD_REQUEST)
            kinds.append(vc.gemini_mime(ct))
        cap_mb, cap_is_tier = vc.cap_for(request.user)
        for f in (take, ref):
            if f.size > cap_mb * 1024 * 1024:
                return Response({"detail": f"That file is {f.size / (1024 * 1024):.0f}MB. "
                                           + vc.cap_why(cap_mb, cap_is_tier), "max_mb": cap_mb},
                                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            if f.size == 0:
                return Response({"detail": "One of those files is empty."},
                                status=status.HTTP_400_BAD_REQUEST)
        if not _key():
            return Response({"detail": "The coach isn't configured — set GEMINI_API_KEY on the backend."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        cost = ai_cost("standard")
        _, _, daily_left = daily_prompt_state(request.user)
        if cost and not daily_left and not can_afford_ai(request.user, cost):
            return Response({"detail": "Not enough PromptZ / balance for a comparison.", "cost_cents": cost},
                            status=status.HTTP_402_PAYMENT_REQUIRED)

        genre = str(request.data.get("genre") or "unspecified")[:60]
        deadline = Deadline(COACH_BUDGET_SECONDS)
        cleanups = []
        try:
            parts = []
            for f, mime in zip((take, ref), kinds):
                part, cleanup, why = vc._media_part(f, mime, vc._size_of(f), deadline=deadline)
                if cleanup:
                    cleanups.append(cleanup)
                if why:
                    return Response({"detail": f"The coach couldn't take that one — {why}. Nothing was charged."},
                                    status=status.HTTP_502_BAD_GATEWAY)
                parts.append(part)
            body = {"contents": [{"parts": [{"text": _prompt(self.app_key, genre)},
                                            {"text": "MEMBER'S TAKE:"}, parts[0],
                                            {"text": "REFERENCE TRACK:"}, parts[1]]}],
                    "generationConfig": {"temperature": vc.COACH_TEMPERATURE}}
            deadline.check("the files were still uploading when the time ran out")
            resp, _tried = generate_content(
                "text", body, key=_key(),
                timeout=deadline.remaining(cap=300 if cleanups else 90),
                env_vars=("GEMINI_AUDIO_MODEL",), label=f"{self.app_key} match")
        except Expired as e:
            return Response({"detail": f"The comparison is taking longer than it should — {e.message}. "
                                       "Nothing was charged.", "timed_out": True},
                            status=status.HTTP_504_GATEWAY_TIMEOUT)
        except requests.RequestException:
            logger.exception("%s match: could not reach Gemini", self.app_key)
            return Response({"detail": "Couldn't reach the coach. Nothing was charged — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            logger.exception("%s match: files could not be read", self.app_key)
            return Response({"detail": "The coach couldn't read those files. Nothing was charged."},
                            status=status.HTTP_400_BAD_REQUEST)
        finally:
            for c in cleanups:
                try:
                    c()
                except Exception:  # pragma: no cover - tidiness, never a failure
                    logger.exception("%s match: cleanup failed", self.app_key)

        if resp.status_code != 200:
            logger.error("%s match: Gemini %s — %s", self.app_key, resp.status_code, resp.text[:300])
            return Response({"detail": "The coach couldn't read those files right now. Nothing was charged."},
                            status=status.HTTP_502_BAD_GATEWAY)
        try:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError):
            return Response({"detail": "The coach's reply didn't come back readable. Nothing was charged."},
                            status=status.HTTP_502_BAD_GATEWAY)
        parsed = vc._parse(text)
        if parsed and str(parsed.get("unscorable") or "").strip():
            return Response({"unscorable": str(parsed["unscorable"]).strip()[:400], "reference": True,
                             "match": True, "cost_cents": 0, "saved": False})
        out = clean_reply(parsed or {}, self.app_key)
        if not parsed or out["closeness"] is None or not (out["eq"] or out["how_to"] or out["summary"]):
            return Response({"detail": "The coach's reply didn't come back readable. Nothing was charged."},
                            status=status.HTTP_502_BAD_GATEWAY)
        charged = _bill(request.user, note=f"{profile_for_app(self.app_key)['label']} Inspiration — AI",
                        count_daily=True)
        return Response({**out, "match": True, "reference": True, "saved": False, "feature": LABEL,
                         "cost_cents": charged, "eq_note": EQ_NOTE, "lyric_note": LYRIC_NOTE,
                         "genre": genre})
