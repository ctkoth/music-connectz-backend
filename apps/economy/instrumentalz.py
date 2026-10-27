"""Instrumental ConnectZ — the IntelligenceZ MIDI writer.

A member picks a genre, instruments, a BPM and a key; the model composes the
parts as NOTES (JSON), and this module turns them into a Standard MIDI File.
The model never writes bytes — every note is validated here, so a bad answer
is refused rather than shipped as a corrupt file.

Every key carries a mood description in K-Oth's personal register, and StatZ
members can search keys by mood. The key list and its moods live here and are
served, so the screen never retypes them.

Billing follows Sentence ConnectZ: price published before the run, a free
daily prompt first, nothing charged for an answer that doesn't parse. The
piece is the member's to use in CollabZ, BattleZ or DistributeZ, where K-Oth's
royalty is a flat ROYALTY_PCT — a MIDI isn't edited in-app, so there is no
"how much of the original survives" to scale it by.
"""
import json
import logging
import re
import struct

import requests
from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .priorities import clause as priorities_clause
from .catalog import ai_cost, over_char_limit
from .deadline import Deadline, Expired
from .gemini import _bill, _key, generate_content
from .models import (InstrumentalWork, membership_for, can_afford_ai, daily_prompt_covers,
                     daily_prompt_state)

logger = logging.getLogger(__name__)

ROYALTY_PCT = 10
BPM_MIN, BPM_MAX = 60, 200
BARS = (4, 8)
MAX_TRACKS = 6
MAX_NOTES = 400
# How long a member may be kept waiting for one POST, start to finish. The
# screen used to give up at 30s while the server let the model run for 90 and
# then charged and saved a piece nobody was waiting for any more. The screen
# reads this from GET and waits LONGER than it (a server that answers in time
# must always be the one that decides), and the model call takes what is left
# of it rather than a number of its own — see deadline.py for why.
BUDGET_SECONDS = 60
TPB = 480  # ticks per beat

# General MIDI programs. Drums ride channel 10 (index 9) and take no program.
INSTRUMENTS = {
    "piano": {"label": "Piano", "program": 0},
    "epiano": {"label": "Electric piano", "program": 4},
    "organ": {"label": "Organ", "program": 16},
    "acoustic_guitar": {"label": "Acoustic guitar", "program": 25},
    "electric_guitar": {"label": "Electric guitar", "program": 27},
    "bass": {"label": "Bass", "program": 33},
    "synth_bass": {"label": "Synth bass", "program": 38},
    "strings": {"label": "Strings", "program": 48},
    "choir": {"label": "Choir pad", "program": 52},
    "brass": {"label": "Brass", "program": 61},
    "lead": {"label": "Synth lead", "program": 80},
    "pad": {"label": "Synth pad", "program": 88},
    "drums": {"label": "Drums", "program": None},
}

