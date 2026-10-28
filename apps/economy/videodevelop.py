"""Video ConnectZ, Develop and Direct modes (StatZ): every shot of a music video
picked to go with the song — its lyrics, or its mood.

* **Develop** — the member picks each shot from the coach's options.
* **Direct** — the coach picks each shot itself, and says why (Corey's name for it).
  Same run and same price: the coach always marks the option it would pick, and
  Direct mode is the screen applying those picks. Every pick stays editable, so
  Direct is a starting point the member can overrule, never a lock.

The stitched music video (`videostitch.py`) joins 2-4 shots over the member's own
track, each shot written by hand. Develop mode is the planning step in front of
it: the model LISTENS to the part of the track the video will play, and for every
shot's slot of the song says what it hears there and offers three shots that go
with it. The member picks one per slot, or writes their own, and the shots go
into the ordinary stitched render, priced and refunded exactly as before.

Rules that hold it, each one an existing rule applied here:

* **The slots are the server's arithmetic, never the model's.** Shot i plays over
  `track_start + (i-1) x CLIP_SECONDS` to the next, because that is how
  `videostitch._join` lays the track under the shots. The model is told those
  times and asked what is heard in each; a time it sends back is ignored. A plan
  whose slots did not match the render would be decoration.
* **It hears the song; it does not guess it from a title.** The member's own
  uploaded track is sent (`vocalcoach._media_part`, inline or via the Files API).
  Lyrics and a mood are optional help, never a substitute: the lyrics are the
  member's own words, so a slot may quote its line back to them.
* **Every option says WHY** (`ties_to` lyric / mood / beat, plus a sentence), so a
  pick is a choice between reasons rather than between three adjectives.
* **StatZ, and the daily sample** (`statz_trial` feature `video_develop`). It is a
  plan, a read of the song: when the sample ends it switches off cleanly and the
  video already rendered from a plan is the member's. Writing shots by hand stays
  free of any gate — the tier decides who gets the planner, never who gets a video.
* **One standard AI price, stated before the button; a failed run is not charged.**
  The shots themselves are then priced by the stitch, per shot, as always.
* **Nothing is stored here.** The plan goes onto the shot fields; what is kept is
  the video it becomes (each shot's text is on its `VideoWork`). The track is the
  member's own upload and is only read.
"""
import logging

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import vocalcoach as vc
from .catalog import ai_cost
from .deadline import COACH_BUDGET_SECONDS, Deadline, Expired
from .gemini import _bill, _key, generate_content
from .models import Upload, can_afford_ai, daily_prompt_state, mark_upload_missing
from .statz_trial import UPGRADE, has_statz
from .videostitch import MAX_SHOTS, MIN_SHOTS, is_audio
from .videoz import CLIP_SECONDS

logger = logging.getLogger(__name__)

FEATURE = "video_develop"
LABEL = "Develop & Direct"
MODES = {"develop": "Develop — you pick each shot from the coach's options",
         "direct": "Direct — the coach picks every shot, and you can change any of them"}
LYRICS_MAX = 4000
MOOD_MAX = 200
OPTIONS = 3
TIES = {"lyric": "the lyric", "mood": "the mood", "beat": "the beat"}
WHAT_IT_DOES = ("The AI listens to the part of your track the video plays and, for each shot's "
                f"{CLIP_SECONDS} seconds of it, says what it hears and offers {OPTIONS} shots that go with "
                "the lyric there, the mood or the beat — each with why. You pick one per shot, or write "
                "your own, then make the video as usual.")
LOCKED = ("Develop and Direct — the AI planning each shot to fit your song — are StatZ features. Writing the "
          "shots yourself is open to everyone.")


def slots_for(start, n):
    """The (start, end) seconds each shot plays over, exactly as the stitch lays the track."""
    return [(start + i * CLIP_SECONDS, start + (i + 1) * CLIP_SECONDS) for i in range(n)]


def _clock(s):
    return f"{s // 60}:{s % 60:02d}"


