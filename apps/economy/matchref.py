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
* **Either side can already be on the platform.** The take: a file, one of the member's
  own posts (a RapZ submission, say), a FileZ upload from whichever app made it, or a
  journal recording. The reference: a file, ANY post the member is allowed to view (the
  famous example, or another member's track), or one of their own uploads. Every one of
  those goes through the coach's own lookups (`_take_from_post`, `_take_from_upload`,
  `_take_from_journal`), so view rights, ownership and size-from-the-row are the rules the
  coach already enforces and not a second copy of them. Nothing is ever written onto
  someone else's post, and a post's file is read for this comparison only.
* **Using a post costs what coaching a post costs** (`vocalcoach.coach_post_energy`, ⚡) — ONCE,
  however many of the two sides are posts. Stated on the control before it is pressed,
  checked before the model runs, spent only after a usable result. A file, a FileZ upload
  or a journal entry costs no ⚡.
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
from .models import can_afford_ai, daily_prompt_state, mark_upload_missing, spend_energy, wallet_for
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
POST_NOTE = ("Using a post as either side costs {cost} ⚡ once. Nothing is written on the post "
             "and its file is read for this comparison only.")
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


class _Slot:
    """One side of the comparison, resolved to something the coach can read.

    `file` is open for reading when `stored` (closed by `close()`); `post` is set only when
    the side came from a post, because that is what costs ⚡ and what the result names.
    """
    def __init__(self, file, ctype, post=None, stored=None):
        self.file, self.ctype, self.post, self.stored = file, ctype, post, stored
        self.mime = vc.gemini_mime(ctype)

    @property
    def uploaded(self):
        return self.stored is None and self.post is None

    @property
    def title(self):
        if self.post is not None:
            return self.post.title
        return (self.stored or {}).get("title") or ""

    def opened(self):
        if not self.uploaded:
            self.file.open("rb")

    def close(self):
        if not self.uploaded:
            try:
                self.file.close()
            except Exception:                            # pragma: no cover
                pass

    def describe(self):
        """What the screen is told this side was. A post names its author — it is theirs and
        the member can already see it; nothing else about it is sent."""
        if self.post is not None:
            return {"kind": "post", "id": self.post.id, "title": self.post.title,
                    "author": self.post.author.username}
        if self.stored is not None:
            return {"kind": self.stored["kind"], "id": self.stored["id"], "title": self.stored.get("title", "")}
        return {"kind": "file", "title": getattr(self.file, "name", "") or ""}


class _Fields:
    """The coach's lookups read plain `post_id` / `upload_id` / `journal_id`. Inspiration has TWO
    slots, so each slot's prefixed fields (`take_post_id`, `reference_post_id`…) are presented to
    those same lookups rather than copying their checks."""
    NAMES = ("post_id", "upload_id", "journal_id")

    def __init__(self, request, prefix):
        self.user = request.user
        self.data = {n: request.data.get(f"{prefix}{n}") for n in self.NAMES}


def _resolve(request, name, doors):
    """(slot, error_response) for 'take' or 'reference'. `doors` is the ids this side accepts."""
    f = request.FILES.get(name)
    if f:
        return _Slot(f, (getattr(f, "content_type", "") or "").lower()), None
    given = [d for d in doors if request.data.get(f"{name}_{d}") not in (None, "")]
    if not given:
        return None, None
    coach = vc.SingZCoachView()
    fields = _Fields(request, f"{name}_")
    if "post_id" in given:
        post, f, ctype, err = coach._take_from_post(fields)
        return (None, err) if err else (_Slot(f, ctype, post=post), None)
    if "upload_id" in given:
        stored, f, ctype, err = coach._take_from_upload(fields)
        return (None, err) if err else (_Slot(f, ctype, stored=stored), None)
    stored, f, ctype, err = coach._take_from_journal(fields)
    return (None, err) if err else (_Slot(f, ctype, stored=stored), None)


