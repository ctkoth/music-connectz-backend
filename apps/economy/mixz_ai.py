"""Mix ConnectZ's AI: it LISTENS to the song, names the genre, and sets the master — eMastered's headline.

Two doors, side by side, because the free one has to exist beside the paid one:

* **Genre presets** (`GENRES`): a starting master for a genre — style, intensity, loudness, punch,
  multiband and the three EQ trims — each with the reason a mastering engineer would give. Free; the
  screen applies them without asking the server for anything but this list.
* **AI listen** (`POST mixz/ai/`): ~90 seconds of the song go to a model that hears it, picks the genre
  from the SAME closed list, and adjusts that genre's preset from a closed list of moves, each with why
  in one sentence ("the low end is already heavy — lows −1 dB"). Priced like any AI run, stated on GET
  before the button; a reply we cannot read is not charged.

What the model may do is decided here, not by the model:

* **Only declared keys, only inside the engine's ranges.** The ranges mirror the frontend's
  `cleanSettings` (master.js), which clamps again as the settings land — the model cannot ask for a
  louder master than the screen's own slider allows, a style that does not exist, or a key nobody reads.
* **Nothing is mastered here.** The answer is settings for the controls; the member hears them by
  pressing Master it, and can move every one. An AI that silently mastered would be a verdict; this is a
  starting point with its reasons on screen, the same rule as TrackZ's "Suggest a balance".
* **The clip is not kept.** It rides inside the one request as inline data and nothing stores it.
"""
import base64
import json
import logging
import re

import requests
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import ai_cost
from .gemini import _bill, _key, generate_content
from .models import ai_energy_cost, can_afford_ai, daily_prompt_covers, daily_prompt_state

logger = logging.getLogger(__name__)

CLIP_MAX_MB = 10
CLIP_SECONDS = 90
MIMES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/wave", "audio/webm", "audio/ogg", "audio/mp4", "audio/aac"}

# The engine's own vocabulary (frontend master.js). Kept here only to refuse what it would not read.
STYLES = ("warm", "balanced", "open")
INTENSITIES = ("low", "medium", "high", "max")
TARGETS = ("streaming", "apple", "loud")
RANGES = {"punch": (-50, 50), "width": (50, 150), "trims.low": (-4, 4), "trims.mid": (-4, 4), "trims.high": (-4, 4),
          "vocal": (0, 6)}


def _p(style, intensity, target, punch=0, multiband=False, low=0, mid=0, high=0, width=None, vocal=None):
    out = {"style": style, "intensity": intensity, "target": target, "punch": punch, "multiband": multiband,
           "width": width, "trims": {"low": low, "mid": mid, "high": high}}
    if vocal is not None:
        out["vocal"] = vocal
    return out


# Each genre: the starting master and why. Ordered as a member scans them.
GENRES = {
    "hiphop": {"label": "Hip-hop / Trap", "emoji": "🎤", "settings": _p("balanced", "high", "streaming", 15, True, low=1),
               "why": "Heavy 808s and a vocal that has to cut: multiband keeps the low end from pumping the vocal, a little extra punch keeps the drums hitting."},
    "drill": {"label": "Drill", "emoji": "🔩", "settings": _p("balanced", "high", "streaming", 20, True, low=1.5),
              "why": "Sliding 808s carry the song, so the lows get a lift and multiband stops them pulling the hats and vocal down."},
    "rnb": {"label": "R&B / Soul", "emoji": "🎶", "settings": _p("warm", "medium", "streaming", 0, False, high=0.5),
            "why": "Smooth, not squashed: a warm tilt, medium compression and a touch of air on the vocal."},
    "pop": {"label": "Pop", "emoji": "✨", "settings": _p("open", "high", "streaming", 10, True, high=1),
            "why": "Bright and forward: an open tilt, firm glue so the chorus lifts, and air on the top."},
    "rock": {"label": "Rock / Alternative", "emoji": "🎸", "settings": _p("balanced", "high", "streaming", 20, False, mid=0.5),
             "why": "Guitars live in the mids, so they get a nudge, and extra punch keeps the snare from going soft under the limiter."},
    "edm": {"label": "EDM / Dance", "emoji": "🎛️", "settings": _p("open", "high", "loud", 10, True, low=1, high=0.5),
            "why": "Built for clubs: louder, wide and open, with multiband holding the kick and bass apart from the leads."},
    "afro": {"label": "Afrobeats / Amapiano", "emoji": "🥁", "settings": _p("open", "medium", "streaming", 10, True, low=0.5),
             "why": "Percussion and log drums need room to bounce: medium glue, multiband for the lows, and an open top."},
    "latin": {"label": "Latin / Reggaeton", "emoji": "💃", "settings": _p("balanced", "high", "streaming", 15, True, low=1),
              "why": "The dembow kick and bass drive it: punch on the hits, multiband so the vocal stays on top."},
    "lofi": {"label": "Lo-fi / Chill", "emoji": "☕", "settings": _p("warm", "low", "streaming", -10, False, high=-1),
             "why": "Soft edges are the sound: light compression, a warm tilt, and the top end rolled off a touch."},
    "acoustic": {"label": "Acoustic / Singer-songwriter", "emoji": "🪕", "settings": _p("warm", "low", "apple", 0, False),
                 "why": "Dynamics are the performance: light compression and Apple's quieter target leave the quiet parts quiet."},
    "gospel": {"label": "Gospel / Choir", "emoji": "🙏", "settings": _p("warm", "medium", "streaming", 0, False, mid=0.5, width=110),
               "why": "Many voices together: a warm tilt, some width for the choir, and mids that keep the words clear."},
    "metal": {"label": "Metal", "emoji": "🤘", "settings": _p("balanced", "max", "loud", 10, True, mid=-0.5),
              "why": "Dense and loud on purpose: the heaviest glue, multiband so kick and guitars stop fighting, mids eased so it does not honk."},
}
GENRE_KEYS = tuple(GENRES)