# Each key's mood, in K-Oth's personal register: values-first, transparent,
# thinking about what lasts. Tags feed the mood search.
KEYS = [
    ("C major", "Clean slate. Nothing hidden — the honest first draft you build a legacy on.", "bright honest hopeful simple fresh"),
    ("G major", "Open road with the windows down. Confidence that doesn't need to prove anything.", "bright confident free uplifting"),
    ("D major", "Victory lap energy — loud, proud and earned, not borrowed.", "triumphant bright energetic proud"),
    ("A major", "Sunlight on the come-up. Warm ambition that still remembers where it started.", "warm hopeful ambitious bright"),
    ("E major", "Electric and wide awake. The moment the plan finally starts working.", "energetic bright exciting electric"),
    ("B major", "Overflowing. So much feeling it spills — joy that's almost too much.", "ecstatic bright intense joyful"),
    ("F# major", "Rare air. Reaching for something most people never try for.", "dreamy bright rare aspirational"),
    ("Db major", "Velvet and soft lights. Grown, smooth, saying it gently because it's true.", "smooth warm romantic soulful"),
    ("Ab major", "Gratitude. Looking back at the road and thanking the people who walked it with you.", "warm grateful nostalgic tender"),
    ("Eb major", "Heroic but humble. Standing tall for the people counting on you.", "heroic warm noble strong"),
    ("Bb major", "Church-steps optimism. Faith in the work, faith in the future.", "hopeful soulful warm faithful"),
    ("F major", "Front porch peace. Simple, rooted, at home in who you are.", "calm peaceful warm pastoral"),
    ("A minor", "Real talk at 2am. Sad, but honest about it — no fronting.", "sad honest reflective melancholy"),
    ("E minor", "Grinding through it. Pain turned into fuel and a plan.", "dark determined gritty moody"),
    ("B minor", "Lonely highway. Missing someone and still choosing to keep going.", "lonely melancholy longing dark"),
    ("F# minor", "Tension in the air. Something's about to break, for better or worse.", "tense dark suspense moody"),
    ("C# minor", "Heartbreak with dignity. It hurts, and you still won't lie about it.", "heartbroken sad emotional dramatic"),
    ("G# minor", "Midnight paranoia. Watching your back and your mind at the same time.", "dark anxious eerie tense"),
    ("Eb minor", "Deep water. The heaviest truths, said slowly so they land.", "heavy dark deep somber"),
    ("Bb minor", "Smoky and street-wise. Cold on the outside, loyal underneath.", "dark cool gritty street"),
    ("F minor", "Storm warning. Anger with a reason and a target.", "angry dark aggressive intense"),
    ("C minor", "Fate calling. Serious, cinematic, the stakes are your whole life.", "dramatic dark epic serious"),
    ("G minor", "Reflective resolve. Owning your mistakes so you don't repeat them.", "reflective sad determined serious"),
    ("D minor", "The saddest key, and it knows it. Mourning that respects what was lost.", "sad mournful somber emotional"),
]
KEY_NAMES = [k for k, _, _ in KEYS]
_KEY_ROOT = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6,
             "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def key_list():
    return [{"key": k, "mood": m, "tags": t.split()} for k, m, t in KEYS]


def search_keys(query):
    words = [w for w in re.findall(r"[a-z]+", (query or "").lower()) if len(w) > 2]
    if not words:
        return []
    scored = []
    for k, m, t in KEYS:
        hay = f"{m.lower()} {t}"
        score = sum(2 if w in t.split() else 1 for w in words if w in hay)
        if score:
            scored.append((score, {"key": k, "mood": m, "tags": t.split()}))
    return [x for _, x in sorted(scored, key=lambda s: -s[0])]


def can_search_mood(user):
    from .statz_trial import has_statz
    return has_statz(user)


def key_signature(key):
    """(sharps/flats count, minor flag) for the MIDI key-signature meta event."""
    name, mode = key.split()
    minor = mode == "minor"
    root = _KEY_ROOT[name]
    major_root = (root + 3) % 12 if minor else root
    order = {0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6, 1: -5, 8: -4, 3: -3, 10: -2, 5: -1}
    sf = order[major_root]
    # Six sharps and six flats are the same key on a keyboard, so the table can
    # only hold one of them; it holds sharps. A key SPELLED with a flat (Eb
    # minor, whose relative major is Gb) wants the flat side, or a score shows
    # D# minor — seven-note names nobody reads — for a member who picked Eb.
    if abs(sf) == 6 and len(name) > 1 and name[1] == "b":
        sf = -6
    return sf, 1 if minor else 0


def prompt_for(genre, instruments, bpm, key, bars, brief="", priorities=None):
    mood = dict((k, m) for k, m, _ in KEYS)[key]
    parts = ", ".join(f'"{i}" ({INSTRUMENTS[i]["label"]})' for i in instruments)
    return (
        f"Compose an original {bars}-bar instrumental loop in 4/4 at {bpm} BPM, key of {key}, "
        f"genre: {genre or 'any'}. Mood of the key: {mood}\n"
        + (f"Brief from the artist: {brief}\n" if brief else "")
        + (priorities_clause("instrumental", priorities).lstrip("\n") + "\n" if priorities else "")
        + f"Write one part for each of these instruments: {parts}.\n"
        "Reply with JSON only, shaped exactly like:\n"
        '{"tracks": [{"instrument": "<one of the ids above>", '
        '"notes": [[pitch, start_beat, length_beats, velocity], ...]}]}\n'
        f"pitch is a MIDI note number 0-127; start_beat is from 0 to {bars * 4} (quarter-note beats, "
        "decimals allowed); velocity 1-127. Stay in the key. For drums use General MIDI drum notes "
        "(36 kick, 38 snare, 42 closed hat, 46 open hat, 49 crash). Make the bass lock with the kick, "
        "give the harmony real chord movement, and make the loop repeat seamlessly."
    )


