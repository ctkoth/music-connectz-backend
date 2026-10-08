"""PreferenceZ, SubstanceZ and ZodiacZ as apps of their own, plus the daily
horoscope behind a member's sign.

All three are DECLARED profile metrics that MembersView could already filter
on. What was missing was a way IN: each lived as a block inside the ProfileZ
form, so "who else here is a Scorpio" or "who drinks" meant knowing which of
VybeZ's dozen filters to set. Each is a screen now — every option, how many
members declared it, and the members behind any option one tap away.

Three rules, the same ones the profile fields already follow:

  * A count is of DECLARATIONS. Nothing is inferred, and nobody who hasn't said
    is counted as anything. `undeclared` travels with every list, so an empty
    tile reads as "nobody has said" rather than "nobody here".
  * SubstanceZ and PreferenceZ are adult-only, in both directions. Attraction
    already was (Play Families policy, `ADULT_ONLY_PROFILE_FIELDS`); listing
    members by heroin use to a fifteen-year-old, or listing a fifteen-year-old
    by theirs, is the same wall. A known minor gets the reason, never the list,
    and is never counted or matched.
  * The horoscope is labelled for what it is. It is a written reading for the
    day, not a measurement of anybody — nothing in it moves a rating, a skill
    level or a price, which is what makes it allowed under the substance rule.
    One reading per sign per day, written once and served to everybody with
    that sign, so twelve model calls a day is the whole cost and no member is
    ever charged for one.
"""
import datetime
import hashlib
import json
import logging
import re

import requests
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .audience import Audience
from .gemini import _key, generate_content
from .models import (Horoscope, Profile, adult_only_reason, blocked_user_ids,
                     profile_is_minor, zodiac_for)
from .social import ACTIVE_STANCES, clean_substances
from .substancez import FREQUENCIES, FREQUENCY_KEYS, SUBSTANCE_KEYS, SUBSTANCES, visible_substances
from .statz_trial import has_statz

logger = logging.getLogger(__name__)

# Order and dates exactly as the member reads them. `zodiac_for` uses the same
# cutoffs, so the date shown is the date that decides.
ZODIAC = [
    ("Aries", "♈", "March 21 – April 19"),
    ("Taurus", "♉", "April 20 – May 20"),
    ("Gemini", "♊", "May 21 – June 20"),
    ("Cancer", "♋", "June 21 – July 22"),
    ("Leo", "♌", "July 23 – August 22"),
    ("Virgo", "♍", "August 23 – September 22"),
    ("Libra", "♎", "September 23 – October 22"),
    ("Scorpio", "♏", "October 23 – November 21"),
    ("Sagittarius", "♐", "November 22 – December 21"),
    ("Capricorn", "♑", "December 22 – January 19"),
    ("Aquarius", "♒", "January 20 – February 18"),
    ("Pisces", "♓", "February 19 – March 20"),
]
SIGN_NAMES = [z[0] for z in ZODIAC]

# Corey's read on each sign, carried over from v2.2 (src/mcz2/zodiac.js), where
# it lived in a screen that is not mounted — so the live app had lost it.
SIGN_READ = {
    "Capricorn": "The grinder. You build the empire brick by brick — disciplined, ambitious, and quietly running the label while everyone else is freestyling.",
    "Aquarius": "The visionary. Weird in the best way — genre-bending ideas nobody else hears yet. You're already three sounds ahead of the trend.",
    "Pisces": "The dreamer. Pure emotion straight to the mic — your melodies feel like water. Protect that sensitivity; it's your whole sound.",
    "Aries": "The starter. First on the beat, first in the booth, first to drop. Raw energy and zero fear — you set the tempo for the whole room.",
    "Taurus": "The craftsman. You don't rush a mix — you build a groove that lasts. Loyal, luxurious, and stubborn enough to finish the album.",
    "Gemini": "The switch-hitter. Two flows, two moods, endless bars. You rap, you sing, you produce — versatility is your signature.",
    "Cancer": "The heart. Your music hits people right in the feelings — nostalgic hooks and home-grown loyalty. You build a real fanbase, not just streams.",
    "Leo": "The star. Born for the stage — presence for days. When you perform, the spotlight was already yours. Just don't forget the team.",
    "Virgo": "The perfectionist. You hear the one frequency that's off. Clean mixes, tight edits, flawless metadata — the engineer everyone needs.",
    "Libra": "The collaborator. You balance the room and make the feature happen. Great ear for harmony, better instinct for the right partnership.",
    "Scorpio": "The intensity. Deep, magnetic, all-in. Your music has a dangerous edge people can't stop replaying. You don't do half-effort.",
    "Sagittarius": "The explorer. Global sound, restless creativity — you'd cut a track on three continents. Freedom is the whole vibe.",
}
ELEMENT = {"Aries": "Fire", "Leo": "Fire", "Sagittarius": "Fire",
           "Taurus": "Earth", "Virgo": "Earth", "Capricorn": "Earth",
           "Gemini": "Air", "Libra": "Air", "Aquarius": "Air",
           "Cancer": "Water", "Scorpio": "Water", "Pisces": "Water"}