TAKE_DOORS = ("post_id", "upload_id", "journal_id")
REFERENCE_DOORS = ("post_id", "upload_id")      # a diary page is not "another artist's finished record"


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
            # Said before the button: a post on either side costs this once; the rest cost none.
            "post_energy_cost": vc.coach_post_energy(request.user),
            "post_note": POST_NOTE.format(cost=vc.coach_post_energy(request.user)),
            "take_sources": ["file", "post", "upload", "journal"],
            "reference_sources": ["file", "post", "upload"],
        })

    def post(self, request):
        limited = vc.coach_rate_limit_check(request.user)
        if limited:
            return limited
        take, err = _resolve(request, "take", TAKE_DOORS)
        if err:
            return err
        ref, err = _resolve(request, "reference", REFERENCE_DOORS)
        if err:
            return err
        if not take or not ref:
            return Response({"detail": "Send both: your take and the reference track."},
                            status=status.HTTP_400_BAD_REQUEST)
        if take.post is not None and ref.post is not None and take.post.id == ref.post.id:
            return Response({"detail": "That's the same post on both sides — pick a different reference."},
                            status=status.HTTP_400_BAD_REQUEST)
        for side in (take, ref):
            if not side.ctype.startswith(("audio/", "video/")):
                return Response({"detail": "Both must be audio or video."},
                                status=status.HTTP_400_BAD_REQUEST)
            if not side.mime:
                return Response({"detail": f"The coach can't read {side.ctype}. Use m4a, mp3, wav, ogg or mp4."},
                                status=status.HTTP_400_BAD_REQUEST)
        cap_mb, cap_is_tier = vc.cap_for(request.user)
        for side in (take, ref):
            # Only an uploaded file is measured here. A stored one was measured from its
            # database row by the lookup (a FieldFile's .size is a storage call that raises
            # when the file has gone), and an empty one is caught once it is opened below.
            if side.uploaded:
                if side.file.size > cap_mb * 1024 * 1024:
                    return Response({"detail": f"That file is {side.file.size / (1024 * 1024):.0f}MB. "
                                               + vc.cap_why(cap_mb, cap_is_tier), "max_mb": cap_mb},
                                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
                if side.file.size == 0:
                    return Response({"detail": "One of those files is empty."},
                                    status=status.HTTP_400_BAD_REQUEST)
        # A post on either side costs ⚡ — once. Checked BEFORE the model runs so nobody waits
        # on a comparison they cannot pay for; spent only after a usable result.
        post_sides = [x for x in (take, ref) if x.post is not None]
        energy_cost = vc.coach_post_energy(request.user) if post_sides else 0
        if energy_cost:
            have = max(0, wallet_for(request.user).energy or 0)
            if have < energy_cost:
                return Response({
                    "detail": f"Using a post costs {energy_cost} ⚡ and you have {have}. Nothing was run "
                              "or charged. A file or a FileZ upload on both sides costs no ⚡.",
                    "insufficient": True, "resource": "energy",
                    "cost": {"resource": "energy", "amount": energy_cost},
                    "energy_needed": energy_cost, "energy_available": have,
                    "energy_short": energy_cost - have,
                }, status=status.HTTP_402_PAYMENT_REQUIRED)
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
            for side in (take, ref):
                side.opened()
                size = vc._size_of(side.file)
                if size == 0:
                    return Response({"detail": f"\"{side.title or 'One of those files'}\" is empty. "
                                               "Nothing was charged."}, status=status.HTTP_400_BAD_REQUEST)
                part, cleanup, why = vc._media_part(side.file, side.mime, size, deadline=deadline)
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
            # A stored side whose file has gone from storage: say so as a fact about the
            # FILE (410), write it down for the next member, and charge nothing.
            gone = [x for x in (take, ref) if not x.uploaded]
            for x in gone:
                mark_upload_missing(getattr(x.file, "instance", None))
            if gone:
                where = ", ".join(f'"{x.title}"' for x in gone if x.title) or "one of those"
                return Response({"detail": f"The recording on {where} isn't on the server any more, so "
                                           "there's nothing to compare. Nothing was charged.",
                                 "take_missing": True}, status=status.HTTP_410_GONE)
            return Response({"detail": "The coach couldn't read those files. Nothing was charged."},
                            status=status.HTTP_400_BAD_REQUEST)
        finally:
            take.close()
            ref.close()
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
        if energy_cost:
            spend_energy(request.user, energy_cost,
                         f"Inspiration with a post — {(post_sides[0].title or 'post')[:50]}",
                         app_key=self.app_key, target=f"post:{post_sides[0].post.id}")
        return Response({**out, "match": True, "reference": True, "saved": False, "feature": LABEL,
                         "cost_cents": charged, "energy_cost": energy_cost,
                         "eq_note": EQ_NOTE, "lyric_note": LYRIC_NOTE, "genre": genre,
                         "sources": {"take": take.describe(), "reference": ref.describe()}})
