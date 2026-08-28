"""SingZ Boss Take — record a take, get it scored and coached.

The blueprint's Boss Take ("user records one scored final take, exercise pass,
or song section") plus the AI Vocal Coach ("deeper feedback on why notes,
transitions, tone, or breath control are weak").

Open to every tier, priced per take. The blueprint filed the coach under StatZ
Gated Features; that was reconsidered once the no-account trial door shipped,
because gating members harder than strangers put the ladder upside down. A tier
now buys FREQUENCY — 1 / 5 / 10 free takes a day — not permission.

A take is sent to Gemini as inline audio along with the member's genre, target
range and difficulty, and comes back as a score out of 10 plus advice in the
Music ConnectZ voice — direct, specific, no hedging.

Only the sub-scores a single take can honestly support are returned. The
blueprint's Consistency, Voice Health and Goal Match scores need history or
self-reported condition, so they are deliberately absent rather than invented
from one clip.
"""
import base64
import json
import logging
import os
import re

import requests
from django.conf import settings
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import ai_cost
from .instruments import DIFFICULTIES, profile_for_app, prompt_for
from .gemini import _bill, _key, generate_content
from .models import (
    PROMPT_ALLOWANCE,
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    can_afford_ai,
    daily_prompt_state,
    membership_for,
    wallet_for,
)

logger = logging.getLogger(__name__)

# The take rides to Gemini as inline_data — base64 inside the request body —
# and that path caps the WHOLE request at 20MB. Base64 inflates by 4/3, so the
# real ceiling on the file is about 15MB, not 25.
#
# 25 was the stated limit and it could not be honoured: a 22MB take passed our
# own check, blew Gemini's, and came back as "The coach couldn't process that
# take" — a limit the app advertised and then refused, with a message that
# blamed the take. 14 leaves headroom for the prompt and the JSON envelope.
#
# It is enough for what a Boss Take is: ~15 minutes of 128kbps audio, or about
# a minute of video at the bitrate the recorder asks for. Anything longer than
# that is not one take.
INLINE_MAX_MB = 14

# What the coach will actually take now. The 20MB request cap belongs to the
# INLINE path, not to the coach — Google's Files API accepts 2GB per file, free,
# and generateContent reads it by URI. So the transport stopped being the thing
# that decides what can be coached, and this is a judgement about what one take
# IS rather than what the wire can carry.
#
# 200MB is roughly three hours of 128kbps audio, or a long video take. A Boss
# Take is one take; anything past this is a session, and scoring a session as a
# take produces a number about the wrong thing. Env-overridable because that
# judgement may want moving without a deploy.
MAX_MB = int(os.environ.get("COACH_MAX_MB", "200"))

# What Gemini will actually accept as inline media. Anything outside these two
# sets is refused by the API, not by us — and the refusal arrives as a plain
# non-200 that we used to surface as "The coach couldn't process that take",
# which blamed the performance for a container problem.
_GEMINI_AUDIO = {"audio/wav", "audio/mp3", "audio/mpeg", "audio/aiff",
                 "audio/aac", "audio/ogg", "audio/flac"}
_GEMINI_VIDEO = {"video/mp4", "video/mpeg", "video/mov", "video/quicktime",
                 "video/avi", "video/x-flv", "video/mpg", "video/webm",
                 "video/wmv", "video/3gpp"}

# Browsers record into containers Gemini names under `video/` even when the
# recording is audio-only. Same bytes, same container — only the label differs,
# so relabel rather than refuse a take we can obviously send.
_RELABEL = {
    "audio/webm": "video/webm",        # Chrome / Edge / Android default
    "audio/x-matroska": "video/webm",
    "audio/mp4": "video/mp4",          # Safari / iOS default
    "audio/x-m4a": "video/mp4",
    "audio/m4a": "video/mp4",
    "audio/3gpp": "video/3gpp",
    "audio/vorbis": "audio/ogg",
    "audio/opus": "audio/ogg",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/x-aiff": "audio/aiff",
}


def gemini_mime(content_type):
    """The mime type to hand Gemini for this upload, or None if it can't take it.

    Two things go wrong between a browser and this call, and both were live:

    1. `MediaRecorder.mimeType` is a FULL media type — Chrome hands back
       `audio/webm;codecs=opus`. The parameter rides through the Blob, the
       multipart upload and Django untouched, and Gemini rejects the whole
       request over it. Strip to the bare type.
    2. `audio/webm` is not on Gemini's audio list at all, though `video/webm`
       is. A browser-recorded take was therefore unscoreable on the two
       biggest browsers — which is exactly the "couldn't process that take"
       people were seeing on a perfectly good performance.
    """
    base = (content_type or "").split(";")[0].strip().lower()
    base = _RELABEL.get(base, base)
    return base if base in _GEMINI_AUDIO or base in _GEMINI_VIDEO else None