_COMPLEMENT = {"Fire": "Air", "Air": "Fire", "Earth": "Water", "Water": "Earth"}


def compatibility(a, b):
    """v2.2's element read on two signs, in Corey's voice. A horoscope's
    answer about two SIGNS — never a score on a person, never used to rank or
    filter anybody, which is what keeps it on the right side of the substance
    rule. Same element flows, Fire/Air and Earth/Water complement, the rest
    clash; opposite signs (six apart) get a spark."""
    if a not in ELEMENT or b not in ELEMENT:
        return None
    ea, eb = ELEMENT[a], ELEMENT[b]
    if a == b:
        score, note = 8, ("Two of the same sign — instant understanding, but you'll double each other's blind "
                          "spots. Mirror energy: powerful when aligned, loud when not.")
    elif ea == eb:
        score, note = 9, (f"Same element ({ea}) — you move at the same tempo and just get each other. Natural "
                          "creative chemistry; watch that you challenge, not just echo.")
    elif _COMPLEMENT[ea] == eb:
        score, note = 8, (f"{ea} + {eb} complement — opposite strengths that cover each other's gaps. This is "
                          "the collab that actually finishes the album.")
    else:
        score, note = 5, (f"{ea} + {eb} clash — different speeds and priorities. Real sparks either way; make "
                          "the friction the sound instead of the argument.")
    if abs(SIGN_NAMES.index(a) - SIGN_NAMES.index(b)) == 6:
        score = min(10, score + 1)
    return {"a": a, "b": b, "element_a": ea, "element_b": eb, "score": score, "out_of": 10, "note": note}


# The house reading — v2.2's deterministic one, in Corey's voice. It costs
# nothing and needs no key, so it is what a member gets when the written
# reading cannot be had (no key, the model down). Same sign + same day = same
# reading, for everybody, refreshed at midnight.
_VIBE = [
    "The stars cleared their throat for you today — energy's up, ego's in check, go make something.",
    "Today's a green light. The universe already signed off; you're just waiting on yourself.",
    "Slow morning, loud afternoon. Save the big move for when the room warms up.",
    "You're magnetic today — people are gonna reach out. Answer the ones that matter.",
    "Low-key power day. Nobody sees the grind but the results show up in a week.",
    "Creative floodgates are open. Catch the idea now, it won't knock twice.",
    "Cosmic curveball incoming — roll with it, don't fight it. The detour's the plot.",
]
_FOCUS = [
    "Lean into your craft — finish the thing you keep almost-finishing.",
    "Money's moving your way. Handle a payment, price your work, don't undersell.",
    "Collabs are blessed today. Slide in that DM, book the session.",
    "Post it. Your audience is listening louder than usual right now.",
    "Rest is the move. You can't pour from an empty 808.",
    "Learn one new thing today — a plugin, a chord, a trick. It compounds.",
    "Handle the boring admin — metadata, contracts, the follow-up email. Future you says thanks.",
]
_CAUTION = [
    "Watch the overthinking — first instinct's usually the hit.",
    "Don't chase clout today; the real ones aren't in the comments.",
    "Guard your energy — one draining conversation can eat the whole session.",
    "Don't drop it half-baked just because you're impatient. Let it breathe.",
    "Skip the comparison scroll — your timeline isn't your competition.",
    "Say no to one thing today so you can say yes to your work.",
]
_COLORS = ["Neon Pink", "Cyan", "Gold", "Purple", "Electric Blue", "Crimson", "Lime"]


