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
* **A YouTube link can be either side; Spotify and SoundCloud links cannot, and the screen says
  so BEFORE the press.** The coach hears audio, and only YouTube can be handed to the model by
  address (Gemini watches a public video itself — nothing is downloaded here). Spotify and
  SoundCloud serve a player and never the audio, so there is nothing to hear; "reviewing" a
  song from its title would be invented detail, which is the substance rule's failure case. The
  link is parsed by `widgetz` (the same parser a link widget uses) and REBUILT from the video id,
  so nothing the member typed reaches the model but that id and a start time. Only a
  `LINK_WINDOW_SECONDS` window is read — a whole album upload would otherwise be the price of
  one comparison.
* **Using a post costs what coaching a post costs** (`vocalcoach.coach_post_energy`, ⚡) — ONCE,
  however many of the two sides are posts. Stated on the control before it is pressed,
  checked before the model runs, spent only after a usable result. A file, a FileZ upload
  or a journal entry costs no ⚡.
* **Both takes are rated and compared** (Corey's ask): every dimension and an overall, for the
  take AND the reference, on one scale so the numbers compare; `compare()` does the subtraction
  (who leads where, by how much) so the model rates and the server does the arithmetic.
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
import re
from urllib.parse import parse_qs, urlparse

import requests
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import ai_cost
from .deadline import COACH_BUDGET_SECONDS, Deadline, Expired
from .gemini import _bill, _key, generate_content
from .instruments import LYRIC_SCORE, profile_for_app, scores_for
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
# What a link can be, said before it is pressed. Served on GET; the screen retypes none of it.
LINK_WINDOW_SECONDS = 240
LINK_NOTE = ("A YouTube link works: the coach watches a public video from the address, and reads "
             f"the first {LINK_WINDOW_SECONDS // 60} minutes (or from the time in the link, like ?t=80). "
             "It has to be public — not private, age-restricted or removed.")
LINK_NO = ("The coach can't listen to {label} links: {label} gives out a player, never the audio, so "
           "there is nothing to hear and the coach won't guess from the title. Upload the file, pick a "
           "post, or use a YouTube link.")
NOT_A_LINK = ("That isn't a link the coach can listen to. Paste a YouTube link, or upload the file.")
LINK_SOURCES = [
    {"provider": "youtube", "label": "YouTube", "ok": True, "note": LINK_NOTE},
    {"provider": "spotify", "label": "Spotify", "ok": False, "why": LINK_NO.format(label="Spotify")},
    {"provider": "soundcloud", "label": "SoundCloud", "ok": False, "why": LINK_NO.format(label="SoundCloud")},
]
POST_NOTE = ("Using a post as either side costs {cost} ⚡ once. Nothing is written on the post "
             "and its file is read for this comparison only.")
LYRIC_NOTE = ("This describes how the reference writes — never its words. Rewrite your "
              "own lines in Sentence ConnectZ with it.")


LYRICS_DOOR_NOTE = ("Opens Sentence ConnectZ with this direction in the brief — add your own lyrics under it "
                    "and press Write. Nothing runs until you do. The reference's words are never sent. A "
                    "failed run is not charged. If you keep the result and use it in a release, battle or "
                    "deal, K-Oth's royalty applies to the part you keep.")


def _lyric_factors():
    """The lyric factors Inspiration compares — the coach's own five writing scores, then HookZ and
    FeelZ — each one a factor Sentence ConnectZ has a fixer for, so every row can say "improve yours"
    and mean a real writer. Labels are the coach's, so a factor reads the same on both screens."""
    from .sentencez import FIXERS, FIXER_FOR_DIM
    out = {}
    for dim in list(LYRIC_SCORE) + ["hook", "feelz"]:
        key = FIXER_FOR_DIM.get(dim)
        if not key:
            continue
        f = FIXERS[key]
        out[dim] = {"fixer": key, "label": LYRIC_SCORE.get(dim) or f"{f['label']} {f['emoji']}"}
    return out


LYRIC_COMPARE_NOTE = ("Both sets of words are rated on the same 1-10 scale. Improve yours opens Sentence ConnectZ's writer "
                      "for that one factor with what the inspiration does there — never its words.")


def _factor_rows(raw, factors, extra=()):
    """[{dim, label, take, reference, gap, leads, why, ...}] in the factor order, both numbers or the row
    is dropped (one track's score compares with nothing). `extra` names text keys kept beside them."""
    if not isinstance(raw, dict):
        return []
    rows = []
    for dim, f in factors.items():
        v = raw.get(dim)
        if not isinstance(v, dict):
            continue
        t, r = vc._clamp(v.get("take")), vc._clamp(v.get("reference"))
        if t is None or r is None:
            continue
        row = {"dim": dim, **f, "take": t, "reference": r, "gap": t - r, "leads": _side(t - r),
               "why": str(v.get("why", "")).strip()[:240]}
        for k in extra:
            row[k] = str(v.get(k, "")).strip()[:300]
        rows.append(row)
    return rows


def clean_lyric_scores(raw):
    """The lyric rows. Empty when the recordings had no words."""
    return _factor_rows(raw, _lyric_factors())


# How the voice is DELIVERED, apart from the words: the coach's own FeelZ tip kinds, minus the two that
# are production (mic & gear, room) — those are "eq" and "how_to" here. One list, so a delivery factor
# reads the same in Inspiration as in a low-FeelZ tip.
_DELIVERY_EMOJI = {"delivery": "🔥", "diction": "🔍", "projection": "📢", "phrasing": "🎼",
                   "dynamics": "📊", "pacing": "⏱️", "intention": "🎯"}


# RapZ also has FLOW — how the bars ride the beat, which is the rapper's delivery before anything else.
# Every other coach has a voice-free performance, so it gets CLARITY: whether every note is defined
# and heard, the instrument's own diction. One table, per-coach rows.
RAP_FLOW = {"flow": {"label": "Flow 🌊", "what": "how the bars ride the beat: cadence, pocket, switches"}}
CLARITY = {"clarity": {"label": "Clarity 🔍", "what": "whether every note is defined and heard, not smeared"}}


def _delivery_factors(app_key="singz"):
    """The performance factors for THIS coach: a voice gets the coach's own FeelZ tip kinds (RapZ adds
    Flow first); an instrument gets Clarity."""
    if profile_for_app(app_key).get("production"):
        return {}                       # a beat is not performed; its writing and mix are scored instead
    if not profile_for_app(app_key).get("lyrics"):
        return {k: {"label": v["label"]} for k, v in CLARITY.items()}
    voice = {k: {"label": f"{vc.FEELZ_TIP_KINDS[k]} {e}"} for k, e in _DELIVERY_EMOJI.items() if k in vc.FEELZ_TIP_KINDS}
    if app_key == "rapz":
        return {**{k: {"label": v["label"]} for k, v in RAP_FLOW.items()}, **voice}
    return voice


DELIVERY_COMPARE_NOTE = ("How each track is delivered, apart from the words, on the same 1-10 scale. The step under each is "
                         "free to practise; your next take's score is how you'll know it moved.")


def clean_delivery_scores(raw, app_key="singz"):
    """The delivery rows for this coach, each with `how` — one concrete step to close that gap."""
    return _factor_rows(raw, _delivery_factors(app_key), extra=("how",))


# The MIX, apart from the performance — every coach, because every recording is mixed. Each names the
# Mix ConnectZ control that moves it (an anchor on that screen), or Arsenal for reverb, or nothing at all:
# clipping and noise are fixed at the recording, and a door to a tool that cannot fix them is a dead end.
MIX_FACTORS = {
    "balance": {"label": "Balance ⚖️", "what": "levels between the parts — does each sit where it should"},
    "eq": {"label": "EQ 🎚️", "what": "tonal balance: lows, mids and highs (the regions are in EQ below)"},
    "compression": {"label": "Compression 🗜️", "what": "how hits land and how much the loud parts are held in — punch vs squash"},
    "loudness": {"label": "Loudness 📈", "what": "how loud the finished track is, and whether it is squashed"},
    "stereo": {"label": "Stereo width ↔️", "what": "how wide or narrow the mix sounds, and whether the low end stays centred"},
    "space": {"label": "Reverb & space 🌌", "what": "depth: how near or far each part sounds"},
    "clarity": {"label": "Clarity & separation 🔍", "what": "whether parts mask each other — mud, boxiness, a buried lead"},
    "clean": {"label": "Clean signal 🔇", "what": "noise, hiss, clipping and distortion that wasn't meant"},
}
_MIX_TARGET = {"eq": "mixz-match", "clarity": "mixz-match", "loudness": "mixz-settings", "stereo": "mixz-match",
               "compression": "mixz-dynamicz"}
MIX_COMPARE_NOTE = ("The mix of each track, apart from the performance, on the same 1-10 scale — heard, not metered. "
                    "Mix ConnectZ measures yours for real and is free on your device.")


def _mix_factors():
    return {k: {"label": v["label"]} for k, v in MIX_FACTORS.items()}


def clean_mix_scores(raw):
    """The mix rows, each with `how` — the move that closes it."""
    return _factor_rows(raw, _mix_factors(), extra=("how",))


def mix_doors(rows, app_key):
    """{dim: door} — the control that moves each mix factor, free (mastering runs on the device). Balance
    lands on VocalZ for a coach with a voice, the main settings otherwise; reverb is Arsenal's insert, as
    mastering does not add space; a clean signal has no door because no tool here can unclip a take."""
    voice = bool(profile_for_app(app_key).get("lyrics"))
    out = {}
    for x in rows:
        d = x["dim"]
        if d == "clean":
            continue
        if d == "space":
            out[d] = {"key": "arsenal", "label": "Add space in Arsenal", "tab": "arsenal", "target": "",
                      "carry": {}, "cost": None,
                      "note": "Free, on your device. Add the Reverb insert to the track in the Mix window."}
            continue
        target = "mixz-vocalz" if (d == "balance" and voice) else _MIX_TARGET.get(d, "mixz-settings")
        out[d] = {"key": "mixz", "label": "Fix it in Mix ConnectZ", "tab": "mixconnectz", "target": target,
                  "carry": {}, "cost": None, "note": "Free, mastered on your device. Nothing uploads unless you save it."}
    return out


MATCH_NOTE = ("Opens Mix ConnectZ with your track and the inspiration both loaded, on Match reference: it matches "
              "your EQ (tonal balance) and loudness to the inspiration. Compression (DynamicZ) and stereo width are "
              "controls you set beside it, guided by the rows above. Free, mastered on your device; nothing uploads "
              "unless you save. Reverb is not mastering — that is Arsenal.")
MATCH_NO_FILE = ("The inspiration is a link, and Mix ConnectZ needs the song's audio to match it, so only your track is "
                 "loaded — add the inspiration's file under Inspiration there.")


def match_mix_door(reference):
    """One door: mix the member's track toward the inspiration in Mix ConnectZ. `reference` is the side
    as described; a YouTube link has no audio file to hand over, and the door says so rather than
    pretending the match will happen."""
    link = (reference or {}).get("kind") == "link"
    return {"key": "mixmatch", "label": "Mix my song like the inspiration", "tab": "mixconnectz", "target": "mixz-match",
            "carry": {}, "cost": None, "with_reference": not link,
            "note": MATCH_NO_FILE if link else MATCH_NOTE}


# How each track is WRITTEN, apart from how well it is played: the instrument's own writing layer.
# Five shared ideas (hook, harmony, arrangement, feel, space) worded for each instrument, so a drummer is
# asked about a signature beat and sound choice rather than chords. A voice coach keeps its lyrics and
# adds the two non-lyric writing factors it has: SingZ Melody and ad-libs, RapZ cadence switches and ad-libs.
# Style-relative by instruction — space in jazz is not space in drill.
_SPACE = {"label": "Space 🌬️", "what": "rests between phrases; not over-playing"}
WRITING_BY_APP = {
    "guitarz": {"hook": {"label": "Riff 🪝", "what": "a riff or figure you would remember after one listen"},
                "harmony": {"label": "Chord choices 🎼", "what": "the chords and voicings chosen"},
                "arrangement": {"label": "Part writing 🏗️", "what": "rhythm part vs lead: what the part does in the song"},
                "feel": {"label": "Feel 🕺", "what": "pushing or laying back against the beat"},
                "space": _SPACE},
    "bassz": {"hook": {"label": "Bassline hook 🪝", "what": "a bassline you would hum"},
              "harmony": {"label": "Note choice 🎼", "what": "roots vs passing tones, outlining the chords"},
              "arrangement": {"label": "Part writing 🏗️", "what": "where it drops out, walks or doubles"},
              "feel": {"label": "Lock 🕺", "what": "locked to the kick and the groove"},
              "space": _SPACE},
    "keyz": {"hook": {"label": "Figure & melody 🪝", "what": "a figure or melody you would remember"},
             "harmony": {"label": "Harmony & voicing 🎼", "what": "chord colour and voice leading"},
             "arrangement": {"label": "Hands 🏗️", "what": "the left hand's and the right hand's roles"},
             "feel": {"label": "Comping feel 🕺", "what": "the rhythm of the comping against the beat"},
             "space": _SPACE},
    "drumz": {"hook": {"label": "Signature beat 🪝", "what": "a pattern you would recognise"},
              "sound": {"label": "Sound & tuning 🥁", "what": "the drum sounds and tuning chosen for the song"},
              "arrangement": {"label": "Builds & fills 🏗️", "what": "builds, drops and where the fills land in the form"},
              "feel": {"label": "Feel 🕺", "what": "swing vs straight, ahead of or behind the beat"},
              "space": {"label": "Space 🌬️", "what": "ghost notes vs silence; not filling every gap"}},
    "violinz": {"hook": {"label": "Line 🪝", "what": "a melodic line you would remember"},
                "harmony": {"label": "Double-stops & counter-melody 🎼", "what": "harmony played against the tune"},
                "arrangement": {"label": "Entrances 🏗️", "what": "when it enters and when it rests"},
                "feel": {"label": "Phrasing shape 🕺", "what": "rubato, the rise and fall of a phrase"},
                "space": {"label": "Breath in the phrase 🌬️", "what": "room between phrases"}},
    "singz": {"melody": {"label": "Melody 🎼", "what": "contour, hookiness, and how it uses the singer's range"},
              "adlibs": {"label": "Ad-libs & harmonies 🎶", "what": "backing vocals, stacks and ad-libs"}},
    "rapz": {"cadence": {"label": "Cadence switches 🔀", "what": "whether the pattern changes, or one flow runs the whole verse"},
             "adlibs": {"label": "Ad-libs 🗣️", "what": "ad-libs and doubles that lift the bars"}},
}
# A producer's writing is the beat itself: the loop that hooks, the lead line, the chords, how the sections
# are built and how it moves between them. Groove, sounds and mix are scored as ProduceZ's own dimensions,
# so they are not repeated here.
WRITING_BY_APP["producez"] = {
    "hook": {"label": "Loop hook 🪝", "what": "a loop or motif you would remember after one listen"},
    "melody": {"label": "Lead line 🎶", "what": "the topline-space melody or lead: contour, repetition, answer"},
    "harmony": {"label": "Chord choices 🎼", "what": "the chords, voicings and where they move"},
    "structure": {"label": "Structure 🏗️", "what": "sections and bar counts: intro, verse, hook, drop, outro"},
    "transitions": {"label": "Transitions ➡️", "what": "risers, fills, drops and mutes that carry one section into the next"},
}
# Winds and brass play a lead line, so their writing is the line itself: what it plays against the chords,
# when it answers or lays out, and the breath between phrases. One set for the four, worded for a horn.
_WINDS_WRITING = {
    "hook": {"label": "Line 🪝", "what": "a melodic line you would remember"},
    "harmony": {"label": "Note choice 🎼", "what": "the notes chosen against the chords — inside or outside"},
    "arrangement": {"label": "Entrances & answers 🏗️", "what": "when it plays, answers the lead, or lays out"},
    "feel": {"label": "Time feel 🕺", "what": "ahead of, on or behind the beat; swing or straight"},
    "space": {"label": "Breath in the phrase 🌬️", "what": "room between phrases"},
}
for _k in ("flutez", "saxz", "clarinetz", "trumpetz"):
    WRITING_BY_APP[_k] = _WINDS_WRITING
assert all(k in WRITING_BY_APP for k in __import__("apps.economy.instruments", fromlist=["INSTRUMENTS"]).INSTRUMENTS), \
    "a coach has no writing factors — add it to WRITING_BY_APP"

WRITING_COMPARE_NOTE = ("How each track is written — the parts chosen, not how well they are played — on the same 1-10 "
                        "scale, judged against the genre. The step under each is a change to try in your next take.")


def _writing_factors(app_key):
    return {k: {"label": v["label"]} for k, v in WRITING_BY_APP.get(app_key, {}).items()}


def clean_writing_scores(raw, app_key):
    """The writing rows for this coach, each with `how` — one concrete change to try in the writing."""
    return _factor_rows(raw, _writing_factors(app_key), extra=("how",))


def writing_doors(rows, app_key):
    """{dim: door} — a writing change is tried in a take, so the door is the coach's recorder, free to
    open. There is no writer door for an instrument part: Instrumental ConnectZ cannot take a part brief,
    and a button promising one would land nowhere."""
    label = profile_for_app(app_key)["label"]
    return {x["dim"]: {"key": "retake", "label": f"Try it in a new take — {label}", "tab": app_key,
                       "target": "bosstake-mic", "carry": {}, "cost": None,
                       "note": "Opens the recorder. Nothing runs until you send a take; the coach's price is on Send."}
            for x in rows}


def delivery_doors(rows, app_key):
    """{dim: door} — practising a delivery factor happens in a take, so the door opens the coach's own
    recorder (whose price is on its Send button, not here). Projection is breath support first, so it
    opens the free breath trainer. Free to open; nothing runs until the member sends a take."""
    from .takescorez import BREATH_DOOR
    label = profile_for_app(app_key)["label"]
    out = {}
    for x in rows:
        if x["dim"] == "projection":
            out[x["dim"]] = {**BREATH_DOOR, "label": "Train your breath (free)"}
        else:
            out[x["dim"]] = {"key": "retake", "label": f"Try it in a new take — {label}", "tab": app_key,
                             "target": "bosstake-mic", "carry": {}, "cost": None,
                             "note": "Opens the recorder. Nothing runs until you send a take; the coach's price is on Send."}
    return out


def lyric_compare(rows):
    """The server's subtraction over the lyric rows: who leads where, widest gap first."""
    return {"better": [x["dim"] for x in sorted(rows, key=lambda x: -x["gap"]) if x["gap"] > 0],
            "worse": [x["dim"] for x in sorted(rows, key=lambda x: x["gap"]) if x["gap"] < 0],
            "take_leads": sum(x["leads"] == "take" for x in rows),
            "reference_leads": sum(x["leads"] == "reference" for x in rows)}


def lyric_doors(rows, genre, price, app_key):
    """{dim: door} — every factor gets "Improve yours", opening its own fixer with the reason the
    inspiration is stronger there already in the brief. The price is the writer's, said on the door."""
    from .takescorez import fixer_door
    g = genre if genre != "unspecified" else ""
    out = {}
    for x in rows:
        d = fixer_door(app_key, x["dim"], genre=g, price=price)
        if not d:
            continue
        lead = (f"The inspiration scores {x['reference']} on {x['label']} and I score {x['take']}"
                if x["gap"] < 0 else f"I score {x['take']} on {x['label']} and the inspiration {x['reference']}")
        why = f" — {x['why']}" if x["why"] else ""
        d = {**d, "label": "Improve yours",
             "carry": {**d["carry"], "text": f"{lead}{why}. Help me improve mine (don't copy its words).\n\nMy bars:\n"}}
        out[x["dim"]] = d
    return out


REVISE_DOOR_NOTE = ("Opens Sentence ConnectZ's Fix my lyrics with the factors you picked. Paste your lyrics: only "
                    "those faults change and every other line stays word for word, so it is still your song. "
                    "Nothing runs until you press Write; a failed run is not charged. K-Oth's royalty can only "
                    "apply to a changed line you keep, never to your own words.")


def revise_door(rows, genre, price):
    """ONE door that edits the member's own lyrics, fixing only the factors they pick. Pre-picked with
    every factor the inspiration leads on (the widest gap first); the screen lets the member change
    that. Each picked factor carries the comparison's reason as a note — data, never the reference's
    words. None when there were no lyric rows to pick from."""
    if not rows:
        return None
    by_gap = sorted(rows, key=lambda x: x["gap"])
    return {"key": "revise", "label": "Fix my lyrics — only what I pick", "tab": "sentenceconnectz",
            "target": "sentencez-write",
            "carry": {"kind": "revise", "genre": genre if genre != "unspecified" else "",
                      "factors": [x["fixer"] for x in by_gap if x["gap"] < 0],
                      "notes": {x["fixer"]: x["why"] for x in rows if x["why"]}},
            "cost": {"resource": "promptz", "amount": price["amount"], "free_today": price["free_today"]},
            "note": REVISE_DOOR_NOTE}


def lyrics_door(direction, genre, price):
    """The paid writer, handed the lyric direction — with its price said before it is pressed.
    None when there is no direction (no words in the recordings). `price` is
    `crosspost.coach_price`, the same standard run Sentence ConnectZ charges."""
    if not direction:
        return None
    return {"key": "lyrics", "label": "Rewrite my lyrics toward the inspiration", "tab": "sentenceconnectz",
            "target": "sentencez-write",
            "carry": {"kind": "lyrics", "genre": genre if genre != "unspecified" else "",
                      "text": ("Rewrite my lyrics with this direction (the reference's words are not used):\n"
                               f"{direction}\n\nMy lyrics:\n")},
            "cost": {"resource": "promptz", "amount": price["amount"], "free_today": price["free_today"]},
            "note": LYRICS_DOOR_NOTE}


def _prompt(app_key, genre):
    p = profile_for_app(app_key)
    keys = list(scores_for(app_key))
    shape = ", ".join(f'"{k}": {{"take": <1-10>, "reference": <1-10>, "why": "<one sentence: what separates them here>"}}' for k in keys)
    dims = ", ".join(keys)
    regions = ", ".join(EQ_REGIONS)
    lyr = _lyric_factors() if p.get("lyrics") else {}
    lyric_shape = ", ".join(f'"{d}": {{"take": <1-10>, "reference": <1-10>, "why": "<one sentence: what separates them>"}}'
                            for d in lyr)
    dlv = _delivery_factors(app_key)
    _what = {**RAP_FLOW, **CLARITY}
    dlv_named = ", ".join(f"{d} ({_what[d]['what']})" if d in _what else d for d in dlv)
    delivery_shape = ", ".join(f'"{d}": {{"take": <1-10>, "reference": <1-10>, "why": "<one sentence: what separates them>", '
                               f'"how": "<one concrete step the member can practise to close it>"}}' for d in dlv)
    delivery_rule = (f"\nDELIVERY: rate how each PERFORMANCE is delivered, apart from the words, in \"delivery_scores\" — "
                     f"{dlv_named} — on the same 1-10 scale, each with what separates them and one step to close it. "
                     "Mic, room and mix belong in \"eq\" and \"how_to\", not here.\n" if dlv else "")
    delivery_line = f'"delivery_scores": {{{delivery_shape}}},\n  ' if dlv else ""
    mix_shape = ", ".join(f'"{d}": {{"take": <1-10>, "reference": <1-10>, "why": "<one sentence: what separates them>", '
                          f'"how": "<the move in that process: which control, which way, roughly how much>"}}' for d in MIX_FACTORS)
    mix_rule = ("\nMIX: rate the MIX of each track, apart from the performance, in \"mix_scores\" — "
                + "; ".join(f"{d} ({v['what']})" for d, v in MIX_FACTORS.items())
                + " — on the same 1-10 scale. A finished record usually mixes better than a home take; say what to change.\n")
    wrt = WRITING_BY_APP.get(app_key, {})
    writing_shape = ", ".join(f'"{d}": {{"take": <1-10>, "reference": <1-10>, "why": "<one sentence: what separates them>", '
                              f'"how": "<one concrete change to try in the writing>"}}' for d in wrt)
    writing_rule = ("\nWRITING: rate how each track is WRITTEN — the parts chosen, not how well they are played — in "
                    "\"writing_scores\" — " + "; ".join(f"{d} ({v['what']})" for d, v in wrt.items())
                    + f" — on the same 1-10 scale, judged against the genre ({genre}): what is right for one style is "
                    "wrong for another.\n" if wrt else "")
    writing_line = f'"writing_scores": {{{writing_shape}}},\n  ' if wrt else ""
    lyric_rule = (f"Rate the WORDS of both tracks on the same 1-10 scale in \"lyric_scores\" — {', '.join(lyr)} — "
                  "judging what is written and sung, never quoting it. If either track has no words, send {}. "
                  if lyr else "")
    lyric_line = f'"lyric_scores": {{{lyric_shape}}},\n  ' if lyr else ""
    produces = bool(p.get("production"))
    build_rule = ("""
BUILD PLAN: this member is a PRODUCER, and TRACK A is a beat or instrumental of theirs. Tell them how to make \
a song like TRACK B. "blueprint" is what you hear in the reference — tempo (BPM), key, feel, its sections with \
bar counts, and the sounds it is built from; leave anything you cannot actually tell as null, never guess a \
tempo or key. "build_plan" is 4-8 ordered steps for the member's OWN project, tied to where TRACK A differs \
(each names one dimension it trains or ""): what to do, why the reference works that way, and how — which \
control, which way, roughly how much, or what to listen for. Approach only: never the reference's melody, \
chord notes, samples or stems.
""" if produces else "")
    build_line = ('"blueprint": {"tempo_bpm": <number or null>, "key": "<e.g. F minor, or null>", "feel": "<swing, straight, pushed...>", '
                  '"sections": [{"name": "<intro|verse|hook|drop|bridge|outro>", "bars": <int or null>, "what": "<what happens>"}, ...], '
                  '"sounds": ["<a sound or instrument heard>", ...]},\n  '
                  '"build_plan": [{"what": "<the move>", "why": "<why the reference works that way>", "how": "<the steps>", '
                  '"targets": "<one scored dimension or empty>"}, ...],\n  ' if produces else "")
    take_word = ("the member's OWN beat" if produces else "the MEMBER'S OWN TAKE")
    return f"""You are the Music ConnectZ {p['coach']}. You are given TWO recordings, \
in this order: TRACK A is {take_word}, TRACK B is the INSPIRATION — a \
reference track they want to sound closer to. Each is announced by name just \
before it. Every "take" key below is TRACK A and every "reference" key is TRACK B; \
never swap them. The reference is another artist's finished record; the take is \
a developing performance. Genre: {genre}.

Start with "heard": one sentence per track describing what you actually hear in it \
(voice or instrument, tempo, energy, production), so the member can check you \
kept the two apart. Do not quote either track's words.

Rate BOTH recordings and compare them. Score every dimension, and the overall, \
for the take AND the reference on the SAME 1-10 scale, so the numbers compare: \
1-2 barely holding together, 3-4 a real attempt that keeps slipping, 5-7 solid \
and ordinary, 8 strong, 9 excellent, 10 a performance you would hold up as an \
example. A finished record will usually rate higher than a developing take; \
that gap is what you are here to explain, not a verdict on the member. The \
overall is not an average and never the weakest dimension: a real strength may \
carry one fixable rough spot, the way a listener hears it. Say what separates \
the take from the reference and what the member can do about it. Never tell the member their take \
is bad for not being a finished record, never call the reference perfect, and \
never invent detail you cannot hear. Production differences (room, mic, mix) \
belong in "eq" and "how_to", not in the performance readings.

DRILLS: give 2-4 practice drills that move the take TOWARD the reference on the \
dimensions where the reference is ahead, widest gap first. Each is something the \
member can do today with what they have, names the one dimension it trains (one \
of: {dims}), says how many minutes, and gives the steps. A drill is about the \
PERFORMANCE; mix and room moves stay in "eq" and "how_to".

If either file has no real performance (silence, talking, wrong file), set \
"unscorable" to one sentence saying which file and what you heard, and stop.

{build_rule}{mix_rule}{delivery_rule}{writing_rule}LYRICS: only if the recordings have words. {lyric_rule}Describe HOW the reference writes — \
rhyme habits, imagery, structure, point of view, line length, density — in your \
own words. NEVER quote, paraphrase line-by-line or reproduce any of the \
reference's lyrics. "lyric_direction" is an instruction the member's own writing \
can follow. If there are no words, leave it empty.

Return ONLY valid JSON, no markdown fence, in exactly this shape:
{{
  "heard": {{"take": "<one sentence: what TRACK A sounds like>", "reference": "<one sentence: what TRACK B sounds like>"}},
  "unscorable": <null, or one sentence>,
  "closeness": <0-100 integer: how near the SOUND and approach of the take is to the reference>,
  "closeness_why": "<one sentence on what drives that number>",
  "scores": {{{shape}}},
  "overall": {{"take": <1-10>, "reference": <1-10>, "take_why": "<one sentence: what most decides the take's number>", "reference_why": "<one sentence: what most decides the reference's number>"}},
  "summary": "<two sentences: the biggest gap and the easiest win>",
  "eq": [{{"region": "<one of: {regions}>", "direction": "<take needs: more | less | close>", "what": "<what you hear in each>", "how": "<the move: which control, which way, roughly how much>"}}, ...],
  "how_to": [{{"what": "<the gap>", "why": "<why the reference sounds the way it does>", "how": "<concrete steps>"}}, ...],
  "drills": [{{"name": "<short name>", "targets": "<one of: {dims}>", "minutes": <1-30 integer>, "why": "<what it closes between the take and the reference>", "how": "<the steps>"}}, ...],
  "keep": "<what the take already does that the reference does too, or does better>",
  "mix_scores": {{{mix_shape}}},
  {build_line}{delivery_line}{writing_line}{lyric_line}"lyric_direction": "<empty, or 2-4 sentences: how the reference writes, as an instruction for rewriting the member's own lines. No quotes from the reference.>"
}}"""


# HOW TO MAKE A SONG LIKE THE EXAMPLE (ProduceZ only). The blueprint is what the model hears in the
# reference — tempo, key, feel, form, sounds — each None when it cannot tell, because a BPM or key
# invented to fill the slot is a number somebody builds a session around. The steps are ordered moves
# for the member's own project; they describe the approach and never ask for the reference's notes,
# samples or stems. Nothing here is saved as the member's score.
BUILD_STEPS_MAX = 8
BUILD_NOTE = ("Heard from the recording, not metered — check the tempo against your own tool. This is the approach "
              "behind the reference, in your own sounds and notes; it never copies its melody, samples or stems.")


def _text(v, n):
    return str(v or "").strip()[:n]


def clean_blueprint(raw):
    """{tempo_bpm, key, feel, sections[{name,bars,what}], sounds[]} or None. Anything unheard is None/empty."""
    if not isinstance(raw, dict):
        return None
    try:
        bpm = float(raw.get("tempo_bpm"))
        bpm = int(round(bpm)) if 40 <= bpm <= 260 else None
    except (TypeError, ValueError):
        bpm = None
    secs = []
    for it in raw.get("sections") if isinstance(raw.get("sections"), list) else []:
        if not isinstance(it, dict) or len(secs) == 12 or not _text(it.get("name"), 40):
            continue
        try:
            bars = int(round(float(it.get("bars"))))
            bars = bars if 1 <= bars <= 128 else None
        except (TypeError, ValueError):
            bars = None
        secs.append({"name": _text(it.get("name"), 40), "bars": bars, "what": _text(it.get("what"), 200)})
    sounds = [_text(x, 80) for x in (raw.get("sounds") if isinstance(raw.get("sounds"), list) else [])[:10] if _text(x, 80)]
    out = {"tempo_bpm": bpm, "key": _text(raw.get("key"), 30) or None, "feel": _text(raw.get("feel"), 120) or None,
           "sections": secs, "sounds": sounds}
    return out if (bpm or out["key"] or out["feel"] or secs or sounds) else None


def clean_build_plan(raw, keys):
    """[{order, what, why, how, targets, open_in}] — at most BUILD_STEPS_MAX, `what` and `how` required.
    `targets` is one of the coach's own dimensions or ""; every step opens Arsenal (the DAW) except a
    mix step, which opens Mix ConnectZ — a step with nowhere to do it is a dead end."""
    out = []
    for it in raw[:20] if isinstance(raw, list) else []:
        if not isinstance(it, dict) or len(out) == BUILD_STEPS_MAX:
            continue
        what, how = _text(it.get("what"), 140), _text(it.get("how"), 500)
        if not what or not how:
            continue
        t = _text(it.get("targets"), 20).lower()
        t = t if t in keys else ""
        door = ({"tab": "mixconnectz", "target": "mixz-match", "label": "Do it in Mix ConnectZ"} if t == "mix" else
                {"tab": "arsenal", "target": "", "label": "Do it in Arsenal"})
        out.append({"order": len(out) + 1, "what": what, "why": _text(it.get("why"), 300), "how": how,
                    "targets": t, "open_in": {**door, "cost": None}})
    return out


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
            out[k] = {"take": t, "reference": r, "why": str(v.get("why", "")).strip()[:240]}
    return out


def _clean_overall(raw):
    """Both overall ratings, or None — never half of one (a lone number compares with nothing)."""
    if not isinstance(raw, dict):
        return None
    t, r = vc._clamp(raw.get("take")), vc._clamp(raw.get("reference"))
    if t is None or r is None:
        return None
    return {"take": t, "reference": r, "take_why": str(raw.get("take_why", "")).strip()[:300],
            "reference_why": str(raw.get("reference_why", "")).strip()[:300]}


def _side(diff):
    return "take" if diff > 0 else "reference" if diff < 0 else "even"


def compare(scores, overall):
    """The comparison, as arithmetic on the two sets of ratings — the model rates, the server
    subtracts. `gap` is take minus reference (negative = the reference is ahead); `closest` and
    `widest` name the dimensions where the take is nearest and furthest behind."""
    rows = [{"key": k, "take": v["take"], "reference": v["reference"], "gap": v["take"] - v["reference"],
             "leads": _side(v["take"] - v["reference"]), "why": v.get("why", "")} for k, v in scores.items()]
    out = {"dimensions": rows,
           "take_leads": sum(r["leads"] == "take" for r in rows),
           "reference_leads": sum(r["leads"] == "reference" for r in rows),
           "even": sum(r["leads"] == "even" for r in rows),
           "overall_gap": overall["take"] - overall["reference"] if overall else None,
           "overall_leads": _side(overall["take"] - overall["reference"]) if overall else None,
           "closest": None, "widest": None,
           # What is better and what is worse, said as lists so nobody has to read it off a grid:
           # `better` = where the take is ahead (biggest lead first), `worse` = where the reference
           # is (widest gap first). Even dimensions are in neither.
           "better": [r["key"] for r in sorted(rows, key=lambda r: -r["gap"]) if r["gap"] > 0],
           "worse": [r["key"] for r in sorted(rows, key=lambda r: r["gap"]) if r["gap"] < 0]}
    if rows:
        out["closest"] = max(rows, key=lambda r: r["gap"])["key"]
        widest = min(rows, key=lambda r: r["gap"])
        out["widest"] = widest["key"] if widest["gap"] < 0 else None
    return out


DRILL_MAX = 4


def clean_drills(raw, keys, worse=()):
    """[{name, targets, label, minutes, why, how}] — at most DRILL_MAX, `name` and `how` required,
    `targets` one of this coach's own dimensions or the drill is dropped (a drill for a dimension
    the coach does not score has no number to move, so nothing could say whether it worked).
    Ordered so drills for the widest gaps (`worse`, from the server's arithmetic) come first."""
    out, seen = [], set()
    for item in raw[:10] if isinstance(raw, list) else []:
        if not isinstance(item, dict) or len(out) == DRILL_MAX:
            continue
        name = str(item.get("name", "")).strip()[:80]
        how = str(item.get("how", "")).strip()[:500]
        target = str(item.get("targets", "")).strip().lower()
        if not name or not how or target not in keys or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            minutes = max(1, min(30, int(round(float(item.get("minutes"))))))
        except (TypeError, ValueError):
            minutes = None
        out.append({"name": name, "targets": target, "minutes": minutes,
                    "why": str(item.get("why", "")).strip()[:300], "how": how})
    rank = {k: i for i, k in enumerate(worse)}
    out.sort(key=lambda d: rank.get(d["targets"], len(rank)))
    return out


def _clean_heard(raw):
    """Both sentences, or None — one side described says nothing about whether they were swapped."""
    if not isinstance(raw, dict):
        return None
    t, r = str(raw.get("take") or "").strip()[:240], str(raw.get("reference") or "").strip()[:240]
    return {"take": t, "reference": r} if t and r else None


def clean_reply(parsed, app_key):
    """The whitelist: anything the model adds beyond this never reaches a screen."""
    keys = list(scores_for(app_key))
    scores = _clean_scores(parsed.get("scores"), keys)
    overall = _clean_overall(parsed.get("overall"))
    try:
        closeness = max(0, min(100, int(round(float(parsed.get("closeness"))))))
    except (TypeError, ValueError):
        closeness = None
    return {
        "heard": _clean_heard(parsed.get("heard")),
        "closeness": closeness,
        "closeness_why": str(parsed.get("closeness_why", "")).strip()[:300],
        "scores": scores,
        "overall": overall,
        "compare": (cmp := compare(scores, overall)),
        "summary": str(parsed.get("summary", "")).strip()[:500],
        "eq": _clean_eq(parsed.get("eq")),
        "how_to": vc.clean_practice(parsed.get("how_to")),
        "drills": clean_drills(parsed.get("drills"), keys, cmp["worse"]),
        "keep": str(parsed.get("keep", "")).strip()[:300],
        "lyric_direction": str(parsed.get("lyric_direction", "")).strip()[:600],
        "lyric_scores": (lyr := clean_lyric_scores(parsed.get("lyric_scores")) if profile_for_app(app_key).get("lyrics") else []),
        "lyric_compare": lyric_compare(lyr),
        "delivery_scores": (dl := clean_delivery_scores(parsed.get("delivery_scores"), app_key)),
        "delivery_compare": lyric_compare(dl),
        "writing_scores": (wr := clean_writing_scores(parsed.get("writing_scores"), app_key)),
        "writing_compare": lyric_compare(wr),
        "mix_scores": (mx := clean_mix_scores(parsed.get("mix_scores"))),
        "mix_compare": lyric_compare(mx),
        # ProduceZ only: how to make a song like the reference. Absent (not empty) for every other coach.
        **({"blueprint": clean_blueprint(parsed.get("blueprint")),
            "build_plan": clean_build_plan(parsed.get("build_plan"), keys),
            "build_note": BUILD_NOTE} if profile_for_app(app_key).get("production") else {}),
    }


class _Slot:
    """One side of the comparison, resolved to something the coach can read.

    `file` is open for reading when it is a stored file (closed by `close()`); `post` is set only when
    the side came from a post, because that is what costs ⚡ and what the result names; `link` is a
    YouTube address the model reads itself, with nothing for us to open or close.
    """
    def __init__(self, file, ctype, post=None, stored=None, link=None):
        self.file, self.ctype, self.post, self.stored, self.link = file, ctype, post, stored, link
        self.mime = vc.gemini_mime(ctype)

    @property
    def uploaded(self):
        return self.file is not None and self.stored is None and self.post is None and self.link is None

    @property
    def on_disk(self):
        """A file that is already stored here (post, FileZ, journal) — opened and closed by us."""
        return self.file is not None and not self.uploaded

    @property
    def title(self):
        if self.post is not None:
            return self.post.title
        if self.link is not None:
            return self.link["title"]
        if self.uploaded:   # a file from the device: its own name is the only title it has
            return str(getattr(self.file, "name", "") or "").rsplit("/", 1)[-1]
        return (self.stored or {}).get("title") or ""

    def opened(self):
        if self.on_disk:
            self.file.open("rb")

    def close(self):
        if self.on_disk:
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
        if self.link is not None:
            return {"kind": "link", "provider": self.link["provider"], "title": self.link["title"],
                    "url": self.link["url"], "start_seconds": self.link["start"]}
        if self.stored is not None:
            return {"kind": self.stored["kind"], "id": self.stored["id"], "title": self.stored.get("title", "")}
        return {"kind": "file", "title": getattr(self.file, "name", "") or ""}


_VIDEO_ID = re.compile(r"/embed/([A-Za-z0-9_-]{11})(?:$|[/?])")
_T = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$")


def _start_seconds(url):
    """Where in the video a pasted link starts: `?t=80`, `?t=1m20s` or `?start=80`. 0 when absent or odd."""
    try:
        q = parse_qs(urlparse(url).query or "")
    except ValueError:
        return 0
    raw = ((q.get("t") or q.get("start") or [""])[0] or "").strip().lower()
    m = _T.match(raw) if raw else None
    if not m or not any(m.groups()):
        return 0
    h, mi, sec = (int(g or 0) for g in m.groups())
    return min(h * 3600 + mi * 60 + sec, 6 * 3600)


def classify_link(url):
    """(slot_link, None) for a YouTube video the coach can watch, else (None, refusal sentence).

    Reuses `widgetz._player_for` — the parser that already decides which links are players — and then
    rebuilds the address from the video id alone. `youtube.com.evil.example` and a link with junk
    appended never reach this far with anything but the id.
    """
    from . import widgetz
    url = str(url or "").strip()[:500]
    if not url.lower().startswith(("http://", "https://")):
        return None, NOT_A_LINK
    spec = widgetz._player_for(url)
    if not spec:
        return None, NOT_A_LINK
    if spec["provider"] != "youtube":
        return None, LINK_NO.format(label=spec["label"])
    m = _VIDEO_ID.search(spec["src"] + "/")
    if not m:
        return None, NOT_A_LINK
    vid, start = m.group(1), _start_seconds(url)
    canonical = f"https://www.youtube.com/watch?v={vid}"
    return {"provider": "youtube", "id": vid, "url": canonical, "start": start,
            "title": f"YouTube video {vid}",
            "part": {"file_data": {"file_uri": canonical},
                     "video_metadata": {"start_offset": f"{start}s",
                                        "end_offset": f"{start + LINK_WINDOW_SECONDS}s"}}}, None


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
        link_url = request.data.get(f"{name}_url")
        if link_url in (None, ""):
            return None, None
        link, why = classify_link(link_url)
        if why:
            return None, Response({"detail": why, "link_unsupported": True, "side": name},
                                  status=status.HTTP_400_BAD_REQUEST)
        return _Slot(None, "video/mp4", link=link), None
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


def _announce(letter, role, side):
    """The line just before a recording: which track it is, and its title when it has one, so the
    model is never left to work out from order alone which file is the member's. Titles are the
    member's or a post's, so they are cut short and quoted as data."""
    title = (side.title or "").replace('"', "'").strip()[:80]
    return f"TRACK {letter} — {role}" + (f' (titled "{title}")' if title else "") + ":"


def run_match(app_key, take, ref, genre):
    """Send the two recordings to the coach and return `(cleaned_reply, None)`, or `(None, Response)`.

    The ONE place a comparison runs: the member's endpoint below and the no-account trial's
    (`trial_inspiration.py`) both call it, so what the coach is asked, how long it may take, what a
    failure says and what the reply is cleaned to can never differ between them. It bills nothing and
    writes nothing — the caller decides what a usable result costs. Every failure is a ready-made
    answer that already says nothing was charged; an `unscorable` Response carries that key in its data.
    Closes both slots and any Files API copies before returning, whichever way it goes.
    """
    deadline = Deadline(COACH_BUDGET_SECONDS)
    cleanups = []
    try:
        parts = []
        for side in (take, ref):
            if side.link is not None:
                parts.append(side.link["part"])
                continue
            side.opened()
            size = vc._size_of(side.file)
            if size == 0:
                return None, Response({"detail": f"\"{side.title or 'One of those files'}\" is empty. "
                                           "Nothing was charged."}, status=status.HTTP_400_BAD_REQUEST)
            part, cleanup, why = vc._media_part(side.file, side.mime, size, deadline=deadline)
            if cleanup:
                cleanups.append(cleanup)
            if why:
                return None, Response({"detail": f"The coach couldn't take that one — {why}. Nothing was charged."},
                                status=status.HTTP_502_BAD_GATEWAY)
            parts.append(part)
        sections = [f"{n.upper()} is a {LINK_WINDOW_SECONDS // 60}-minute section of a video, starting at "
                    f"{x.link['start'] // 60}:{x.link['start'] % 60:02d}. Judge only that section."
                    for n, x in (("the member's take", take), ("the reference", ref)) if x.link is not None]
        body = {"contents": [{"parts": [{"text": _prompt(app_key, genre) + ("\n\n" + " ".join(sections) if sections else "")},
                                        {"text": _announce("A", "THE MEMBER'S OWN TAKE", take)}, parts[0],
                                        {"text": "END OF TRACK A."},
                                        {"text": _announce("B", "THE INSPIRATION (reference)", ref)}, parts[1],
                                        {"text": "END OF TRACK B."}]}],
                "generationConfig": {"temperature": vc.COACH_TEMPERATURE}}
        deadline.check("the files were still uploading when the time ran out")
        resp, _tried = generate_content(
            "text", body, key=_key(),
            timeout=deadline.remaining(cap=300 if cleanups else 90),
            env_vars=("GEMINI_AUDIO_MODEL",), label=f"{app_key} match")
    except Expired as e:
        return None, Response({"detail": f"The comparison is taking longer than it should — {e.message}. "
                                   "Nothing was charged.", "timed_out": True},
                        status=status.HTTP_504_GATEWAY_TIMEOUT)
    except requests.RequestException:
        logger.exception("%s match: could not reach Gemini", app_key)
        return None, Response({"detail": "Couldn't reach the coach. Nothing was charged — try again."},
                        status=status.HTTP_502_BAD_GATEWAY)
    except Exception:
        logger.exception("%s match: files could not be read", app_key)
        # A stored side whose file has gone from storage: say so as a fact about the
        # FILE (410), write it down for the next member, and charge nothing.
        gone = [x for x in (take, ref) if x.on_disk]
        for x in gone:
            mark_upload_missing(getattr(x.file, "instance", None))
        if gone:
            where = ", ".join(f'"{x.title}"' for x in gone if x.title) or "one of those"
            return None, Response({"detail": f"The recording on {where} isn't on the server any more, so "
                                       "there's nothing to compare. Nothing was charged.",
                             "take_missing": True}, status=status.HTTP_410_GONE)
        return None, Response({"detail": "The coach couldn't read those files. Nothing was charged."},
                        status=status.HTTP_400_BAD_REQUEST)
    finally:
        take.close()
        ref.close()
        for c in cleanups:
            try:
                c()
            except Exception:  # pragma: no cover - tidiness, never a failure
                logger.exception("%s match: cleanup failed", app_key)

    if resp.status_code != 200:
        logger.error("%s match: Gemini %s — %s", app_key, resp.status_code, resp.text[:300])
        if take.link is not None or ref.link is not None:
            return None, Response({"detail": "The coach couldn't open that YouTube video. It has to be public — not "
                                       "private, age-restricted or removed. Nothing was charged.",
                             "link_unreachable": True}, status=status.HTTP_502_BAD_GATEWAY)
        return None, Response({"detail": "The coach couldn't read those files right now. Nothing was charged."},
                        status=status.HTTP_502_BAD_GATEWAY)
    try:
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, ValueError):
        return None, Response({"detail": "The coach's reply didn't come back readable. Nothing was charged."},
                        status=status.HTTP_502_BAD_GATEWAY)
    parsed = vc._parse(text)
    if parsed and str(parsed.get("unscorable") or "").strip():
        return None, Response({"unscorable": str(parsed["unscorable"]).strip()[:400], "reference": True,
                         "match": True, "cost_cents": 0, "saved": False})
    out = clean_reply(parsed or {}, app_key)
    if not parsed or out["closeness"] is None or not (out["eq"] or out["how_to"] or out["drills"] or out["summary"]):
        return None, Response({"detail": "The coach's reply didn't come back readable. Nothing was charged."},
                        status=status.HTTP_502_BAD_GATEWAY)
    return out, None


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
            "take_sources": ["file", "post", "upload", "journal", "link"],
            "reference_sources": ["file", "post", "upload", "link"],
            # Which links work, said before one is pasted. Only YouTube can be heard.
            "link_window_seconds": LINK_WINDOW_SECONDS,
            "link_note": LINK_NOTE,
            "link_sources": LINK_SOURCES,
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
        out, failed = run_match(self.app_key, take, ref, genre)
        if failed is not None:
            return failed
        if energy_cost:   # before the run's own up-to ⚡ (vocalcoach says why)
            spend_energy(request.user, energy_cost,
                         f"Inspiration with a post — {(post_sides[0].title or 'post')[:50]}",
                         app_key=self.app_key, target=f"post:{post_sides[0].post.id}")
        charged = _bill(request.user, note=f"{profile_for_app(self.app_key)['label']} Inspiration — AI",
                        count_daily=True)
        from .crosspost import coach_price   # read after the bill, so "free today" is today's truth
        price = coach_price(request.user)
        door = lyrics_door(out["lyric_direction"], genre, price)
        lyric_factor_doors = lyric_doors(out["lyric_scores"], genre, price, self.app_key)
        fix_door = revise_door(out["lyric_scores"], genre, price)
        delivery_factor_doors = delivery_doors(out["delivery_scores"], self.app_key)
        mix_factor_doors = mix_doors(out["mix_scores"], self.app_key)
        writing_factor_doors = writing_doors(out["writing_scores"], self.app_key)
        mix_match = match_mix_door(ref.describe()) if out["mix_scores"] else None
        return Response({**out, "match": True, "reference": True, "saved": False, "feature": LABEL,
                         "cost_cents": charged, "energy_cost": energy_cost, "lyrics_door": door, "lyric_doors": lyric_factor_doors, "revise_door": fix_door, "delivery_doors": delivery_factor_doors, "mix_doors": mix_factor_doors, "writing_doors": writing_factor_doors,
                         "writing_compare_note": WRITING_COMPARE_NOTE if out["writing_scores"] else "", "mix_match_door": mix_match,
                         "mix_compare_note": MIX_COMPARE_NOTE if out["mix_scores"] else "",
                         "delivery_compare_note": DELIVERY_COMPARE_NOTE if out["delivery_scores"] else "",
                         "lyric_compare_note": LYRIC_COMPARE_NOTE if out["lyric_scores"] else "",
                         "eq_note": EQ_NOTE, "lyric_note": LYRIC_NOTE, "genre": genre,
                         "sources": {"take": take.describe(), "reference": ref.describe()}})
