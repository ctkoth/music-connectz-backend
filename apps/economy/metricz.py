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

from .gemini import _key, generate_content
from .models import (Horoscope, Profile, adult_only_reason, blocked_user_ids,
                     profile_is_minor, zodiac_for)
from .social import ACTIVE_STANCES, clean_substances

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

# Keys match what ProfileZ already stores, so every existing declaration counts.
SUBSTANCES = [
    ("cigarettes", "Cigarettes", "🚬"),
    ("caffeine", "Caffeine", "☕"),
    ("alcohol", "Alcohol", "🍺"),
    ("thc", "THC", "🍃"),
    ("heroin", "Heroin", "💉"),
    ("crack", "Crack", "💎"),
    ("meth", "Meth", "💎"),
    ("dxm", "DXM", "🧴"),
    ("adderall", "Adderall", "💊"),
    ("opioids", "Opioids", "💊"),
    ("benzos", "Benzos", "💊"),
]
SUBSTANCE_KEYS = [s[0] for s in SUBSTANCES]

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
        return [{"key": n, "label": n, "emoji": e, "dates": d} for n, e, d in ZODIAC]
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
    undeclared = sober = 0
    adult = KINDS[kind]["adult"]
    blocked = blocked_user_ids(viewer)
    for p in Profile.objects.exclude(user_id__in=blocked).only(
            "sign", "birthday", "substances", "sober", "attracted_to", "verified_18plus", "user_id"):
        if adult and profile_is_minor(p):
            continue
        keys = _declared(kind, p)
        for k in keys:
            counts[k] += 1
        if not keys:
            undeclared += 1
            if kind == "substancez" and p.sober:
                sober += 1
    return counts, undeclared, sober


def matches(kind, p, wanted):
    """Whether profile `p` declared ANY of `wanted` for `kind`. OR within a
    metric, the rule every multi-select in MembersView already follows."""
    if KINDS[kind]["adult"] and profile_is_minor(p):
        return False
    return bool(set(wanted) & set(_declared(kind, p)))


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
        counts, undeclared, sober = counts_for(kind, request.user)
        me = getattr(request.user, "mcz_profile", None)
        mine = _declared(kind, me) if me else []
        out = {**base, "options": [{**o, "count": counts[o["key"]], "mine": o["key"] in mine}
                                    for o in _options(kind)],
               "undeclared": undeclared, "mine": mine,
               # ProfileZ anchor that sets it — "nothing is a dead end".
               "set_in": {"tab": "profilez", "target": {"zodiacz": "birthday", "substancez": "substancez",
                                                         "preferencez": "preferencez"}[kind]}}
        if kind == "substancez":
            out["sober"] = sober
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


def _write(sign, day):
    """One model call for one sign's day. None when it can't be written."""
    key = _key()
    if not key:
        return None
    body = {"contents": [{"parts": [{"text": _prompt(sign, day)}]}],
            "generationConfig": {"temperature": 0.9, "responseMimeType": "application/json"}}
    try:
        resp, _ = generate_content("text", body, key=key, timeout=40, label="ZodiacZ horoscope")
    except requests.RequestException:
        logger.exception("ZodiacZ horoscope: could not reach Gemini")
        return None
    if resp is None or resp.status_code != 200:
        logger.error("ZodiacZ horoscope: %s — %s", getattr(resp, "status_code", 0), getattr(resp, "text", "")[:300])
        return None
    try:
        parts = resp.json()["candidates"][0]["content"]["parts"]
        raw = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
        m = re.search(r"\{.*\}", raw, re.S)
        return _clean(json.loads(m.group(0) if m else raw))
    except Exception:
        return None


def horoscope_for(sign, day=None):
    """Today's reading for `sign`, written on first ask and kept for the day."""
    day = day or timezone.localdate()
    row = Horoscope.objects.filter(sign=sign, day=day).first()
    if row:
        return row.reading
    reading = _write(sign, day)
    if not reading:
        return None
    try:
        Horoscope.objects.create(sign=sign, day=day, reading=reading)
    except IntegrityError:
        # Two members asked for the same sign in the same second; the first
        # write wins and both read it, so nobody sees two different days.
        row = Horoscope.objects.filter(sign=sign, day=day).first()
        return row.reading if row else reading
    return reading


class HoroscopeView(APIView):
    """GET /api/economy/horoscope/<sign>/ — today's detailed reading. Free."""

    permission_classes = [IsAuthenticated]

    def get(self, request, sign):
        sign = str(sign).strip().title()
        if sign not in SIGN_NAMES:
            return Response({"detail": "Unknown sign."}, status=status.HTTP_404_NOT_FOUND)
        emoji, dates = {n: (e, d) for n, e, d in ZODIAC}[sign]
        day = timezone.localdate()
        base = {"sign": sign, "emoji": emoji, "dates": dates, "day": day.isoformat(),
                "note": HOROSCOPE_NOTE, "cost": 0,
                "members_tab": {"tab": "zodiacz", "sign": sign}}
        reading = horoscope_for(sign, day)
        if not reading:
            return Response({**base, "reading": None,
                             "detail": "Today's reading isn't written yet — try again in a minute."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({**base, "reading": reading})