def house_reading(sign, day):
    seed = int(hashlib.sha256(f"{sign}-{day.isoformat()}".encode()).hexdigest()[:8], 16)
    pick = lambda pool, off: pool[(seed + off) % len(pool)]
    same = [n for n in SIGN_NAMES if ELEMENT[n] == _COMPLEMENT[ELEMENT[sign]]]
    return {"overview": pick(_VIBE, 0), "music": pick(_FOCUS, 3), "wellbeing": pick(_CAUTION, 7),
            "mood": "", "lucky_color": pick(_COLORS, 5), "lucky_number": (seed % 9) + 1,
            "best_match": same[seed % len(same)], "source": "house"}

# The list lives in substancez.py (one list, served), imported above.

PARTNER_GENDERS = [
    ("male", "Male", "♂"),
    ("female", "Female", "♀"),
    ("nonbinary", "Non-binary", "⚧"),
]
PARTNER_KEYS = [g[0] for g in PARTNER_GENDERS]

KINDS = {
    "zodiacz": {"label": "ZodiacZ", "adult": False, "param": "signs",
                "say": "Your sign comes from your birthday in ProfileZ."},
    "substancez": {"label": "SubstanceZ", "adult": True, "param": "uses",
                   "say": "What members say they use, and how often. Declared by them, never guessed."},
    "preferencez": {"label": "PreferenceZ", "adult": True, "param": "attracted",
                    "say": "Who members say they're attracted to — one, two or all three."},
}


def _options(kind):
    if kind == "zodiacz":
        return [{"key": n, "label": n, "emoji": e, "dates": d, "element": ELEMENT[n], "read": SIGN_READ[n]}
                for n, e, d in ZODIAC]
    if kind == "substancez":
        return [{"key": k, "label": l, "emoji": e} for k, l, e in SUBSTANCES]
    return [{"key": k, "label": l, "emoji": e} for k, l, e in PARTNER_GENDERS]


def _declared(kind, p):
    """The option keys this profile has declared for `kind` — [] for none."""
    if kind == "zodiacz":
        sign = p.sign or zodiac_for(p.birthday)
        return [sign] if sign in SIGN_NAMES else []
    if kind == "substancez":
        subs = clean_substances(p.substances)
        return [k for k in SUBSTANCE_KEYS if subs.get(k) in ACTIVE_STANCES]
    return [k for k in PARTNER_KEYS if k in (p.attracted_to or [])]


def counts_for(kind, viewer):
    """{option: members who declared it}, how many declared nothing, and the
    viewer's own answer. Adults only on the adult kinds."""
    counts = {o["key"]: 0 for o in _options(kind)}
    # SubstanceZ only: how those declarations split by frequency. A count of
    # "12 use THC" hides whether that is twelve daily users or twelve people
    # who had it once; `unsaid` is the legacy "yes", kept as its own bucket
    # rather than folded into a frequency nobody chose.
    by_freq = {o["key"]: {f: 0 for f in FREQUENCY_KEYS + ["unsaid"]} for o in _options(kind)} \
        if kind == "substancez" else {}
    undeclared = sober = 0
    adult = KINDS[kind]["adult"]
    blocked = blocked_user_ids(viewer)
    profiles = list(Profile.objects.exclude(user_id__in=blocked).only(
        "sign", "birthday", "substances", "sober", "attracted_to", "verified_18plus", "user_id",
        "visibility"))
    # SubstanceZ counts are of what THIS viewer may know. A declaration the
    # member keeps private (the default) must not feed a number either: a tile
    # saying 5 over a list of 4 is a count that discloses the fifth, and the
    # setting reads "served to nobody but me".
    aud = Audience(viewer, [p.user_id for p in profiles]) if kind == "substancez" else None
    for p in profiles:
        if adult and profile_is_minor(p):
            continue
        if kind == "substancez":
            seen = visible_substances(p, viewer, aud)
            keys = [k for k in SUBSTANCE_KEYS if seen.get(k) in ACTIVE_STANCES]
        else:
            seen, keys = None, _declared(kind, p)
        for k in keys:
            counts[k] += 1
        if by_freq and keys:
            for k in keys:
                by_freq[k][seen[k] if seen[k] in FREQUENCY_KEYS else "unsaid"] += 1
        if not keys:
            # Sober by choice is a claim, not a blank: counted on its own and
            # kept out of "haven't said", or the footer reads as though
            # sober members had said nothing.
            if kind == "substancez" and p.sober:
                sober += 1
            else:
                undeclared += 1
    return counts, undeclared, sober, by_freq