# Masters by RAP STYLE and by SINGING RANGE. Keyed by the coaches' own slugs (instruments.RAP_STYLES / VOCAL_RANGES — a test
# holds the two lists equal), so a take scored as Drill or sung as a Baritone can offer its own master. They are NOT in
# GENRE_KEYS: the AI picks a genre from that list and these are not genres.
#   A STYLE decides how the master is pushed: how hard it is glued, whether the drums are punched, whether the lows are
#   split from the vocal, how wide it sits. A RANGE decides where the voice needs help: a low voice sits where the bass
#   and the kick live, so it is masked first and gets the bigger centre lift and a nudge in the mids; a high voice is
#   already forward, so it gets a smaller lift and the top is eased instead of boosted, because sibilance and harshness
#   are what a bright master makes worse. Starting points, said as such; the AI listen can still move them.
RAP_MASTERS = {
    "boom-bap": ("Boom Bap", "🥁", _p("warm", "medium", "streaming", 10, False, low=0.5, vocal=2), "Dusty and punchy: a warm tilt, medium glue and a little punch so the snare keeps its crack."),
    "trap": ("Trap", "🏚️", _p("balanced", "high", "streaming", 15, True, low=1, vocal=3), "808s and a vocal that has to cut: multiband keeps the low end from pumping the vocal."),
    "drill": ("Drill", "⚔️", _p("balanced", "high", "streaming", 20, True, low=1.5, vocal=3), "The sliding 808 carries it: lows lifted, multiband so it doesn't pull the hats and vocal down."),
    "cloud-rap": ("Cloud Rap", "☁️", _p("warm", "low", "streaming", -10, False, high=-1, vocal=1.5), "Soft edges are the sound: light compression, a warm tilt, the top rolled off a touch."),
    "lyrical": ("Lyrical", "🧠", _p("balanced", "medium", "streaming", 0, False, mid=0.5, vocal=3), "Every word has to be heard: a firmer vocal lift and mids that keep consonants clear."),
    "storytelling": ("Storytelling", "📖", _p("warm", "low", "apple", 0, False, mid=0.5, vocal=2), "Dynamics carry the story: light compression and the quieter Apple target."),
    "freestyle": ("Freestyle", "🌀", _p("balanced", "medium", "streaming", 5, False, vocal=2), "Even-handed: nothing pushed, so the take sounds like the take."),
    "melodic": ("Melodic", "🎶", _p("open", "medium", "streaming", 5, True, high=0.5, vocal=2), "Sung-rap needs air: an open tilt, medium glue, multiband to keep the bass out of the hook."),
    "double-time": ("Double-Time", "⚡", _p("balanced", "high", "streaming", 10, False, mid=0.5, vocal=3), "Fast syllables smear first: firm glue and a midrange nudge keep them separate."),
    "old-school": ("Old School", "📻", _p("warm", "medium", "streaming", 10, False, high=-0.5, width=90, vocal=2), "A little narrower and warmer, like a record from then, with punch on the drums."),
    "conscious": ("Conscious", "✊", _p("warm", "low", "apple", 0, False, mid=0.5, vocal=2.5), "The message leads: warm, spacious, and a vocal that stays clear."),
    "mumble": ("Mumble", "😶‍🌫️", _p("warm", "high", "streaming", 10, True, low=1, high=-1, vocal=2), "Heavy and hazy: dense glue, multiband for the bass, the top eased so it doesn't turn brittle."),
}
RANGE_MASTERS = {
    "bass": ("Bass", "🧔‍♂️", _p("balanced", "medium", "streaming", 0, False, mid=0.5, vocal=3.5), "The lowest voice sits where the kick and bass live, so it is masked first: the biggest centre lift and a nudge in the mids."),
    "baritone": ("Baritone", "🎙️", _p("balanced", "medium", "streaming", 0, False, mid=0.5, vocal=3), "Still under the low end of most mixes: a firm centre lift and a little mid."),
    "tenor": ("Tenor", "🎤", _p("balanced", "medium", "streaming", 0, False, vocal=2.5), "Sits in the middle of the mix: a moderate lift, no tone moves."),
    "countertenor": ("Countertenor", "🕊️", _p("open", "medium", "streaming", 0, False, vocal=2), "Already forward: a lighter lift and an open top."),
    "contralto": ("Contralto", "🎻", _p("warm", "medium", "streaming", 0, False, mid=0.5, vocal=3), "A low female voice meets the same masking a baritone does: a firm lift and a warm tilt."),
    "alto": ("Alto", "🎶", _p("balanced", "medium", "streaming", 0, False, vocal=2.5), "Balanced: a moderate lift, nothing else."),
    "mezzo-soprano": ("Mezzo-Soprano", "🌊", _p("balanced", "medium", "streaming", 0, False, high=-0.5, vocal=2), "Forward already: a lighter lift and the top eased a touch."),
    "soprano": ("Soprano", "☀️", _p("warm", "medium", "streaming", 0, False, high=-1, vocal=1.5), "The brightest voice: the smallest lift, and the top eased because a bright master makes harshness worse."),
}

