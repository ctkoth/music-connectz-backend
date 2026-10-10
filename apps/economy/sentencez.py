"""Sentence ConnectZ — the IntelligenceZ writer.

Writes essays, Instagram captions, social posts, lyrics (to a rhyme scheme
stated in numbers), resumes, cover letters, poems and bios, and — for members who
hold the Manager or A&R Scout PersonaZ — artist contracts and royalties agreements.

Whose voice a piece comes out in is declared per kind (`voice`) and served, so a
screen says it rather than assuming it: lyrics, captions and posts are K-Oth's
register, essays the academic one, and everything else is written plainly — a
resume in anybody's house voice is a resume that is not the member's.

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

from .catalog import UNLIMITED_CHARS as UNLIMITED_BRIEF
from .catalog import WRITER_BRIEF_CHARS, ai_cost, over_writer_brief, writer_brief_chars
from .gemini import _bill, _key, generate_content
from .models import (SentenceWork, membership_for, can_afford_ai, daily_prompt_covers,
                     daily_prompt_state, profile_for)
from .personaz import personas_of

logger = logging.getLogger(__name__)

KOTH_ROYALTY_PCT = 10
CONTRACT_PERSONAS = ("manager", "arscout")

# Corey's voice. Both repos are public, so his lyrics are NOT committed: they
# are read from a Render Secret File (or the env var), samples separated by a
# line holding only "---". With neither set the writer uses the voice notes alone,
# which describe how he writes without quoting anything he wrote.
VOICE_FILE = os.environ.get("SENTENCEZ_VOICE_FILE", "/etc/secrets/sentencez_voice.txt")
# Corey's two registers, from his own voice profile. Never blended: lyrics,
# captions and posts take the personal one, essays the academic one, and the
# legal kinds neither.
PERSONAL_VOICE = (
    "Values-first and radically transparent: say the real reason, not the polished one. "
    "Frame things with an eye on legacy and long-term impact, even in short pieces."
)
LYRIC_STYLE = (
    "Stack internal and multi-syllable rhymes inside lines, not only at line ends. "
    "Play on homophones and split words, written out so the double meaning shows: "
    "k(no)w, chews (choose), worth/worse. Run bars on across line breaks the way speech does. "
    "Be candid and self-reflective, including about your own faults, and turn it toward growth. "
    "Plain, conversational vocabulary; confidence without polish."
)
ACADEMIC_VOICE = (
    "Open every heading and every paragraph with an emoji. Headings are plain text on their own line. "
    "Use contractions — conversational, not stiff — and em dashes freely. Use Music ConnectZ, the "
    "author's own music platform, as a recurring real-world example. Cite in full APA 7 in-text and end "
    "with an APA 7 References section, but cite ONLY sources listed in the brief, with their exact "
    "details; never invent a source. Where a claim needs a citation the brief doesn't supply, write "
    "[CITATION NEEDED]."
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

# Written FROM what the member supplied, so they may not be written from anything
# else. A resume is a claim about a person's history; a model filling the gaps with
# plausible employers and dates produces a document that looks finished and is
# false, which is the substance rule's failure case with a job application
# attached. Everything not stated becomes a visible [BRACKETED] blank instead.
NO_INVENTION = ("Use ONLY the facts stated in the request. Never invent an employer, job title, "
                "date, degree, certification, number, award or achievement. Where the request leaves "
                "something out that this document normally carries, write a [BRACKETED PLACEHOLDER] "
                "for it; do not guess and do not explain the gap outside the brackets.")

KINDS.update({
    "resume": {"label": "Resume", "emoji": "📄", "plain": True, "no_invention": True,
               "ask": ("a resume in plain text: a header with name and contact placeholders, a two-line "
                       "summary, experience newest first with action-led bullets, education, and skills. "
                       "Keep it to one page unless the request has enough for more"),
               "hint": ("Paste your history: every role (employer, title, dates, what you did), your "
                        "education and skills. It writes only what you tell it — nothing is added."),
               "style_label": "Role you're applying for (optional)"},
    "cover_letter": {"label": "Cover letter", "emoji": "✉️", "plain": True, "no_invention": True,
                     "ask": ("a cover letter of about 250 words addressed to the hiring contact: why this "
                             "role, two concrete things the applicant has done that fit it, and a close"),
                     "hint": ("The role and company, then what you want them to know about you — your "
                              "real experience. It writes only what you tell it."),
                     "style_label": "Tone (optional)"},
    "poem": {"label": "Poem", "emoji": "🪶", "plain": True,
             "ask": ("a poem. Follow the form the request names (sonnet, haiku, villanelle…); free verse "
                     "if it names none. A title, then the poem"),
             "hint": "What is it about? Name a form or a feeling if you have one.",
             "style_label": "Form or mood (optional)"},
    "bio": {"label": "Bio", "emoji": "🙋", "plain": True, "no_invention": True,
            "ask": ("a short bio of about 100 words in the third person, written for the place the "
                    "request names, or for a general profile if it names none"),
            "hint": "Who it is about, what they do, and the two or three facts that matter.",
            "style_label": "Where it will appear (optional)"},
})

# Placeholder text for the brief box, per kind. Served so a screen never types
# the prompt for a kind it was not written for.
_HINTS = {
    "lyrics": "What's the song about? Describe the topic, the story, the feeling.",
    "caption": "What is the post about? Where, who, the mood.",
    "post": "What should it say?",
    "essay": ("The prompt, your angle, and every source to cite (author, year, title, publisher, URL). "
              "It cites only what you list."),
    "contract": "Who the parties are, what is being agreed, term and territory.",
    "royalties": "The work, who is on it, and what each person is owed.",
}
for _k, _h in _HINTS.items():
    KINDS[_k]["hint"] = _h

# The order a screen lists them in: what most people came to write first, the
# persona-gated agreements last so a member without the persona is not shown
# two locked doors before anything they can use.
_ORDER = ("resume", "cover_letter", "lyrics", "poem", "bio", "caption", "post", "essay", "contract", "royalties")
assert set(_ORDER) == set(KINDS), "a kind was added without being placed in _ORDER"
KINDS = {k: KINDS[k] for k in _ORDER}

LEGAL_KINDS = {k for k, v in KINDS.items() if v.get("personas")}
LEGAL_NOTE = ("A starting draft, not legal advice. Have a lawyer read it before anybody signs, "
              "and fill every [BRACKETED] blank.")
# For the documents that claim a history. The writer was told to use only what the
# member wrote, so what is missing is a visible blank rather than a plausible guess
# — and the note says to fill them, because a resume sent with a bracket in it is a
# worse resume than none.
FILL_NOTE = ("Written from only what you gave it. Fill every [BRACKETED] blank with your real "
             "details, and read it through before you send it.")


def voice_of(kind):
    """"koth", "academic" or "plain" — whose register the piece is written in."""
    if kind == "essay":
        return "academic"
    if KINDS[kind].get("plain") or kind in LEGAL_KINDS:
        return "plain"
    return "koth"


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
                    "needs": ["Manager", "A&R Scout"] if need else [],
                    "voice": voice_of(key),
                    "invents_nothing": bool(k.get("no_invention")),
                    "hint": k.get("hint", ""),
                    "style_label": k.get("style_label", "Genre / style (optional)")})
    return out


def chars_unlimited_brief(tier):
    return writer_brief_chars(tier) >= UNLIMITED_BRIEF


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
    voice = voice_of(kind)
    if voice == "academic":
        lines.append("VOICE: " + ACADEMIC_VOICE)
    elif voice == "koth":
        lines.append("VOICE: " + PERSONAL_VOICE + (" " + LYRIC_STYLE if kind == "lyrics" else ""))
    if k.get("no_invention"):
        lines.append(NO_INVENTION)
    if kind in ("lyrics", "caption", "post"):
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
            "legal_note": LEGAL_NOTE if w.kind in LEGAL_KINDS else "",
            "note": FILL_NOTE if KINDS.get(w.kind, {}).get("no_invention") else ""}


class SentenceView(APIView):
    """GET: the kinds, which are open to you, and the price — before anything
    is written. POST {kind, topic, genre?, majority?, minority?}: write it."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cost = ai_cost("standard")
        allowance, _, daily_left = daily_prompt_state(request.user)
        free = daily_left > 0 and daily_prompt_covers(cost)
        works = SentenceWork.objects.filter(user=request.user)[:20]
        tier = membership_for(request.user).tier
        return Response({
            "configured": bool(_key()),
            "kinds": kinds_for(request.user),
            "brief_limit": writer_brief_chars(tier),
            # Every tier's number, so a screen can say what the next one takes
            # without typing it. None is unlimited.
            "brief_ladder": [{"tier": t, "chars": None if WRITER_BRIEF_CHARS[t] >= UNLIMITED_BRIEF else WRITER_BRIEF_CHARS[t]}
                             for t in ("free", "premium", "statz")],
            "brief_unlimited": chars_unlimited_brief(tier),
            "tier": tier,
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
        cap = over_writer_brief(topic, membership_for(request.user).tier)
        if cap:
            return Response({"detail": f"Your tier takes up to {cap:,} characters of brief here — upgrade in MembershipZ for more.", "char_limit": cap},
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
            user=request.user, kind=kind, topic=topic, text=text,
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