def matches(kind, p, wanted, freqs=None, viewer=None, audience=None):
    """Whether profile `p` declared ANY of `wanted` for `kind`. OR within a
    metric, the rule every multi-select in MembersView already follows.

    SubstanceZ reads only what `viewer` may know (`visible_substances`: the
    adult wall, and the member's own VisibilitieZ setting). With no viewer it
    fails closed, as an anonymous one. `freqs` narrows to those declared at one
    of the listed frequencies; a legacy "yes" has no frequency to match, so it
    never passes a frequency filter — that would be a guess in the searcher's
    favour.
    """
    if KINDS[kind]["adult"] and profile_is_minor(p):
        return False
    if kind == "substancez":
        subs = visible_substances(p, viewer, audience)
        if freqs:
            return any(subs.get(k) in freqs for k in wanted)
        return any(subs.get(k) in ACTIVE_STANCES for k in wanted)
    return bool(set(wanted) & set(_declared(kind, p)))


class SubstanceScaleView(APIView):
    """GET /api/economy/substancez/ — the substances and the frequency scale.

    The one place both are defined for a screen. Deliberately NOT part of
    MetricZView: that answer is adult-gated and walks every profile for counts,
    and the profile editor needs only the two lists. Nothing here is about
    anybody; it is the vocabulary.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .substancez import scale
        return Response(scale())


class MetricZView(APIView):
    """GET /api/economy/metricz/<kind>/ — every option, its count, and yours."""

    permission_classes = [IsAuthenticated]

    def get(self, request, kind):
        spec = KINDS.get(kind)
        if not spec:
            return Response({"detail": "Unknown app."}, status=status.HTTP_404_NOT_FOUND)
        base = {"kind": kind, "label": spec["label"], "say": spec["say"], "param": spec["param"],
                "adult_only": spec["adult"]}
        if spec["adult"]:
            why = adult_only_reason(request.user)
            if why:
                return Response({**base, "locked": why, "options": []})
        counts, undeclared, sober, by_freq = counts_for(kind, request.user)
        me = getattr(request.user, "mcz_profile", None)
        mine = _declared(kind, me) if me else []
        my_subs = clean_substances(me.substances) if me and kind == "substancez" else {}
        out = {**base, "options": [
                   {**o, "count": counts[o["key"]], "mine": o["key"] in mine,
                    **({"by_frequency": by_freq[o["key"]],
                        # Yours, as you said it — None for the legacy "yes".
                        "my_frequency": my_subs.get(o["key"]) if my_subs.get(o["key"]) in FREQUENCY_KEYS else None}
                       if kind == "substancez" else {})}
                   for o in _options(kind)],
               "undeclared": undeclared, "mine": mine,
               # ProfileZ anchor that sets it — "nothing is a dead end".
               "set_in": {"tab": "profilez", "target": {"zodiacz": "birthday", "substancez": "substancez",
                                                         "preferencez": "preferencez"}[kind]}}
        if kind == "substancez":
            out["sober"] = sober
            out["frequencies"] = [{"key": k, "label": l, "hint": h} for k, l, h in FREQUENCIES]
        if kind == "zodiacz":
            out["today"] = timezone.localdate().isoformat()
        return Response(out)


# ---- The daily horoscope ---------------------------------------------------

SECTIONS = ("overview", "love", "music", "money", "wellbeing")
HOROSCOPE_NOTE = "A reading written for today — for fun and reflection, not a forecast."


def _prompt(sign, day):
    dates = dict((n, d) for n, _, d in ZODIAC)[sign]
    return (
        f"Write today's horoscope for {sign} ({dates}) for {day:%A, %B %d, %Y}, for members of "
        "Music ConnectZ — a social platform for musicians, producers, dancers and creatives. "
        "Warm, specific, grounded and a little playful; second person; no fatalism, no medical, "
        "legal or financial instructions, nothing about gambling or substances. "
        "Answer ONLY with JSON: {\"overview\": 3-4 sentences, \"love\": 2 sentences, "
        "\"music\": 2 sentences about creative work and collaboration, \"money\": 2 sentences, "
        "\"wellbeing\": 2 sentences, \"mood\": one or two words, \"lucky_color\": one colour, "
        "\"lucky_number\": an integer 1-99, \"best_match\": one of the twelve signs}"
    )


def _clean(data):
    if not isinstance(data, dict):
        return None
    out = {}
    for k in SECTIONS:
        v = str(data.get(k) or "").strip()
        if not v:
            return None
        out[k] = v[:900]
    out["mood"] = str(data.get("mood") or "")[:40]
    out["lucky_color"] = str(data.get("lucky_color") or "")[:30]
    try:
        n = int(data.get("lucky_number"))
        out["lucky_number"] = n if 1 <= n <= 99 else None
    except (TypeError, ValueError):
        out["lucky_number"] = None
    match = str(data.get("best_match") or "").strip().title()
    out["best_match"] = match if match in SIGN_NAMES else ""
    return out


# ---- The advanced reading (StatZ) ------------------------------------------
#
# Same rules as the daily one — a reading, never a measurement, written once
# per sign per day and shared — so the whole platform's cost is still at most
# 24 calls a day however many StatZ members open it. What it adds is DEPTH in
# the places members asked for (love and money), the next seven days, and the
# one thing this app has that a newspaper horoscope does not: who to MAKE
# something with. Every line it adds is somewhere a member can go and act.
ADV_SECTIONS = ("love_single", "love_partnered", "money_earning", "money_spending",
                "career", "challenge", "affirmation")


def _adv_prompt(sign, day):
    dates = dict((n, d) for n, _, d in ZODIAC)[sign]
    week = ", ".join(f"{(day + datetime.timedelta(days=i)):%A}" for i in range(7))
    return (
        f"Write today's ADVANCED horoscope for {sign} ({dates}) for {day:%A, %B %d, %Y}, for "
        "members of Music ConnectZ — musicians, producers, dancers, designers and other creatives. "
        "Deeper and more specific than a daily horoscope; warm, grounded, second person. No "
        "fatalism; no medical or legal advice; money talk stays about creative work (pricing a "
        "feature, chasing an invoice, choosing what to spend on) — never investments, gambling, "
        "loans or substances. Answer ONLY with JSON: {"
        "\"love_single\": 3 sentences for someone single, "
        "\"love_partnered\": 3 sentences for someone in a relationship, "
        "\"money_earning\": 3 sentences about earning from their art today, "
        "\"money_spending\": 2 sentences about what is and isn't worth spending on, "
        "\"career\": 3 sentences about their music or creative career, "
        "\"collab_signs\": [two of the twelve signs who are good to create with today], "
        "\"collab_why\": 1 sentence on why, "
        "\"friction_sign\": one sign to go gently with today, "
        "\"power_hours\": a short time window like \"7–9pm\" that suits creating today, "
        f"\"week\": an array of exactly 7 one-sentence notes, one each for {week}, "
        "\"challenge\": 1 sentence, a small creative challenge for today, "
        "\"affirmation\": 1 short first-person sentence}"
    )


def _clean_adv(data):
    if not isinstance(data, dict):
        return None
    out = {}
    for k in ADV_SECTIONS:
        v = str(data.get(k) or "").strip()
        if not v:
            return None
        out[k] = v[:900]
    signs = [str(x).strip().title() for x in (data.get("collab_signs") or []) if isinstance(x, str)]
    out["collab_signs"] = [x for x in signs if x in SIGN_NAMES][:2]
    out["collab_why"] = str(data.get("collab_why") or "")[:300]
    f = str(data.get("friction_sign") or "").strip().title()
    out["friction_sign"] = f if f in SIGN_NAMES else ""
    out["power_hours"] = str(data.get("power_hours") or "")[:30]
    week = [str(x).strip()[:300] for x in (data.get("week") or []) if str(x).strip()]
    if len(week) != 7:
        return None
    out["week"] = week
    return out


_LEVELS = {
    "basic": (_prompt, _clean, "ZodiacZ horoscope"),
    "advanced": (_adv_prompt, _clean_adv, "ZodiacZ advanced horoscope"),
}


def _write(sign, day, level="basic"):
    """One model call for one sign's day at one level. None when it can't be written."""
    key = _key()
    if not key:
        return None
    prompt, clean, label = _LEVELS[level]
    body = {"contents": [{"parts": [{"text": prompt(sign, day)}]}],
            "generationConfig": {"temperature": 0.9, "responseMimeType": "application/json"}}
    try:
        resp, _ = generate_content("text", body, key=key, timeout=45, label=label)
    except requests.RequestException:
        logger.exception("%s: could not reach Gemini", label)
        return None
    if resp is None or resp.status_code != 200:
        logger.error("%s: %s — %s", label, getattr(resp, "status_code", 0), getattr(resp, "text", "")[:300])
        return None
    try:
        parts = resp.json()["candidates"][0]["content"]["parts"]
        raw = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
        m = re.search(r"\{.*\}", raw, re.S)
        return clean(json.loads(m.group(0) if m else raw))
    except Exception:
        return None


def horoscope_for(sign, day=None, level="basic"):
    """Today's reading for `sign` at `level`, written on first ask and kept for the day."""
    day = day or timezone.localdate()
    row = Horoscope.objects.filter(sign=sign, day=day, level=level).first()
    if row:
        return row.reading
    reading = _write(sign, day, level)
    if not reading:
        return None
    try:
        Horoscope.objects.create(sign=sign, day=day, level=level, reading=reading)
    except IntegrityError:
        # Two members asked for the same sign in the same second; the first
        # write wins and both read it, so nobody sees two different days.
        row = Horoscope.objects.filter(sign=sign, day=day, level=level).first()
        return row.reading if row else reading
    return reading