def _first_json(raw):
    raw = (raw or "").strip()
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        return json.loads(m.group(0) if m else raw)
    except (ValueError, AttributeError):
        return None


def clean_tracks(data, instruments, bars):
    """The model's answer, validated note by note. [] when nothing usable."""
    beats = bars * 4
    out = []
    for t in (data or {}).get("tracks") or []:
        if not isinstance(t, dict):
            continue
        inst = str(t.get("instrument", ""))
        if inst not in instruments or any(o["instrument"] == inst for o in out):
            continue
        notes = []
        for n in (t.get("notes") or [])[:MAX_NOTES]:
            try:
                pitch, start, length, vel = int(n[0]), float(n[1]), float(n[2]), int(n[3])
            except (TypeError, ValueError, IndexError):
                continue
            if not (0 <= pitch <= 127 and 0 <= start < beats and length > 0):
                continue
            notes.append([pitch, round(start, 3), round(min(length, beats - start), 3), max(1, min(127, vel))])
        if notes:
            out.append({"instrument": inst, "notes": sorted(notes, key=lambda x: x[1])})
        if len(out) >= MAX_TRACKS:
            break
    return out


def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def _chunk(kind, data):
    return kind + struct.pack(">I", len(data)) + data


def _track(events):
    """events: (tick, bytes) — sorted, delta-encoded, end-of-track appended."""
    data, last = b"", 0
    for tick, ev in sorted(events, key=lambda e: (e[0], e[1][0] & 0xF0 != 0x80)):
        data += _vlq(tick - last) + ev
        last = tick
    return _chunk(b"MTrk", data + b"\x00\xff\x2f\x00")


def midi_bytes(tracks, bpm, key, title=""):
    """A format-1 Standard MIDI File: a tempo track, then one track per part."""
    sf, mi = key_signature(key)
    tempo = int(60_000_000 / bpm)
    meta = [(0, b"\xff\x51\x03" + tempo.to_bytes(3, "big")),
            (0, b"\xff\x58\x04\x04\x02\x18\x08"),
            (0, b"\xff\x59\x02" + struct.pack("b", sf) + bytes([mi]))]
    if title:
        name = title.encode("utf-8")[:120]
        meta.append((0, b"\xff\x03" + _vlq(len(name)) + name))
    chunks = [_track(meta)]
    ch = 0
    for t in tracks:
        drums = t["instrument"] == "drums"
        channel = 9 if drums else ch
        if not drums:
            ch = ch + 1 if ch + 1 != 9 else ch + 2
        evs = []
        label = INSTRUMENTS[t["instrument"]]["label"].encode()
        evs.append((0, b"\xff\x03" + _vlq(len(label)) + label))
        if not drums:
            evs.append((0, bytes([0xC0 | channel, INSTRUMENTS[t["instrument"]]["program"]])))
        for pitch, start, length, vel in t["notes"]:
            on = int(start * TPB)
            off = max(on + 1, int((start + length) * TPB))
            evs.append((on, bytes([0x90 | channel, pitch, vel])))
            evs.append((off, bytes([0x80 | channel, pitch, 0])))
        chunks.append(_track(evs))
    header = _chunk(b"MThd", struct.pack(">HHH", 1, len(chunks), TPB))
    return header + b"".join(chunks)


def missing_parts(asked, tracks):
    """Instrument ids that were asked for and are not in the tracks that were kept."""
    kept = {t.get("instrument") for t in tracks or [] if isinstance(t, dict)}
    return [i for i in asked or [] if i not in kept]


def _work_dict(w):
    return {"id": w.id, "genre": w.genre, "instruments": w.instruments, "bpm": w.bpm, "key": w.key,
            "bars": w.bars, "brief": w.brief, "tracks": w.tracks, "created_at": w.created_at.isoformat(),
            # A loop short of a requested part is billed in full (one model run
            # was made either way), so the screen must say WHICH parts are not
            # in the file rather than leave a member to count tracks.
            "missing": missing_parts(w.instruments, w.tracks),
            "royalty_pct": ROYALTY_PCT}


def _text_of(resp):
    try:
        parts = resp.json()["candidates"][0]["content"]["parts"]
    except Exception:
        return ""
    return "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()