def prompt_for(slots, lyrics, mood, look, kind_ask):
    lines = "\n".join(f"  slot {i}: {_clock(a)}–{_clock(b)}" for i, (a, b) in enumerate(slots, 1))
    return (
        "You are planning a short music video for the member's own song, which is attached. "
        f"The video has {len(slots)} shots of {CLIP_SECONDS} seconds each, joined in order, with the song "
        "playing under them. Each shot plays over this part of the song:\n"
        f"{lines}\n"
        "Listen to each slot of the song. For each one, say what is heard there, then offer exactly "
        f"{OPTIONS} different shots that go with it.\n"
        "Each shot is a one or two sentence direction for an AI video model: what is in frame, the camera, the "
        "light and the movement. It must work as ONE continuous 8-second clip. No real or famous people, no "
        "brands or logos, no on-screen text, nothing sexual or violent.\n"
        "Tie each option to ONE of: \"lyric\" (what is sung or rapped in that slot), \"mood\" (how that part "
        "feels) or \"beat\" (the rhythm, a drop, a build). Say why in one short sentence. Across the three "
        "options give the member a real choice, not three wordings of one idea.\n"
        + (f"The member's lyrics (their own words; quote at most one short line per slot, only if it is heard "
           f"there):\n<<<\n{lyrics}\n>>>\n" if lyrics else
           "No lyrics were given: if words are heard, describe them briefly rather than transcribing.\n")
        + (f"The mood the member wants: {mood}\n" if mood else "")
        + (f"The look the member already set for every shot: {look}\n" if look else "")
        + f"The kind of video: {kind_ask}\n"
        "Also suggest one LOOK line for the whole video (palette, texture, era) that fits the song.\n"
        "If the attachment is silent or is not music, return {\"unplannable\": \"<one sentence why>\"}.\n"
        "Reply with JSON only:\n"
        "{\"overall\": \"<one sentence: what the song is, its arc>\", \"look\": \"<one line>\", "
        "\"slots\": [{\"heard\": \"<what is heard in this slot>\", \"mood\": \"<a few words>\", "
        "\"options\": [{\"shot\": \"<direction>\", \"ties_to\": \"lyric|mood|beat\", \"why\": \"<sentence>\"}], "
        "\"pick\": <0, 1 or 2: the option YOU would direct, as the video's director>, "
        "\"pick_why\": \"<one sentence: why that one, in the arc of the whole video>\"}]}"
    )


def _txt(v, n):
    return " ".join(str(v or "").split())[:n]


def clean_plan(parsed, slots):
    """The model's plan held to the server's slots: times are ours, options capped and
    whitelisted, and a slot with no usable option makes the whole plan unusable."""
    raw = parsed.get("slots") if isinstance(parsed, dict) else None
    if not isinstance(raw, list):
        return None
    out = []
    for i, (a, b) in enumerate(slots):
        row = raw[i] if i < len(raw) and isinstance(raw[i], dict) else {}
        opts = []
        for o in (row.get("options") or [])[:OPTIONS]:
            if not isinstance(o, dict):
                continue
            shot = _txt(o.get("shot"), 300)
            if not shot:
                continue
            tie = o.get("ties_to") if o.get("ties_to") in TIES else "mood"
            opts.append({"shot": shot, "ties_to": tie, "ties_label": TIES[tie], "why": _txt(o.get("why"), 200)})
        if not opts:
            return None
        # The coach's own pick (Direct mode). An index it did not offer falls back to
        # the first option and the reason is dropped rather than attached to the wrong shot.
        try:
            pick = int(row.get("pick"))
        except (TypeError, ValueError):
            pick = -1
        pick_why = _txt(row.get("pick_why"), 200) if 0 <= pick < len(opts) else ""
        pick = pick if 0 <= pick < len(opts) else 0
        out.append({"slot": i + 1, "start": a, "end": b, "at": f"{_clock(a)}–{_clock(b)}",
                    "heard": _txt(row.get("heard"), 240), "mood": _txt(row.get("mood"), 60), "options": opts,
                    "pick": pick, "pick_why": pick_why})
    return {"overall": _txt(parsed.get("overall"), 240), "look": _txt(parsed.get("look"), 300), "slots": out}