class HoroscopeView(APIView):
    """GET /api/economy/horoscope/<sign>/[?level=advanced] — today's reading.

    The daily reading is free for everybody. `advanced` is StatZ (or the
    StatZ free-hour sample); asking without it answers 403 with what it is
    and where to get it, never an empty panel."""

    permission_classes = [IsAuthenticated]

    def get(self, request, sign):
        sign = str(sign).strip().title()
        if sign not in SIGN_NAMES:
            return Response({"detail": "Unknown sign."}, status=status.HTTP_404_NOT_FOUND)
        emoji, dates = {n: (e, d) for n, e, d in ZODIAC}[sign]
        day = timezone.localdate()
        base = {"sign": sign, "emoji": emoji, "dates": dates, "day": day.isoformat(),
                "note": HOROSCOPE_NOTE, "cost": 0, "element": ELEMENT[sign], "about": SIGN_READ[sign],
                "members_tab": {"tab": "zodiacz", "sign": sign}}
        other = str(request.query_params.get("with", "")).strip().title()
        if other in SIGN_NAMES:
            base["compatibility"] = compatibility(sign, other)
        level = "advanced" if request.query_params.get("level") == "advanced" else "basic"
        base["level"] = level
        base["advanced_available"] = has_statz(request.user)
        if level == "advanced" and not base["advanced_available"]:
            return Response({**base, "reading": None, "tier": "statz",
                             "detail": "The advanced reading — love single and taken, money earned and spent, "
                                       "your music career, who to create with, and the week ahead — is a "
                                       "StatZ feature. The daily reading stays free."},
                            status=status.HTTP_403_FORBIDDEN)
        reading = horoscope_for(sign, day, level)
        if not reading and level == "basic":
            # Never an empty panel for the free reading: the house one is
            # always there, says it is, and costs nothing.
            return Response({**base, "reading": house_reading(sign, day)})
        if not reading:
            return Response({**base, "reading": None,
                             "detail": "Today's reading isn't written yet — try again in a minute."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({**base, "reading": reading})