class InstrumentalView(APIView):
    """GET: instruments, keys and moods, price, your pieces. POST: compose one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cost = ai_cost("standard")
        allowance, _, daily_left = daily_prompt_state(request.user)
        free = daily_left > 0 and daily_prompt_covers(cost)
        return Response({
            "configured": bool(_key()),
            "instruments": [{"id": k, "label": v["label"]} for k, v in INSTRUMENTS.items()],
            "keys": key_list(),
            "bpm": [BPM_MIN, BPM_MAX], "bars": list(BARS), "max_tracks": MAX_TRACKS,
            "budget_seconds": BUDGET_SECONDS,
            "cost_cents": cost, "free_today": free, "daily_remaining": daily_left,
            "daily_allowance": allowance,
            "can_run": bool(_key()) and (free or can_afford_ai(request.user, cost)),
            "mood_search": can_search_mood(request.user),
            "inspiration_note": INSPIRATION_NOTE,
            "royalty_pct": ROYALTY_PCT,
            "royalty_rule": (f"Using one in DistributeZ, CollabZ or BattleZ pays K-Oth {ROYALTY_PCT}% "
                             "of what you earn from it."),
            "works": [_work_dict(w) for w in InstrumentalWork.objects.filter(user=request.user)[:20]],
        })

    def post(self, request):
        deadline = Deadline(BUDGET_SECONDS)
        d = request.data or {}
        genre = str(d.get("genre", "")).strip()[:60]
        brief = str(d.get("brief", "")).strip()
        cap = over_char_limit(brief, membership_for(request.user).tier)
        if cap:
            return Response({"detail": f"Your tier writes up to {cap:,} characters here — upgrade in MembershipZ for more.", "char_limit": cap},
                            status=status.HTTP_400_BAD_REQUEST)
        instruments = [i for i in dict.fromkeys(d.get("instruments") or []) if i in INSTRUMENTS][:MAX_TRACKS]
        key = str(d.get("key", ""))
        try:
            bpm, bars = int(d.get("bpm")), int(d.get("bars") or 4)
        except (TypeError, ValueError):
            return Response({"detail": "BPM must be a number."}, status=status.HTTP_400_BAD_REQUEST)
        if not instruments:
            return Response({"detail": "Pick at least one instrument."}, status=status.HTTP_400_BAD_REQUEST)
        if key not in KEY_NAMES:
            return Response({"detail": "Pick a key."}, status=status.HTTP_400_BAD_REQUEST)
        if not BPM_MIN <= bpm <= BPM_MAX:
            return Response({"detail": f"BPM between {BPM_MIN} and {BPM_MAX}."}, status=status.HTTP_400_BAD_REQUEST)
        if bars not in BARS:
            return Response({"detail": "4 or 8 bars."}, status=status.HTTP_400_BAD_REQUEST)

        api_key = _key()
        if not api_key:
            return Response({"detail": "Instrumental ConnectZ isn't switched on — the backend is missing GEMINI_API_KEY."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        cost = ai_cost("standard")
        _, _, daily_left = daily_prompt_state(request.user)
        free = daily_left > 0 and daily_prompt_covers(cost)
        if cost and not free and not can_afford_ai(request.user, cost):
            return Response({"detail": "Not enough PromptZ or balance for this one.", "cost_cents": cost},
                            status=status.HTTP_402_PAYMENT_REQUIRED)

        body = {"contents": [{"parts": [{"text": prompt_for(genre, instruments, bpm, key, bars, brief, d.get("priorities"))}]}],
                "generationConfig": {"temperature": 0.9, "responseMimeType": "application/json"}}
        try:
            deadline.check("the request was still being prepared when the time ran out")
            resp, tried = generate_content("text", body, key=api_key, timeout=deadline.remaining(cap=90),
                                           label="Instrumental ConnectZ")
            # `generate_content` walks a chain of models with ONE timeout each,
            # so a call can overrun the budget by more than it was given. An
            # answer that lands after the member's wait is over is not billed:
            # they were told it was still running, and nothing here is theirs.
            deadline.check("the composer was still going when the time ran out")
        except Expired as e:
            logger.warning("Instrumental ConnectZ: over budget after %.0fs — %s", deadline.spent(), e.message)
            return Response({"detail": f"The composer is taking longer than it should — {e.message}. "
                                       "Nothing was charged. Try again, or pick fewer instruments.",
                             "timed_out": True, "waited_seconds": int(deadline.spent())},
                            status=status.HTTP_504_GATEWAY_TIMEOUT)
        except requests.RequestException:
            logger.exception("Instrumental ConnectZ: could not reach Gemini")
            return Response({"detail": "Couldn't reach the composer. Nothing was charged — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        ok = resp is not None and resp.status_code == 200
        tracks = clean_tracks(_first_json(_text_of(resp)) if ok else None, instruments, bars)
        if not tracks:
            logger.error("Instrumental ConnectZ: unusable answer %s model=%s — %s",
                         getattr(resp, "status_code", 0), ", ".join(tried), getattr(resp, "text", "")[:300])
            return Response({"detail": "The composer's answer wasn't a usable loop. Nothing was charged — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)

        charged = _bill(request.user, f"Instrumental ConnectZ — {key}, {bpm} BPM", count_daily=True)
        if charged is None:
            return Response({"detail": "Not enough PromptZ or balance for this one.", "cost_cents": cost},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        work = InstrumentalWork.objects.create(user=request.user, genre=genre, instruments=instruments,
                                               bpm=bpm, key=key, bars=bars, brief=brief, tracks=tracks)
        return Response({**_work_dict(work), "charged_cents": charged}, status=status.HTTP_201_CREATED)


class InstrumentalMoodView(APIView):
    """GET ?q= — keys whose mood matches. StatZ."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_search_mood(request.user):
            return Response({"detail": "Searching keys by mood is a StatZ feature. Every key and its mood is "
                                       "still listed for you to pick from.", "tier": "statz"},
                            status=status.HTTP_403_FORBIDDEN)
        return Response({"results": search_keys(request.query_params.get("q", ""))})