def cap_for(user):
    """(megabytes, is_their_tier_limit) — the take ceiling for THIS member.

    Two ceilings meet here and the smaller one wins:

    * MAX_MB, which is now a judgement about what one take is;
    * the member's own per-file upload limit, which is what their tier lets
      them put on the platform at all.

    While MAX_MB was 14 the coach's was always the smaller, so the app could
    say "this isn't your tier's limit" and be right for everybody — which is
    why `max_mb_is_tier_limit` has been a hardcoded False. At 200MB that stops
    being true: a Free member can only upload 100MB, so THEIR ceiling is their
    tier's, and telling them otherwise would be the app stating a size it can't
    honour with a sentence explicitly denying whose limit it is.

    So it is computed, and the flag finally does the job it was invented for.
    """
    from .catalog import limits_for
    from .models import membership_for

    try:
        tier_mb = int(limits_for(membership_for(user).tier)["upload_mb"])
    except Exception:                                    # pragma: no cover
        return MAX_MB, False
    if tier_mb < MAX_MB:
        return tier_mb, True
    return MAX_MB, False


def cap_why(mb, is_tier):
    """Whose ceiling it is, said in the member's terms."""
    if is_tier:
        return (f"Your tier uploads up to {mb}MB a file, and that's what the coach "
                "can be given. A tier up raises it.")
    return (f"A Boss Take can be up to {mb}MB — around three hours of audio. Past "
            "that it's a session rather than a take, and a score about a whole "
            "session is a number about the wrong thing. It isn't your tier's "
            "upload limit.")


def _size_of(f):
    """How many bytes this take is, without asking storage.

    Seek-to-end works on an uploaded file and an opened stored one alike, and
    unlike `FieldFile.size` it does not make a metadata call that raises when
    the file has gone missing.
    """
    try:
        here = f.tell()
        f.seek(0, 2)
        n = f.tell()
        f.seek(here)
        return n
    except Exception:                                    # pragma: no cover
        return int(getattr(f, "size", 0) or 0)


def _media_part(f, mime, size):
    """The generateContent part carrying the take, and a cleanup callback.

    Small takes go INLINE, base64 in the request body: one round trip, nothing
    to tidy afterwards, and the path with a year of production behind it.

    Bigger ones are uploaded first and referenced by URI, which is what lifts
    the ceiling from 14MB to gigabytes. Returns (part, cleanup, error) with
    exactly one of part/error set.
    """
    if size <= INLINE_MAX_MB * 1024 * 1024:
        return ({"inline_data": {"mime_type": mime,
                                 "data": base64.b64encode(f.read()).decode()}},
                None, None)

    from . import gemini_files
    up, why = gemini_files.upload(f, mime, size, display_name="boss-take")
    if why:
        return None, None, why
    ready, why = gemini_files.wait_active(up)
    if not ready:
        gemini_files.delete(up)
        return None, None, why
    return (gemini_files.part_for(up, mime),
            lambda: gemini_files.delete(up), None)