# The moves the AI may make on top of its genre's preset. Anything else it says is dropped.
MOVES = ("style", "intensity", "target", "punch", "multiband", "width", "trims.low", "trims.mid", "trims.high", "vocal")
MAX_MOVES = 6


def genres_payload():
    out = [{"key": k, "group": "Genre", **{f: g[f] for f in ("label", "emoji", "settings", "why")}} for k, g in GENRES.items()]
    for group, table in (("Rap style", RAP_MASTERS), ("Singing range", RANGE_MASTERS)):
        out += [{"key": f"{group.split()[0].lower()}:{k}", "group": group, "label": f"{label} master", "emoji": emoji, "settings": settings, "why": why}
                for k, (label, emoji, settings, why) in table.items()]
    return out


def prompt():
    return (
        "You are a mastering engineer. Listen to this excerpt of a finished mix (about "
        f"{CLIP_SECONDS} seconds) and decide how to master it.\n"
        f"1. Pick the genre it is closest to, from exactly these keys: {', '.join(GENRE_KEYS)}.\n"
        "2. That genre has a starting preset. Say what THIS song needs on top of it, as a few moves "
        f"(at most {MAX_MOVES}), each from this list only: style (warm|balanced|open), intensity "
        "(low|medium|high|max), target (streaming|apple|loud), punch (-50..50), multiband (true|false), "
        "width (50..150 percent), trims.low / trims.mid / trims.high (-4..4 dB), vocal (0..6 dB lift on the "
        "centre where a voice lives). Only move what you can HEAR needs it; an empty list is a fine answer.\n"
        "3. One sentence on what you heard (the balance, the low end, the vocal, how dense it already is).\n"
        "Return JSON only: {\"genre\": key, \"heard\": sentence, \"moves\": [{\"key\": move key, \"value\": "
        "value, \"why\": one sentence}]}. Do not invent loudness numbers or measurements; describe what you hear."
    )


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def clean_moves(raw):
    """The model's moves, kept only when the key is declared and the value is one the engine reads."""
    out = []
    for m in raw if isinstance(raw, list) else []:
        if not isinstance(m, dict) or m.get("key") not in MOVES:
            continue
        k, v = m["key"], m.get("value")
        why = " ".join(str(m.get("why") or "").split())[:200]
        if k == "style":
            v = v if v in STYLES else None
        elif k == "intensity":
            v = v if v in INTENSITIES else None
        elif k == "target":
            v = v if v in TARGETS else None
        elif k == "multiband":
            v = v if isinstance(v, bool) else (str(v).lower() == "true" if str(v).lower() in ("true", "false") else None)
        else:
            n = _num(v)
            lo, hi = RANGES[k]
            v = None if n is None else round(max(lo, min(hi, n)) * 2) / 2
        if v is None or not why or any(x["key"] == k for x in out):
            continue
        out.append({"key": k, "value": v, "why": why})
        if len(out) >= MAX_MOVES:
            break
    return out