class InstrumentalMidiView(APIView):
    """GET — the piece as a .mid file."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        w = InstrumentalWork.objects.filter(pk=pk, user=request.user).first()
        if not w:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        title = f"{w.genre or 'Instrumental'} in {w.key} at {w.bpm} BPM"
        resp = HttpResponse(midi_bytes(w.tracks, w.bpm, w.key, title), content_type="audio/midi")
        # "#" would be dropped as punctuation and F# minor would download as
        # "f-minor", the name of a different key. Spell the sharp out first.
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower().replace("#", " sharp ")).strip("-")[:60] or "instrumental"
        resp["Content-Disposition"] = f'attachment; filename="{slug}.mid"'
        return resp


# ---- Inspiration: a song you want your instrumental to feel like ----------

INSPIRATION_NOTE = ("Use music you have the right to analyse. The coach listens to the song to suggest a "
                    "setup — genre, tempo, key, instruments and a brief. It does NOT copy the melody or "
                    "chords: you still compose a new, original loop, which is priced separately. The song "
                    "isn't kept.")


def inspiration_prompt(lyrics=""):
    kinds = ", ".join(f'"{k}"' for k in INSTRUMENTS)
    keys = ", ".join(f'"{k}"' for k in KEY_NAMES)
    return (
        "You are given a reference song. Describe the SETUP someone would need to write an ORIGINAL "
        "instrumental with the same feel. Do not transcribe or reproduce its melody, chords or lyrics.\n"
        + ("The instrumental must also sit well under these lyrics (the member's own): pick a tempo, key "
           "mood and arrangement density with room for the words, matching their line length and mood.\n"
           f"LYRICS:\n{lyrics}\n" if lyrics else "")
        + "Reply with JSON only, exactly:\n"
        '{"unscorable": <null, or one sentence if there is no music to hear>, "genre": "<short>", '
        f'"bpm": <integer {BPM_MIN}-{BPM_MAX}>, "key": "<one of: {keys}>", '
        f'"instruments": [<ids from: {kinds}>], "bars": <4 or 8>, '
        '"brief": "<2-3 sentences for the composer: feel, groove, space, dynamics - in your own words>", '
        '"feel": "<one sentence: what the reference does that this setup borrows>", '
        '"fits_lyrics": "<one sentence on how it leaves room for the lyrics, or empty>"}'
    )


def clean_inspiration(parsed):
    if not isinstance(parsed, dict):
        return None
    try:
        bpm = max(BPM_MIN, min(BPM_MAX, int(round(float(parsed.get("bpm"))))))
    except (TypeError, ValueError):
        return None
    key = str(parsed.get("key", "")).strip()
    if key not in KEY_NAMES:
        key = ""
    ins = [i for i in dict.fromkeys(parsed.get("instruments") or []) if i in INSTRUMENTS][:MAX_TRACKS]
    if not ins:
        return None
    bars = parsed.get("bars")
    return {"genre": str(parsed.get("genre", "")).strip()[:60], "bpm": bpm, "key": key,
            "instruments": ins, "bars": bars if bars in BARS else 4,
            "brief": str(parsed.get("brief", "")).strip()[:600],
            "feel": str(parsed.get("feel", "")).strip()[:300],
            "fits_lyrics": str(parsed.get("fits_lyrics", "")).strip()[:300]}


class InstrumentalInspirationView(APIView):
    """POST a reference song (+ optional lyrics) → a suggested setup. Nothing composed, nothing kept."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from rest_framework.parsers import FormParser, MultiPartParser
        from . import vocalcoach as vc
        f = request.FILES.get("reference")
        if not f or f.size == 0:
            return Response({"detail": "Pick the song you want it to feel like."}, status=status.HTTP_400_BAD_REQUEST)
        ct = (getattr(f, "content_type", "") or "").lower()
        mime = vc.gemini_mime(ct) if ct.startswith(("audio/", "video/")) else None
        if not mime:
            return Response({"detail": "Use an m4a, mp3, wav, ogg or mp4 file."}, status=status.HTTP_400_BAD_REQUEST)
        cap_mb, is_tier = vc.cap_for(request.user)
        if f.size > cap_mb * 1024 * 1024:
            return Response({"detail": f"That file is {f.size / (1024 * 1024):.0f}MB. " + vc.cap_why(cap_mb, is_tier)},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        lyrics = str(request.data.get("lyrics", "")).strip()[:4000]
        api_key = _key()
        if not api_key:
            return Response({"detail": "Instrumental ConnectZ isn't switched on."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        cost = ai_cost("standard")
        _, _, daily_left = daily_prompt_state(request.user)
        if cost and not daily_left and not can_afford_ai(request.user, cost):
            return Response({"detail": "Not enough PromptZ or balance for this one.", "cost_cents": cost},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        deadline = Deadline(BUDGET_SECONDS * 2)
        cleanup = None
        try:
            part, cleanup, why = vc._media_part(f, mime, vc._size_of(f), deadline=deadline)
            if why:
                return Response({"detail": f"Couldn't take that file — {why}. Nothing was charged."},
                                status=status.HTTP_502_BAD_GATEWAY)
            body = {"contents": [{"parts": [{"text": inspiration_prompt(lyrics)}, part]}],
                    "generationConfig": {"temperature": 0.3}}
            resp, _ = generate_content("text", body, key=api_key, timeout=deadline.remaining(cap=120),
                                       env_vars=("GEMINI_AUDIO_MODEL",), label="Instrumental Inspiration")
        except Expired as e:
            return Response({"detail": f"Taking longer than it should — {e.message}. Nothing was charged.",
                             "timed_out": True}, status=status.HTTP_504_GATEWAY_TIMEOUT)
        except requests.RequestException:
            return Response({"detail": "Couldn't reach the coach. Nothing was charged — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        finally:
            if cleanup:
                try:
                    cleanup()
                except Exception:  # pragma: no cover
                    logger.exception("Instrumental Inspiration: cleanup failed")
        parsed = _first_json(_text_of(resp)) if resp is not None and resp.status_code == 200 else None
        if isinstance(parsed, dict) and str(parsed.get("unscorable") or "").strip():
            return Response({"unscorable": str(parsed["unscorable"]).strip()[:300], "cost_cents": 0})
        out = clean_inspiration(parsed)
        if not out:
            return Response({"detail": "The coach's answer wasn't usable. Nothing was charged — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        charged = _bill(request.user, "Instrumental ConnectZ Inspiration — AI", count_daily=True)
        if charged is None:
            return Response({"detail": "Not enough PromptZ or balance for this one.", "cost_cents": cost},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        return Response({**out, "cost_cents": charged, "saved": False})