def _parse(text):
    """Pull the JSON object out of a model reply that may be fenced."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _clamp(v, lo=1, hi=10):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return None


def score_take(app_key, f, content_type, *, genre, target, difficulty, style=None):
    """Send one take to the model. Returns (payload, error) — exactly one is None.

    Shared by the member coach and the no-account trial, deliberately: a trial
    that grades on an easier rubric is a lie about the product, and the first
    real take would contradict it.
    """
    key = _key()
    if not key:
        return None, (
            {"detail": "The vocal coach isn't configured — set GEMINI_API_KEY on the backend."},
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    difficulty = str(difficulty or "").lower()
    prompt = prompt_for(
        app_key,
        genre=str(genre or "unspecified")[:60],
        target=str(target or "unspecified")[:60],
        difficulty=difficulty if difficulty in DIFFICULTIES else "builder",
        style=str(style or "")[:60] or None,
    )
    # Normalise BEFORE the call. An unsupported container is a refusal we can
    # give instantly and explain, rather than a round trip that comes back as a
    # generic failure the member reads as "my take was bad".
    mime = gemini_mime(content_type)
    if not mime:
        return None, (
            {"detail": f"The coach can't read {content_type or 'that format'}. "
                       "Record in the app, or attach an m4a, mp3, wav, ogg or mp4.",
             "content_type": content_type},
            status.HTTP_400_BAD_REQUEST,
        )

    unreadable = ({"detail": "The coach couldn't process that take."}, status.HTTP_502_BAD_GATEWAY)

    # How the take travels: inline for small ones, uploaded-and-referenced for
    # anything the inline request can't carry. Deciding it HERE means the trial
    # door gets the same lift for free, and there is still exactly one rubric.
    size = _size_of(f)
    part, cleanup, why = _media_part(f, mime, size)
    if why:
        return None, ({"detail": f"The coach couldn't take that one — {why}.",
                       "size_mb": round(size / (1024 * 1024), 1)},
                      status.HTTP_502_BAD_GATEWAY)
    # Built ONCE, before the chain walks. Several models may be tried, and a
    # file object read a second time hands the next attempt an empty take —
    # which is also why the upload above happens once rather than per model.
    body = {"contents": [{"parts": [{"text": prompt}, part]}]}
    try:
        resp, tried = generate_content(
            "text", body, key=key,
            # A referenced file is read by the model rather than sent with the
            # request, and a long one takes longer to listen to than a short
            # one — so the wait scales with the take instead of cutting a good
            # one off at ninety seconds.
            timeout=90 if cleanup is None else 300,
            env_vars=("GEMINI_AUDIO_MODEL",),
            label=f"{app_key} coach")
    except requests.RequestException:
        logger.exception("SingZ coach: could not reach Gemini")
        return None, ({"detail": "Couldn't reach the coach. Try that take again."},
                      status.HTTP_502_BAD_GATEWAY)
    finally:
        # The upload is ours and it is finished with, whatever happened. Files
        # expire in 48 hours by themselves, so this is tidiness rather than a
        # correctness requirement — which is why it can never raise.
        if cleanup:
            cleanup()
    # Every name the chain actually tried, for the log line and the error body.
    model = ", ".join(tried)

    if resp.status_code != 200:
        # Log what we SENT as well as what came back. Without the mime type and
        # model in the line, a container rejection and a bad API key look
        # identical in the logs, which is how this one stayed hidden.
        logger.error("%s coach: Gemini %s for mime=%s model=%s — %s",
                     app_key, resp.status_code, mime, model, resp.text[:300])
        # And say it on the SCREEN. "The coach couldn't process that take" was
        # true of a bad key, a retired model, a spent quota and an unreadable
        # container alike — one sentence for four different problems, none of
        # them the member's, all of them reading like the take was bad.
        #
        # The upstream body is deliberately NOT forwarded: it is a third party's
        # error text, and it is not ours to put in front of a member. The status
        # plus our own reading of it is the useful part.
        why = {
            400: "that take's format wasn't accepted",
            403: "the coach's API key was refused",
            404: "the coach can't reach a model right now — we're on it",
            429: "the coach has hit its limit for now — try again shortly",
        }.get(resp.status_code,
              "the coach is having a moment" if resp.status_code >= 500
              else "the coach refused that one")
        return None, ({"detail": f"The coach couldn't read that take — {why}.",
                       # Enough for you to diagnose from a screenshot, and
                       # nothing that identifies the key or the account.
                       "upstream_status": resp.status_code,
                       "sent_mime": mime,
                       "model": model},
                      status.HTTP_502_BAD_GATEWAY)
    try:
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, ValueError):
        logger.error("SingZ coach: unexpected Gemini shape")
        return None, unreadable

    parsed = _parse(text)
    if not parsed or _clamp(parsed.get("score")) is None:
        logger.error("SingZ coach: unparseable reply — %s", text[:300])
        return None, ({"detail": "The coach's reply didn't come back readable. Try again."},
                      status.HTTP_502_BAD_GATEWAY)

    listy = lambda v: [str(x)[:300] for x in v][:6] if isinstance(v, list) else []
    return {
        "score": _clamp(parsed.get("score")),
        "scores": {k: _clamp((parsed.get("scores") or {}).get(k))
                   for k in profile_for_app(app_key)["scores"]},
        "verdict": str(parsed.get("verdict", ""))[:400],
        # Where they are and where they're going. A score with no destination
        # is a number, not coaching — and these are whitelisted like everything
        # else, so a field the model invents never reaches the screen.
        "now": str(parsed.get("now", ""))[:600],
        "goal": str(parsed.get("goal", ""))[:600],
        # Empty when the take was too short to read a range from, or when the
        # app has no range to read. The client hides the row rather than
        # printing a heading over nothing.
        "range_profile": str(parsed.get("range_profile", ""))[:600],
        "style_fit": str(parsed.get("style_fit", ""))[:600],
        "strengths": listy(parsed.get("strengths")),
        "fixes": listy(parsed.get("fixes")),
        "next_drill": str(parsed.get("next_drill", ""))[:300],
    }, None


class SingZCoachView(APIView):
    """The Boss Take coach for any InstrumentZ app.

    GET  → what a take costs this member, plus the dimensions THIS instrument
           is scored on so the client renders from the server rather than
           keeping its own copy that can drift.
    POST → multipart {take, genre, range, difficulty} → score + coaching.

    `app_key` is bound per-route in urls.py; it defaults to singz so the
    original /api/singz/coach/ keeps behaving exactly as it did.
    """

    permission_classes = [IsAuthenticated]
    # JSON as well as multipart: a take handed over from PostZ has no file
    # to upload — the recording is already stored — so that request is a
    # plain `{"post_id": 12}` and would 415 on a multipart-only view.
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    app_key = "singz"

    def get(self, request):
        """The price, before anyone commits to paying it.

        A cost that only appears in the response is a bill, not a price. This
        answers what THIS member pays for THIS take right now — whether a free
        daily prompt covers it, how many they have left, and what it falls back
        to if not.
        """
        profile = profile_for_app(self.app_key)
        tier = membership_for(request.user).tier
        cap_mb, cap_is_tier = cap_for(request.user)
        allowance, _, daily_left = daily_prompt_state(request.user)
        w = wallet_for(request.user)
        cost = ai_cost("standard")
        # "Allowed" now means CAN YOU TAKE ONE RIGHT NOW — configured, and either
        # a free prompt left or the balance to cover it. It used to mean "are you
        # StatZ", which was a less useful answer to the only question the screen
        # is actually asking.
        allowed = bool(_key()) and (daily_left > 0 or can_afford_ai(request.user, cost))
        return Response({
            "allowed": allowed,
            # Nothing tier-locks a take any more. The tier decides HOW MANY come
            # free per day, not whether you may have one — see the ladder below.
            "gated": False,
            "required_tier": None,
            "configured": bool(_key()),
            "cost_cents": cost,
            # A free daily prompt covers the whole run before any paid balance.
            "free_today": daily_left > 0,
            "daily_remaining": daily_left,
            "daily_allowance": allowance,
            "tier": tier,
            # What more would buy: frequency, not access. Stated so the upsell is
            # present and honest without being a wall in front of the feature.
            "allowance_ladder": [
                {"tier": t, "daily": PROMPT_ALLOWANCE[t]}
                for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ)
            ],
            "open_in": "membershipz",
            "promptz": w.promptz or 0,
            "money_cents": w.money_cents or 0,
            # A take the coach can't read is never billed — _bill runs only
            # after a usable result parses. Worth saying, not just doing.
            "charged_on_failure": False,
            # THIS member's ceiling, and whose it is — the coach's judgement or
            # their tier's own upload limit, whichever binds them first. This
            # flag was a hardcoded False, which was safe only while the coach's
            # number was the smaller one for everybody. At 200MB it isn't.
            "max_mb": cap_mb,
            "max_mb_why": cap_why(cap_mb, cap_is_tier),
            "max_mb_is_tier_limit": cap_is_tier,
            # What the coach itself would take regardless of tier, so a member
            # on a small plan can see what a tier up actually buys here.
            "coach_max_mb": MAX_MB,
            # Under this the take rides inside the request; over it, it is
            # uploaded first and referenced. Both are scored identically — this
            # is here for diagnosis, not for the screen.
            "inline_max_mb": INLINE_MAX_MB,
            # The client renders its score chips, range picker and honest-scope
            # footnote from these, so they cannot disagree with what the model
            # was actually asked to score.
            "app_key": self.app_key,
            "label": profile["label"],
            "scores": profile["scores"],
            "range_label": profile["range_label"],
            "ranges": [{"key": k, "label": l} for k, l in profile["ranges"]],
            # RapZ picks a style the way SingZ picks a range. Served from the
            # profile so the lab's picker and the coach's prompt can't drift
            # into two different lists of what a rap style is.
            "style_label": profile.get("style_label"),
            "styles": [{"key": k, "label": l} for k, l in profile.get("styles", [])],
            "difficulties": DIFFICULTIES,
            "caveat": profile["caveat"],
        })

    def post(self, request):
        # No tier gate. The blueprint filed the AI coach under StatZ Gated
        # Features and that was reconsidered on purpose: the trial door already
        # hands an anonymous visitor a full scored take, one per address per
        # day, so gating members harder than non-members had the ladder upside
        # down — a Premium member paying every month got less than a stranger.
        #
        # A take still costs a prompt, and the tier still decides how many come
        # free each day (PROMPT_ALLOWANCE: 1 / 5 / 10). Frequency is the honest
        # difference between somebody tracking daily and somebody curious once a
        # month; access was charging twice for the same thing.
        # Two ways in, one coach. Either a file was just recorded, or a post
        # the member is looking at IS the take — PostZ hands the post over
        # rather than asking anyone to find the file and upload it a second
        # time. Both land on the same rubric, the same size ceiling and the
        # same bill: a second scoring path is how one surface quietly stops
        # charging for what the other charges for.
        #
        # There are three doors and one coach: a file just recorded, a post the
        # member is looking at, and a page of their own diary. The third exists
        # because a voice note kept in JournalZ is a take like any other, and
        # making somebody publish their diary to have it scored would be this
        # app charging privacy as the price of a feature.
        #
        # `stored` is the shared half: a take that is ALREADY on the server, so
        # nothing is uploaded twice and the size is read from a row rather than
        # from storage. `post` stays set only for the post door, because the
        # things that are genuinely post-shaped — writing the score back onto
        # the post, offering the way back to it — are its alone.
        post = stored = None
        f = request.FILES.get("take")
        if f:
            content_type = (getattr(f, "content_type", "") or "").lower()
        else:
            post, f, content_type, err = self._take_from_post(request)
            if err:
                return err
            if post is None:
                stored, f, content_type, err = self._take_from_journal(request)
                if err:
                    return err
        if post is not None:
            stored = {"kind": "post", "title": post.title, "id": post.id}
        if not f:
            return Response({"detail": "Record or attach a take first."}, status=status.HTTP_400_BAD_REQUEST)
        # Video has always been accepted here — the model watches the take as
        # well as hearing it, which is worth real marks on delivery and breath.
        # The refusal copy said "isn't audio" and contradicted the check, which
        # is how the file picker ended up audio-only for a year.
        if not (content_type.startswith("audio/") or content_type.startswith("video/")):
            return Response({"detail": "That isn't audio or video. Record a take, or attach an "
                                       "audio or video file."},
                            status=status.HTTP_400_BAD_REQUEST)
        # An uploaded file knows its own size. A stored one does NOT — asking a
        # FieldFile for `.size` is a round trip to storage, and when the file
        # has gone missing that call RAISES. Unhandled, it left the member
        # looking at "Something went wrong on our side" for a recording that
        # simply isn't there any more. So the post path is measured from its
        # database row instead, inside _take_from_post, and never touches
        # storage until the take is actually read.
        cap_mb, cap_is_tier = cap_for(request.user)
        if stored is None and f.size > cap_mb * 1024 * 1024:
            return Response({"detail": f"That take is {f.size / (1024 * 1024):.0f}MB. "
                                       + cap_why(cap_mb, cap_is_tier),
                             "max_mb": cap_mb, "max_mb_is_tier_limit": cap_is_tier},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        key = _key()
        if not key:
            return Response({"detail": "The vocal coach isn't configured — set GEMINI_API_KEY on the backend."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # A free daily prompt covers the whole run, so it has to count here
        # too. Billing spends the allowance first (count_daily below), and this
        # gate did not know that — a StatZ member with prompts left but an
        # empty balance was refused a take that would have cost them nothing.
        cost = ai_cost("standard")
        _, _, daily_left = daily_prompt_state(request.user)
        if cost and not daily_left and not can_afford_ai(request.user, cost):
            return Response({"detail": "Not enough PromptZ / balance for a coached take.", "cost_cents": cost},
                            status=status.HTTP_402_PAYMENT_REQUIRED)

        data = request.data
        # A post already says what it is. Its genre seeds the coach when the
        # handoff didn't carry one, so a Drill track isn't scored as "unspecified".
        genre = data.get("genre") or (post.genre if post else "")
        try:
            if stored is not None:
                # Opened here rather than in the lookup, so a take refused on
                # size, on a missing key or on an empty balance never opens a
                # file handle it then has to remember to close.
                f.open("rb")
            payload, err = score_take(
                self.app_key, f, content_type,
                genre=genre, target=data.get("range"),
                difficulty=data.get("difficulty"), style=data.get("style"),
            )
        except Exception:
            # Almost always a recording that is no longer in storage. Say that,
            # and say it as a fact about the FILE rather than about the take or
            # about "our side" — the member did nothing wrong and the coach is
            # working fine. 410, not 502: the thing is gone, the server isn't.
            logger.exception("%s coach: %s %s take could not be read from storage",
                             self.app_key, (stored or {}).get("kind"),
                             (stored or {}).get("id"))
            # Named when the take came from somewhere with a name; "that take"
            # when it was just recorded. This used to read `post.title`
            # unconditionally, which meant a fresh upload failing here raised
            # inside the handler and answered 500 to a member whose only problem
            # was a file that hadn't finished writing.
            where = (stored or {}).get("title") or "that take"
            return Response(
                {"detail": f"The recording on \"{where}\" isn't on the server any "
                           "more, so there's nothing for the coach to listen to. Record "
                           "or attach the take here and it'll be scored.",
                 **({"post_id": post.id} if post else
                    {"journal_id": (stored or {}).get("id")}),
                 "take_missing": True},
                status=status.HTTP_410_GONE)
        finally:
            if stored is not None:
                try:
                    f.close()
                except Exception:                            # pragma: no cover
                    pass
        if err:
            body, code = err
            return Response(body, status=code)

        # Only bill once a usable result exists — a failed take is not charged.
        # count_daily: a coached take is a flat text-model run, so the tier's
        # free daily prompts cover it first. Without it the coach silently
        # skipped the allowance a StatZ member is told they get and went
        # straight to their PromptZ and cash.
        note = f"{profile_for_app(self.app_key)['label']} Boss Take — AI Coach"
        if stored is not None:
            note += f" — {stored['kind']} #{stored['id']}"
        charged = _bill(request.user, note=note, count_daily=True)
        out = {**payload, "cost_cents": charged}
        if stored is not None and post is None:
            # A scored take is never a dead end either: the score offers the way
            # back to the day it came from.
            out.update({"source": "journal", "journal_id": stored["id"],
                        "journal_day": stored["day"],
                        "open_in": "journalz", "target": "journalz-entries"})
        if post is not None:
            out.update({
                "source": "post", "post_id": post.id, "post_title": post.title,
                "post_author": post.author.username,
                # Where this came from, so the score isn't a dead end either —
                # the client offers the way back to the post it scored.
                "open_in": "postz", "target": f"post:{post.id}",
                # Kept on the post when it's the member's own work. Post.score
                # is exactly this field — "optional scored-take payload (e.g.
                # RapZ/SingZ lab result) for context on the post" — so a post
                # that has been coached carries its coaching instead of the
                # result living for one screenful and then being gone.
                "saved_to_post": self._save_to_post(post, request.user, payload,
                                                    self.app_key),
            })
        return Response(out)

    def _take_from_post(self, request):
        """(post, file, content_type, error_response) for a post-sourced take.

        The post is resolved from the id and read for its OWN media URL — the
        client never says which file to score, so no address it invents can
        reach a file. Viewing rights are checked first: a take you may not see
        is not a take you may send to a model.
        """
        from .crosspost import post_take
        from .models import Post, can_view_post
        from .postz import media_slots

        raw = request.data.get("post_id")
        if raw in (None, ""):
            return None, None, "", None      # no file and no post: the caller says so
        try:
            pk = int(raw)
        except (TypeError, ValueError):
            return None, None, "", Response({"detail": "post_id must be a number."},
                                            status=status.HTTP_400_BAD_REQUEST)
        post = Post.objects.filter(pk=pk).select_related("author").first()
        if not post:
            return None, None, "", Response({"detail": "post not found"},
                                            status=status.HTTP_404_NOT_FOUND)
        if not can_view_post(post, request.user):
            return None, None, "", Response({"detail": "you can't view this post"},
                                            status=status.HTTP_403_FORBIDDEN)
        upload, kind, why = post_take(post, media_slots(post))
        if why:
            return None, None, "", Response({"detail": why, "post_id": post.id},
                                            status=status.HTTP_400_BAD_REQUEST)
        # Measured from the ROW, never from the file. `Upload.size_bytes` is a
        # column; `FieldFile.size` is a storage call that raises on a file that
        # has gone missing — which is exactly how the ceiling check turned a
        # dead recording into a 500.
        cap_mb, cap_is_tier = cap_for(request.user)
        if (upload.size_bytes or 0) > cap_mb * 1024 * 1024:
            return None, None, "", Response(
                {"detail": f"\"{post.title}\" is {upload.size_bytes / (1024 * 1024):.0f}MB. "
                           + cap_why(cap_mb, cap_is_tier)
                           + " The post keeps the full track — record or attach the "
                             "section you want scored.",
                 "max_mb": cap_mb, "max_mb_is_tier_limit": cap_is_tier, "post_id": post.id},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        # The Upload's own recorded type, falling back to the slot the post
        # keeps it in — an upload saved with no content type is still audio if
        # that is the slot it fills.
        content_type = (upload.content_type or "").lower() or f"{kind}/webm"
        return post, upload.file, content_type, None

    def _take_from_journal(self, request):
        """(stored, file, content_type, error) for a take on a journal entry.

        Yours only, and that is not an oversight to be relaxed later. A journal
        entry is private by default and a shared one is a POST — which already
        has the post door, with its own view check. So the only entry anybody
        can coach through here is one of their own, and the query says so
        rather than a permission check saying it afterwards.
        """
        from .crosspost import upload_behind
        from .journalz import entry_media
        from .models import JournalEntry

        raw = request.data.get("journal_id")
        if raw in (None, ""):
            return None, None, "", None
        try:
            pk = int(raw)
        except (TypeError, ValueError):
            return None, None, "", Response({"detail": "journal_id must be a number."},
                                            status=status.HTTP_400_BAD_REQUEST)
        e = JournalEntry.objects.filter(pk=pk, author=request.user).first()
        if not e:
            return None, None, "", Response({"detail": "entry not found"},
                                            status=status.HTTP_404_NOT_FOUND)
        media = entry_media(e)
        kind = next((k for k in ("audio", "video") if media.get(k)), "")
        if not kind:
            return None, None, "", Response(
                {"detail": "There's no recording on that entry — the coach scores audio "
                           "or video, so attach a take and try again.",
                 "journal_id": e.id}, status=status.HTTP_400_BAD_REQUEST)
        upload = upload_behind(media[kind], [request.user.id])
        if upload is None:
            return None, None, "", Response(
                {"detail": "That take isn't stored on Music ConnectZ, so the coach can't "
                           "read it. Record or attach it in the coach and it'll be scored.",
                 "journal_id": e.id}, status=status.HTTP_400_BAD_REQUEST)
        # From the ROW, never the file — see _take_from_post.
        cap_mb, cap_is_tier = cap_for(request.user)
        if (upload.size_bytes or 0) > cap_mb * 1024 * 1024:
            return None, None, "", Response(
                {"detail": f"That take is {upload.size_bytes / (1024 * 1024):.0f}MB. "
                           + cap_why(cap_mb, cap_is_tier)
                           + " The entry keeps the whole recording — attach just the "
                             "section you want scored.",
                 "max_mb": cap_mb, "max_mb_is_tier_limit": cap_is_tier,
                 "journal_id": e.id},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        content_type = (upload.content_type or "").lower() or f"{kind}/webm"
        stored = {"kind": "journal", "id": e.id, "title": e.title or str(e.day),
                  "day": str(e.day)}
        return stored, upload.file, content_type, None

    @staticmethod
    def _save_to_post(post, user, payload, app_key):
        """Keep the coaching ON the post — but only when the post is theirs.

        Coaching somebody else's track is allowed (you can see it, you paid for
        it, and a second opinion is the point of a feed). Writing your score
        onto their post is not: their post carries their name, and a number
        that appeared on it because a stranger spent a prompt is the platform
        putting words in their mouth. So that run answers to the member who
        asked for it and leaves the post alone.
        """
        from .models import owns_post
        from django.utils import timezone

        if not owns_post(post, user):
            return False
        post.score = {**payload, "app_key": app_key,
                      "coached_by": user.username,
                      "coached_at": timezone.now().isoformat()}
        post.save(update_fields=["score"])
        return True
