"""Sentence ConnectZ — the IntelligenceZ writer.

Writes essays, Instagram captions, social posts, lyrics (to a rhyme scheme
stated in numbers), and — for members who hold the Manager or A&R Scout
PersonaZ — artist contracts and royalties agreements.

Billing follows the coach: the price is published by GET before anything is
written, a free daily prompt covers a run before any paid balance, and a run
that comes back empty is not charged.

Every piece is kept (`SentenceWork`) with the text exactly as it was written,
because K-Oth's royalty on a piece used in DistributeZ, CollabZ or BattleZ is
`KOTH_ROYALTY_PCT` scaled by how much of that ORIGINAL survives the member's
edits — 10% for the piece as written, 5% when half of it is left. `kept_share`
is that measurement and lives here so the thing that wrote the text and the
thing that prices it can never disagree about what the original was.
"""
import difflib
import logging
import os
import re

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import ai_cost
from .gemini import _bill, _key, generate_content
from .models import (SentenceWork, can_afford_ai, daily_prompt_covers,
                     daily_prompt_state, profile_for)
from .personaz import personas_of

logger = logging.getLogger(__name__)

KOTH_ROYALTY_PCT = 10
TOPIC_MAX = 2000
CONTRACT_PERSONAS = ("manager", "arscout")

# Corey's voice. Both repos are public, so his lyrics are NOT committed: they
# are read from a Render Secret File (or the env var), samples separated by a
# line holding only "---". With neither set the writer uses VOICE_NOTES alone,
# which describe how he writes without quoting anything he wrote.
VOICE_FILE = os.environ.get("SENTENCEZ_VOICE_FILE", "/etc/secrets/sentencez_voice.txt")
VOICE_NOTES = (
    "Stack internal and multi-syllable rhymes inside lines, not only at line ends. "
    "Play on homophones and split words, written out so the double meaning shows: "
    "k(no)w, chews (choose), worth/worse. Run bars on across line breaks the way speech does. "
    "Be candid and self-reflective, including about your own faults, and turn it toward growth. "
    "Plain, conversational vocabulary; confidence without polish; the occasional brand-style Z "
    "(ConnectZ, SkillZ) when talking about the platform."
)