def apply_moves(genre_key, moves):
    """The genre's preset with the moves on top: the settings the screen puts on its controls."""
    s = json.loads(json.dumps(GENRES[genre_key]["settings"]))
    for m in moves:
        if m["key"].startswith("trims."):
            s["trims"][m["key"].split(".", 1)[1]] = m["value"]
        else:
            s[m["key"]] = m["value"]
    return s


def parse(text):
    """{genre, heard, moves} from the model's reply, or None when there is nothing usable."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0) if m else text)
    except (ValueError, AttributeError):
        return None
    if not isinstance(d, dict) or d.get("genre") not in GENRES:
        return None
    heard = " ".join(str(d.get("heard") or "").split())[:300]
    return {"genre": d["genre"], "heard": heard, "moves": clean_moves(d.get("moves"))}


def _price(user):
    cost = ai_cost("standard")
    _, _, left = daily_prompt_state(user)
    free = left > 0 and daily_prompt_covers(cost)
    return {"cost_cents": cost, "free_today": free, "energy": ai_energy_cost(user),
            "can_run": bool(_key()) and (free or can_afford_ai(user, cost))}


class MixAIView(APIView):
    """GET: the genre presets (free) and the AI listen's price. POST multipart `clip`: the AI's master settings."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        return Response({"genres": genres_payload(), "price": _price(request.user), "configured": bool(_key()),
                         "clip_seconds": CLIP_SECONDS, "clip_max_mb": CLIP_MAX_MB,
                         "note": ("The AI hears about 90 seconds from the middle of your song, picks its genre and "
                                  "sets the master with a reason for every move. Nothing is mastered until you press "
                                  "Master it, and the clip is not kept. A listen that can't be read is not charged.")})

    def post(self, request):
        f = request.FILES.get("clip")
        if not f:
            return Response({"detail": "Load a song first — the AI needs something to hear."}, status=status.HTTP_400_BAD_REQUEST)
        if f.size > CLIP_MAX_MB * 1024 * 1024:
            return Response({"detail": f"That clip is over {CLIP_MAX_MB} MB."}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        mime = (getattr(f, "content_type", "") or "").split(";")[0].strip().lower()
        if mime not in MIMES:
            return Response({"detail": "Send the clip as MP3, WAV, WebM, OGG or M4A."}, status=status.HTTP_400_BAD_REQUEST)
        key = _key()
        if not key:
            return Response({"detail": "The AI isn't switched on — the backend is missing GEMINI_API_KEY."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        price = _price(request.user)
        if not price["free_today"] and not can_afford_ai(request.user, price["cost_cents"]):
            return Response({"detail": "Not enough PromptZ or balance for an AI listen.", **price}, status=status.HTTP_402_PAYMENT_REQUIRED)
        body = {"contents": [{"parts": [{"text": prompt()},
                                        {"inline_data": {"mime_type": "audio/mpeg" if mime == "audio/mp3" else mime,
                                                         "data": base64.b64encode(f.read()).decode("ascii")}}]}],
                "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"}}
        try:
            resp, _tried = generate_content("text", body, key=key, timeout=90, env_vars=("GEMINI_AUDIO_MODEL",),
                                            label="Mix ConnectZ AI listen")
        except requests.RequestException:
            logger.exception("Mix AI: could not reach Gemini")
            return Response({"detail": "Couldn't reach the AI. Nothing was charged — try again."}, status=status.HTTP_502_BAD_GATEWAY)
        if resp is None or resp.status_code != 200:
            return Response({"detail": "The AI couldn't hear that clip. Nothing was charged."}, status=status.HTTP_502_BAD_GATEWAY)
        try:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError):
            text = ""
        got = parse(text)
        if not got:
            return Response({"detail": "The AI's answer couldn't be read. Nothing was charged — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        charged = _bill(request.user, "Mix ConnectZ AI listen", count_daily=True)
        if charged is None:
            return Response({"detail": "Not enough PromptZ or balance for an AI listen."}, status=status.HTTP_402_PAYMENT_REQUIRED)
        g = GENRES[got["genre"]]
        return Response({"genre": got["genre"], "genre_label": g["label"], "genre_why": g["why"], "heard": got["heard"],
                         "moves": got["moves"], "settings": apply_moves(got["genre"], got["moves"]),
                         "charged_cents": charged})