class VideoDevelopView(APIView):
    """GET: whether Develop mode is open to you, and what one plan costs. POST: plan the shots."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cost = ai_cost("standard")
        _, _, daily_left = daily_prompt_state(request.user)
        allowed = has_statz(request.user)
        return Response({
            "feature": FEATURE, "label": LABEL, "allowed": allowed,
            "locked_reason": "" if allowed else LOCKED, "upgrade": UPGRADE,
            "cost_cents": cost, "free_today": daily_left > 0, "charged_on_failure": False,
            "what_it_does": WHAT_IT_DOES, "modes": MODES, "clip_seconds": CLIP_SECONDS, "options": OPTIONS,
            "min_shots": MIN_SHOTS, "max_shots": MAX_SHOTS,
            "lyrics_max": LYRICS_MAX, "mood_max": MOOD_MAX, "ties": TIES,
            "configured": bool(_key()),
        })

    def post(self, request):
        user = request.user
        if not has_statz(user):
            return Response({"detail": LOCKED, "feature": FEATURE, "upgrade": UPGRADE},
                            status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        track = Upload.objects.filter(pk=d.get("track_id") or 0, user=user, missing_since__isnull=True).first()
        if not track or not is_audio(track):
            return Response({"detail": "Pick one of your own uploaded tracks. Nothing was charged."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            n = int(d.get("shots") or 0)
        except (TypeError, ValueError):
            n = 0
        if not (MIN_SHOTS <= n <= MAX_SHOTS):
            return Response({"detail": f"Plan {MIN_SHOTS} to {MAX_SHOTS} shots."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            start = max(0, min(int(d.get("track_start") or 0), 3600))
        except (TypeError, ValueError):
            start = 0
        lyrics = str(d.get("lyrics") or "").strip()
        if len(lyrics) > LYRICS_MAX:
            return Response({"detail": f"Lyrics go up to {LYRICS_MAX:,} characters — paste the part the video plays."},
                            status=status.HTTP_400_BAD_REQUEST)
        mood, look = _txt(d.get("mood"), MOOD_MAX), _txt(d.get("look"), 300)
        from .videoz import KINDS
        kind_ask = KINDS["music"]["ask"]

        cost = ai_cost("standard")
        _, _, daily_left = daily_prompt_state(user)
        if cost and not daily_left and not can_afford_ai(user, cost):
            return Response({"detail": "Not enough PromptZ / balance to plan the shots.", "cost_cents": cost},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        if not _key():
            return Response({"detail": "Develop mode isn't switched on yet. Nothing was charged."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        slots = slots_for(start, n)
        deadline = Deadline(COACH_BUDGET_SECONDS)
        cleanup = None
        try:
            f = track.file
            f.open("rb")
            try:
                size = vc._size_of(f)
                if size == 0:
                    return Response({"detail": "That track is empty. Nothing was charged."},
                                    status=status.HTTP_400_BAD_REQUEST)
                mime = vc.gemini_mime(track.content_type or "audio/mpeg")
                if not mime:
                    return Response({"detail": f"The AI can't read \"{track.name}\" as audio. Try an MP3, WAV "
                                               "or M4A of the song. Nothing was charged."},
                                    status=status.HTTP_400_BAD_REQUEST)
                part, cleanup, why = vc._media_part(f, mime, size, deadline=deadline)
            finally:
                f.close()
            if why:
                return Response({"detail": f"The AI couldn't take that track — {why}. Nothing was charged."},
                                status=status.HTTP_502_BAD_GATEWAY)
            body = {"contents": [{"parts": [{"text": prompt_for(slots, lyrics, mood, look, kind_ask)}, part]}],
                    "generationConfig": {"temperature": 0.7}}
            deadline.check("the track was still uploading when the time ran out")
            resp, _ = generate_content("text", body, key=_key(), timeout=deadline.remaining(cap=120),
                                       env_vars=("GEMINI_AUDIO_MODEL",), label="video develop")
        except Expired as e:
            return Response({"detail": f"Planning is taking longer than it should — {e.message}. Nothing was charged.",
                             "timed_out": True}, status=status.HTTP_504_GATEWAY_TIMEOUT)
        except requests.RequestException:
            logger.exception("video develop: could not reach Gemini")
            return Response({"detail": "Couldn't reach the AI. Nothing was charged — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        except (FileNotFoundError, OSError):
            mark_upload_missing(track)
            return Response({"detail": f"\"{track.name}\" isn't on the server any more. Nothing was charged.",
                             "track_missing": True}, status=status.HTTP_410_GONE)
        finally:
            if cleanup:
                try:
                    cleanup()
                except Exception:  # pragma: no cover - tidiness, never a failure
                    logger.exception("video develop: cleanup failed")

        if resp.status_code != 200:
            logger.error("video develop: Gemini %s — %s", resp.status_code, resp.text[:300])
            return Response({"detail": "The AI couldn't plan from that track right now. Nothing was charged."},
                            status=status.HTTP_502_BAD_GATEWAY)
        try:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError):
            text = ""
        parsed = vc._parse(text)
        if parsed and _txt(parsed.get("unplannable"), 300):
            return Response({"unplannable": _txt(parsed["unplannable"], 300), "cost_cents": 0})
        plan = clean_plan(parsed or {}, slots)
        if not plan:
            return Response({"detail": "The AI's plan didn't come back usable. Nothing was charged."},
                            status=status.HTTP_502_BAD_GATEWAY)
        charged = _bill(user, note="Video ConnectZ Develop mode — AI", count_daily=True)
        return Response({**plan, "cost_cents": charged, "track_id": track.id, "track_start": start,
                         "clip_seconds": CLIP_SECONDS, "saved": False})