def voice_samples():
    raw = os.environ.get("SENTENCEZ_VOICE", "")
    if not raw:
        try:
            with open(VOICE_FILE, encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            raw = ""
    return [s.strip() for s in re.split(r"(?m)^---\s*$", raw) if s.strip()][:8]

KINDS = {
    "lyrics": {"label": "Lyrics", "emoji": "🎤",
               "ask": "song lyrics with labelled sections (Verse, Chorus, Bridge)"},
    "caption": {"label": "Instagram caption", "emoji": "📸",
                "ask": "an Instagram caption: a hook first line, a short body, then 5-10 relevant hashtags"},
    "post": {"label": "Social media post", "emoji": "📣",
             "ask": "a social media post that fits any major platform, under 280 words"},
    "essay": {"label": "Essay", "emoji": "📝",
              "ask": "an essay with a title, an introduction, developed body paragraphs and a conclusion"},
    "contract": {"label": "Artist contract", "emoji": "📜", "personas": CONTRACT_PERSONAS,
                 "ask": ("an artist agreement between a manager or label representative and an artist: "
                         "parties, term, territory, services, compensation and splits, recoupment, "
                         "ownership of masters and publishing, termination, and signature blocks. "
                         "Use [BRACKETED PLACEHOLDERS] for every name, date, amount and percentage "
                         "the request does not state")},
    "royalties": {"label": "Royalties agreement", "emoji": "💸", "personas": CONTRACT_PERSONAS,
                  "ask": ("a royalties split agreement: the work, every party and their percentage, "
                          "which income the splits cover, accounting and payment schedule, audit "
                          "rights, and signature blocks. Use [BRACKETED PLACEHOLDERS] for anything "
                          "the request does not state, and make the percentages add to 100")},
}

LEGAL_KINDS = {k for k, v in KINDS.items() if v.get("personas")}
LEGAL_NOTE = ("A starting draft, not legal advice. Have a lawyer read it before anybody signs, "
              "and fill every [BRACKETED] blank.")


def persona_keys(user):
    keys = set()
    for p in personas_of(profile_for(user)):
        for f in ("key", "name"):
            v = re.sub(r"[^a-z]", "", str(p.get(f, "")).lower())
            if v:
                keys.add(v)
    return keys


def kinds_for(user):
    mine = persona_keys(user)
    out = []
    for key, k in KINDS.items():
        need = k.get("personas") or ()
        out.append({"key": key, "label": k["label"], "emoji": k["emoji"],
                    "allowed": not need or bool(mine & set(need)),
                    "needs": ["Manager", "A&R Scout"] if need else []})
    return out


def _int(v, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return None


def prompt_for(kind, topic, genre="", majority=None, minority=None):
    k = KINDS[kind]
    lines = [f"Write {k['ask']}.", f"Subject: {topic}"]
    if genre:
        lines.append(f"Genre / style: {genre}")
    if kind == "lyrics" and (majority or minority):
        rule = ["RHYME SCHEME — count syllables from the END of each line:"]
        if majority:
            rule.append(f"- Most lines (the majority) must rhyme on their last {majority} "
                        f"syllable{'s' if majority > 1 else ''} with another line.")
        if minority:
            rule.append(f"- The remaining lines (the minority) rhyme on their last {minority} "
                        f"syllable{'s' if minority > 1 else ''}.")
        lines.append("\n".join(rule))
    if kind not in LEGAL_KINDS:
        lines.append("VOICE: " + VOICE_NOTES)
        samples = voice_samples()
        if samples:
            lines.append("Match the voice of these samples — vocabulary, rhythm, wordplay, attitude — "
                         "but never reuse their lines or their subjects:\n" + "\n---\n".join(samples))
    lines.append("Reply with the finished piece only: no preamble, no notes about what you wrote.")
    return "\n\n".join(lines)


def kept_share(original, edited):
    """Fraction of the original's words that survive, in order, in `edited`."""
    a = (original or "").split()
    if not a:
        return 0.0
    b = (edited or "").split()
    matched = sum(m.size for m in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    return round(min(1.0, matched / len(a)), 4)


def royalty_pct(original, edited):
    return round(KOTH_ROYALTY_PCT * kept_share(original, edited), 2)


def _text_of(resp):
    try:
        parts = resp.json()["candidates"][0]["content"]["parts"]
    except Exception:
        return ""
    return "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()


def _work_dict(w):
    return {"id": w.id, "kind": w.kind, "label": KINDS.get(w.kind, {}).get("label", w.kind),
            "topic": w.topic, "text": w.text, "inputs": w.inputs,
            "created_at": w.created_at.isoformat(),
            "legal_note": LEGAL_NOTE if w.kind in LEGAL_KINDS else ""}


class SentenceView(APIView):
    """GET: the kinds, which are open to you, and the price — before anything
    is written. POST {kind, topic, genre?, majority?, minority?}: write it."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cost = ai_cost("standard")
        allowance, _, daily_left = daily_prompt_state(request.user)
        free = daily_left > 0 and daily_prompt_covers(cost)
        works = SentenceWork.objects.filter(user=request.user)[:20]
        return Response({
            "configured": bool(_key()),
            "kinds": kinds_for(request.user),
            "cost_cents": cost,
            "free_today": free,
            "daily_remaining": daily_left,
            "daily_allowance": allowance,
            "can_run": bool(_key()) and (free or can_afford_ai(request.user, cost)),
            "royalty_pct": KOTH_ROYALTY_PCT,
            "royalty_rule": (f"Using a piece in DistributeZ, CollabZ or BattleZ pays K-Oth "
                             f"{KOTH_ROYALTY_PCT}% of it, scaled by how much of the original you kept — "
                             f"keep half and it's {KOTH_ROYALTY_PCT / 2:g}%."),
            "legal_note": LEGAL_NOTE,
            "rhyme_max": 4,
            "works": [_work_dict(w) for w in works],
        })

    def post(self, request):
        d = request.data or {}
        kind = str(d.get("kind", "")).strip()
        if kind not in KINDS:
            return Response({"detail": "Pick what to write."}, status=status.HTTP_400_BAD_REQUEST)
        need = KINDS[kind].get("personas")
        if need and not (persona_keys(request.user) & set(need)):
            return Response({"detail": f"{KINDS[kind]['label']}s are written for members with the "
                                       "Manager or A&R Scout PersonaZ. Add one in ProfileZ.",
                             "needs": ["Manager", "A&R Scout"]}, status=status.HTTP_403_FORBIDDEN)
        topic = str(d.get("topic", "")).strip()
        if not topic:
            return Response({"detail": "Say what it's about."}, status=status.HTTP_400_BAD_REQUEST)
        if len(topic) > TOPIC_MAX:
            return Response({"detail": f"Keep the brief under {TOPIC_MAX} characters."},
                            status=status.HTTP_400_BAD_REQUEST)
        genre = str(d.get("genre", "")).strip()[:60]
        majority = _int(d.get("majority"), 0, 4) if kind == "lyrics" else None
        minority = _int(d.get("minority"), 0, 4) if kind == "lyrics" else None

        key = _key()
        if not key:
            return Response({"detail": "Sentence ConnectZ isn't switched on — the backend is missing GEMINI_API_KEY."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        cost = ai_cost("standard")
        _, _, daily_left = daily_prompt_state(request.user)
        free = daily_left > 0 and daily_prompt_covers(cost)
        if cost and not free and not can_afford_ai(request.user, cost):
            return Response({"detail": "Not enough PromptZ or balance for this one.", "cost_cents": cost},
                            status=status.HTTP_402_PAYMENT_REQUIRED)

        body = {"contents": [{"parts": [{"text": prompt_for(kind, topic, genre, majority, minority)}]}],
                "generationConfig": {"temperature": 0.9}}
        try:
            resp, tried = generate_content("text", body, key=key, timeout=60, label="Sentence ConnectZ")
        except requests.RequestException:
            logger.exception("Sentence ConnectZ: could not reach Gemini")
            return Response({"detail": "Couldn't reach the writer. Nothing was charged — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        text = _text_of(resp) if resp is not None and resp.status_code == 200 else ""
        if not text:
            logger.error("Sentence ConnectZ: Gemini %s model=%s — %s", getattr(resp, "status_code", 0),
                         ", ".join(tried), getattr(resp, "text", "")[:300])
            return Response({"detail": "The writer came back empty. Nothing was charged — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)

        charged = _bill(request.user, f"Sentence ConnectZ — {KINDS[kind]['label']}", count_daily=True)
        if charged is None:
            return Response({"detail": "Not enough PromptZ or balance for this one.", "cost_cents": cost},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        work = SentenceWork.objects.create(
            user=request.user, kind=kind, topic=topic[:TOPIC_MAX], text=text,
            inputs={"genre": genre, "majority": majority, "minority": minority},
        )
        return Response({**_work_dict(work), "charged_cents": charged}, status=status.HTTP_201_CREATED)


class SentenceRoyaltyView(APIView):
    """POST {text}: what K-Oth's royalty on this piece would be, as edited."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        work = SentenceWork.objects.filter(pk=pk, user=request.user).first()
        if not work:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        edited = str((request.data or {}).get("text", ""))
        return Response({"kept_share": kept_share(work.text, edited),
                         "royalty_pct": royalty_pct(work.text, edited)})
