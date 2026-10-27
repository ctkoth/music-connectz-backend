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
import json
import logging
import os
import re

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import refinput
from .priorities import clause as priorities_clause
from .catalog import UNLIMITED_CHARS as UNLIMITED_BRIEF
from .catalog import WRITER_BRIEF_CHARS, ai_cost, over_writer_brief, writer_brief_chars
from .deadline import Deadline, Expired
from .gemini import _bill, _key, generate_content
from .models import (SentenceWork, membership_for, can_afford_ai, daily_prompt_covers,
                     daily_prompt_state, profile_for)
from .personaz import personas_of
from .voicez import resolve
from .views import is_owner_candidate

logger = logging.getLogger(__name__)

KOTH_ROYALTY_PCT = 10
CONTRACT_PERSONAS = ("manager", "arscout")
# How long a member may be kept waiting for one POST, start to finish. The
# screen used to give up at 30s while the server let the writer run for 60 per
# model and then charged for a piece nobody was waiting for. The screen reads
# this from GET and waits LONGER than it, so a server that answers in time is
# always the one that decides; the model call takes what is left of it.
BUDGET_SECONDS = 55

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
# The citation rules are what makes an essay safe to hand in, and they are the
# same for everybody: only sources the member listed, never an invented one.
_APA = ("Cite in full APA 7 in-text and end with an APA 7 References section, but cite ONLY sources "
        "listed in the brief, with their exact details; never invent a source. Where a claim needs a "
        "citation the brief doesn't supply, write [CITATION NEEDED].")
# What every member's essay gets: a plain academic register and the citation rules.
ACADEMIC_PLAIN = "Write in a clear, formal academic register. Headings are plain text on their own line. " + _APA
# Corey's own academic register — an emoji on every heading and paragraph,
# contractions, em dashes, and this platform as the running example. It is HIS
# voice, so only the platform owner's essays are written in it; handing it to a
# student writing about streaming payouts put an app they had not mentioned into
# their essay. Byte-for-byte what the prompt said before the split.
ACADEMIC_VOICE = (
    "Open every heading and every paragraph with an emoji. Headings are plain text on their own line. "
    "Use contractions — conversational, not stiff — and em dashes freely. Use Music ConnectZ, the "
    "author's own music platform, as a recurring real-world example. " + _APA
)
# Said on the screen, per the essay kind, so what the member is told is what the
# prompt actually does.
ESSAY_NOTE_MEMBER = ("Clear academic register, APA 7. It cites only the sources you list in the brief — it never "
                     "makes one up, and writes [CITATION NEEDED] where a claim has no source from you.")
ESSAY_NOTE_OWNER = ("Your own academic register: an emoji opens every heading and paragraph, contractions and em "
                    "dashes, and Music ConnectZ as the running example. APA 7, citing only the sources you list.")


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

# The lyric problem areas the coach can score, and the writer that fixes each.
#
# Every one of these is the same product: five suggestions for ONE weak
# dimension, each with the technique it uses and why it lands, ranked by what
# members rate highest — and every one is a saved SentenceWork, so a line a
# member takes into a release, battle or deal carries K-Oth's royalty on the
# part they keep, exactly as any other piece does. `techniques` is a closed list
# PER KIND: the ratings are grouped by it, so a technique the model invents
# would be a group of one that can never be ranked.
FIXERS = {
    "punchlines": {
        "dim": "punchlines", "label": "Punchlines", "emoji": "🥊", "noun": "punchlines", "one": "punchline",
        "techniques": {"wordplay": "Wordplay", "double_meaning": "Double meaning", "metaphor": "Metaphor",
                       "simile": "Simile", "callback": "Callback", "reversal": "Reversal",
                       "multisyllabic": "Multisyllabic", "other": "Other"},
        "core": "A punchline lands on a turn: a setup, then a payoff the listener did not see coming.",
        "hint": ("Paste the bars you want better punchlines for (or the whole verse). You get five, each "
                 "with why it lands, ranked by what members rate highest.")},
    "hooks": {
        "dim": "hook", "label": "Hooks (HookZ)", "emoji": "🪝", "noun": "hooks", "one": "hook",
        "techniques": {"repeat": "Repeated phrase", "call_response": "Call and response", "chant": "Chant",
                       "melodic": "Melodic line", "contrast": "Contrast", "question": "Question",
                       "one_word": "One-word hook", "other": "Other"},
        "core": "A hook is the chorus or refrain a listener can sing back after one hearing.",
        "hint": ("Paste your chorus (or the verse it follows). You get five hooks, each with why it "
                 "sticks, ranked by what members rate highest.")},
    "rhymes": {
        "dim": "rhyme", "label": "Rhymes", "emoji": "🔗", "noun": "rhyme rewrites", "one": "rewrite",
        "techniques": {"multisyllabic": "Multisyllabic", "internal": "Internal rhyme", "chain": "Chain rhyme",
                       "slant": "Slant rhyme", "stacked": "Stacked rhymes", "other": "Other"},
        "core": "Rewrite weak lines so the rhymes land on the stressed syllables and the meaning survives.",
        "hint": "Paste the bars whose rhymes feel weak. You get five rewrites, each with why it rhymes better."},
    "imagery": {
        "dim": "imagery", "label": "Imagery", "emoji": "🖼️", "noun": "imagery lines", "one": "line",
        "techniques": {"sensory": "Sensory detail", "concrete": "Concrete detail", "metaphor": "Metaphor",
                       "motion": "Motion", "contrast": "Contrast", "other": "Other"},
        "core": "Imagery shows the listener a thing instead of naming a feeling.",
        "hint": "Paste the bars that tell more than they show. You get five lines, each with why it paints."},
    "storybeats": {
        "dim": "story", "label": "Story beats", "emoji": "📖", "noun": "story beats", "one": "beat",
        "techniques": {"setup_payoff": "Setup and payoff", "turn": "Turn", "stakes": "Stakes",
                       "callback": "Callback", "time_jump": "Time jump", "other": "Other"},
        "core": "A story beat moves the verse from where it is to somewhere the listener wants to follow.",
        "hint": "Paste the verse that wanders. You get five beats, each with why it moves the story."},
    "depth": {
        "dim": "feelz", "label": "Depth (FeelZ)", "emoji": "💗", "noun": "lines with more depth", "one": "line",
        "techniques": {"vulnerable": "Vulnerability", "specific_memory": "Specific memory", "stakes": "Real stakes",
                       "contrast": "Contrast", "restraint": "Restraint", "turn_inward": "Turn inward", "other": "Other"},
        "core": "Depth is a line that costs the writer something: a specific, true moment instead of a general feeling.",
        "hint": ("Paste the bars that say a feeling without earning it. You get five lines with more depth, "
                 "each with why it hits harder.")},
    "freshangles": {
        "dim": "freshness", "label": "Fresh angles", "emoji": "💡", "noun": "fresh angles", "one": "angle",
        "techniques": {"pov": "Unexpected point of view", "specific": "Specific detail", "reversal": "Reversal",
                       "personal": "Personal truth", "wordplay": "Wordplay", "other": "Other"},
        "core": "A fresh angle says a familiar thing in a way the listener has not heard it.",
        "hint": "Paste the bars that sound like everyone else. You get five angles, each with why it is fresh."},
}
FIX_COUNT = 5
MIN_RATINGS_TO_RANK = 5   # below this a technique's average is a coincidence, not a preference
# What the coach's dimension keys map to, so a weak score finds its writer.
FIXER_FOR_DIM = {f["dim"]: k for k, f in FIXERS.items()}

KINDS.update({
    k: {"label": f["label"], "emoji": f["emoji"], "json": True, "fixer": True,
        "ask": (f"exactly five {f['noun']} this rapper could use in the bars below, to lift a weak "
                f"{f['dim']} score. {f['core']} Each must fit the genre, be original (never a famous "
                f"line) and be something THIS rapper could say. Reply as JSON: "
                '{"items":[{"line":"<the ' + f["one"] + ', one or two bars>",'
                '"technique":"<one of: ' + ", ".join(t for t in f["techniques"] if t != "other") + '>",'
                '"why":"<one or two sentences: why it works, and why it fixes the weakness in THESE bars>",'
                '"where":"<which line or section of their bars it would replace or follow, or empty>"}]}'),
        "hint": f["hint"], "style_label": "Genre / style (optional)"}
    for k, f in FIXERS.items()
})

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
    "workout_read": {"label": "AI coach's read", "emoji": "🤖", "plain": True, "no_invention": True,
                     "ask": ("a short coaching read of the workout in the facts: what went well, the one thing "
                             "to change next time, and a concrete target for the next session. Speak to the "
                             "lifter as 'you', plain and encouraging, under 150 words, no headings"),
                     "hint": "Read from your logged sets.", "style_label": "Focus (optional)"},
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
_ORDER = ("resume", "cover_letter", "lyrics", *FIXERS, "poem", "bio", "workout_read", "caption", "post", "essay", "contract", "royalties")
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


# The kinds that take the member's WRITER voice. Creative work is the member's
# to voice; everything else is a claim about a person (resume, cover letter,
# bio), follows a standard (essay, APA) or is a legal draft, and a voice must
# never change what is true. A poem is plain by default (no house register) but
# makes no claim about anybody, so a custom voice may write it.
CREATIVE_KINDS = ("lyrics", *FIXERS, "poem", "caption", "post")


def voice_of(kind):
    """"koth", "academic" or "plain" — whose register the piece is written in."""
    if kind == "essay":
        return "academic"
    if KINDS[kind].get("plain") or kind in LEGAL_KINDS:
        return "plain"
    return "koth"


_EMOJI_TEXT = {"none": "EMOJI: none.", "light": "EMOJI: sparing, only where it helps.",
               "heavy": "EMOJI: plenty, fitting each line."}


def persona_keys(user):
    keys = set()
    for p in personas_of(profile_for(user)):
        for f in ("key", "name"):
            v = re.sub(r"[^a-z]", "", str(p.get(f, "")).lower())
            if v:
                keys.add(v)
    return keys


def voice_note(kind, owner=False, writer=None):
    """What the prompt for this kind actually does about voice, for the screen to say.

    Only the essay has anything member-specific to say; the others are stated by
    `voice` alone, so theirs is empty rather than a sentence invented to fill the key.
    """
    base = ""
    if kind == "essay":
        base = ESSAY_NOTE_OWNER if owner else ESSAY_NOTE_MEMBER
    # Member-specific only when the member chose something other than the
    # default; the default is stated by `voice` alone (the screen says K-Oth's).
    if writer is not None and writer.is_custom:
        if kind in CREATIVE_KINDS:
            return f"Written in your voice '{writer.label}'."
        return (base + " " if base else "") + f"Your voice '{writer.label}' isn't used here: this kind keeps its own register."
    if writer is not None and not writer.follows_style and writer.key == "standard" and voice_of(kind) == "koth":
        return "Written plainly, with none of K-Oth's house style (your Writer voice is Standard)."
    return base


def kinds_for(user):
    mine = persona_keys(user)
    owner = bool(is_owner_candidate(user))
    from .voicez import resolve
    writer = resolve(user, "writer")
    out = []
    for key, k in KINDS.items():
        need = k.get("personas") or ()
        out.append({"key": key, "label": k["label"], "emoji": k["emoji"],
                    "allowed": not need or bool(mine & set(need)),
                    "needs": ["Manager", "A&R Scout"] if need else [],
                    "voice": voice_of(key),
                    "voice_note": voice_note(key, owner, writer),
                    "takes_voice": key in CREATIVE_KINDS,
                    # A fixer exists to repair a score the coach gave: it belongs to the
                    # music platform and is not part of the writer-only standalone.
                    "fixer": bool(k.get("fixer")),
                    "invents_nothing": bool(k.get("no_invention")),
                    "hashtags": key in HASHTAG_KINDS,
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


HASHTAG_KINDS = ("post", "caption")
# The kinds where the lyric/writing dials apply: made things with craft to weigh, not documents
# that make claims about a person (a resume is not "more wordplay").
from .priorities import WRITING_KINDS as PRIORITY_KINDS
HASHTAG_MAX = 30
_TAG = re.compile(r"#\w+", re.UNICODE)


def clean_hashtags(value):
    """How many hashtags the member asked for: None when they did not say (the kind's own
    default applies), else a whole number from 0 to HASHTAG_MAX. Junk is "did not say", never
    a refusal — a stray character must not cost anybody a run."""
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return None
    try:
        n = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return max(0, min(HASHTAG_MAX, n))


def count_hashtags(text):
    return len(_TAG.findall(text or ""))


def fit_hashtags(text, n):
    """Hold the model to the number asked for. Only the TRAILING block of hashtags is touched
    (the last lines made of nothing else): a model that miscounts is trimmed to the first `n`
    — which are the most relevant, because the prompt asks for relevance order — and a tag in
    the middle of a sentence is part of the sentence and stays. Fewer than asked is left as it
    came; the screen reports asked vs got rather than padding with tags nobody chose."""
    if n is None:
        return text
    lines = text.rstrip().split("\n")
    tail = []
    while lines and lines[-1].strip() and not _TAG.sub("", lines[-1]).strip():
        tail.append(lines.pop())
    tags = [t for ln in reversed(tail) for t in _TAG.findall(ln)]
    kept = tags[:n]
    out = "\n".join(lines).rstrip()
    if kept:
        out += ("\n\n" if out else "") + " ".join(kept)
    return out


def hashtag_line(n):
    if n == 0:
        return "HASHTAGS: use no hashtags at all."
    return (f"HASHTAGS: finish with exactly {n} hashtag{'s' if n != 1 else ''}, together on the last line and "
            "nowhere else, ordered from MOST to LEAST relevant to this subject and genre. Each must say "
            "something specific about it — no filler tags (#love, #viral, #fyp) unless they truly fit.")


def prompt_for(kind, topic, genre="", majority=None, minority=None, owner=False, voice=None, hashtags=None):
    k = KINDS[kind]
    ask = k["ask"]
    if hashtags is not None and kind == "caption":
        ask = ask.replace("5-10 relevant hashtags", "the hashtags below")        # one instruction, not two
    lines = [f"Write {ask}.", f"Subject: {topic}"]
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
    register = voice_of(kind)
    custom = voice is not None and voice.is_custom and kind in CREATIVE_KINDS
    plainer = (voice is not None and not voice.is_custom and voice.key == "standard"
               and not voice.follows_style and register == "koth")
    if custom:
        from . import voicez
        lines.append("VOICE: Write the piece in the voice described below.\n" + voicez.FRAME + "\n"
                     + voicez.data_block(voice.voice) + "\n"
                     + "\n".join(voicez.tone_lines(voice.voice, _EMOJI_TEXT))
                     + "\nThe voice colours the wording only; the instructions after this still apply.")
    elif plainer:
        lines.append("VOICE: Write in a clear, natural register with no house style.")
    elif register == "academic":
        # The owner's register is the owner's alone; everyone else gets the plain
        # academic one. `owner` defaults to False so a caller that forgets to say
        # gives the safe version, never somebody else's voice.
        lines.append("VOICE: " + (ACADEMIC_VOICE if owner else ACADEMIC_PLAIN))
    elif register == "koth":
        lines.append("VOICE: " + PERSONAL_VOICE + (" " + LYRIC_STYLE if kind == "lyrics" or kind in FIXERS else ""))
    if k.get("no_invention"):
        lines.append(NO_INVENTION)
    if hashtags is not None and kind in HASHTAG_KINDS:
        lines.append(hashtag_line(hashtags))
    if kind in ("lyrics", *FIXERS, "caption", "post") and not custom and not plainer:
        samples = voice_samples()
        if samples:
            lines.append("Match the voice of these samples — vocabulary, rhythm, wordplay, attitude — "
                         "but never reuse their lines or their subjects:\n" + "\n---\n".join(samples))
    if k.get("json"):
        lines.append("Reply with ONLY the JSON object: no markdown fence, no preamble, no notes.")
    else:
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


def parse_fixes(kind, text):
    """[{line, technique, why, where}] from the model's JSON, cleaned and capped.

    Tolerant of a markdown fence or a sentence around the object; strict about
    what survives: a line with no text is dropped, a technique outside THIS
    kind's closed list becomes 'other', and every field is length-capped. Empty
    list when nothing usable came back, which the caller treats as an empty
    answer (not charged, not saved).
    """
    import json
    techniques = FIXERS[kind]["techniques"]
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return []
    try:
        raw = json.loads(m.group(0)).get("items")
    except (ValueError, AttributeError):
        return []
    out = []
    for it in (raw if isinstance(raw, list) else [])[:FIX_COUNT]:
        if not isinstance(it, dict):
            continue
        line = str(it.get("line", "")).strip()[:300]
        if not line:
            continue
        tech = str(it.get("technique", "")).strip().lower().replace(" ", "_")
        out.append({"line": line, "technique": tech if tech in techniques else "other",
                    "why": str(it.get("why", "")).strip()[:400],
                    "where": str(it.get("where", "")).strip()[:160]})
    return out


def technique_stats(kind):
    """{technique: {avg, n}} — what members rate each technique of ONE kind of
    fix, from the ratings alone. A technique nobody has rated is absent, never 0.
    Grouped per kind: a 'reversal' that works as a punchline says nothing about
    a 'reversal' as a fresh angle."""
    from django.db.models import Avg, Count
    from .models import PunchlineRating
    rows = (PunchlineRating.objects.filter(work__kind=kind)
            .values("technique").annotate(avg=Avg("stars"), n=Count("id")))
    return {r["technique"]: {"avg": round(float(r["avg"]), 2), "n": r["n"]} for r in rows}


def fixer_items(work, user=None):
    """The work's suggestions, ranked by what members rate highest.

    Ranked only where there is evidence: a technique with at least
    MIN_RATINGS_TO_RANK ratings sorts by its members' average; the rest keep the
    writer's own order after them, and say so (`community` is None) instead of
    wearing a made-up number. `my_stars` is this member's own rating of the line.
    """
    from .models import PunchlineRating
    items = (work.inputs or {}).get("items") or []
    techniques = FIXERS.get(work.kind, {}).get("techniques", {})
    stats = technique_stats(work.kind)
    mine = {}
    if user is not None:
        mine = dict(PunchlineRating.objects.filter(work=work, user=user).values_list("idx", "stars"))
    rows = []
    for i, it in enumerate(items):
        st = stats.get(it.get("technique"))
        community = st if st and st["n"] >= MIN_RATINGS_TO_RANK else None
        rows.append({"idx": i, "line": it.get("line", ""), "why": it.get("why", ""),
                     "where": it.get("where", ""), "technique": it.get("technique", "other"),
                     "technique_label": techniques.get(it.get("technique"), "Other"),
                     "community": community, "my_stars": mine.get(i)})
    rows.sort(key=lambda r: (0, -r["community"]["avg"], r["idx"]) if r["community"] else (1, 0, r["idx"]))
    return rows


def _work_dict(w, user=None):
    extra = {}
    if w.kind in FIXERS:
        extra = {"items": fixer_items(w, user),
                 "rank_note": ("Ranked by what members rate highest, once a technique has "
                               f"{MIN_RATINGS_TO_RANK} ratings. Until then they are in the writer's order "
                               "and say so.")}
    return {"id": w.id, "kind": w.kind, "label": KINDS.get(w.kind, {}).get("label", w.kind),
            "topic": w.topic, "text": w.text, "inputs": w.inputs,
            "created_at": w.created_at.isoformat(),
            "legal_note": LEGAL_NOTE if w.kind in LEGAL_KINDS else "",
            "note": FILL_NOTE if KINDS.get(w.kind, {}).get("no_invention") else "",
            **extra}


def write_piece(user, kind, topic, genre="", majority=None, minority=None, *, spend_note=None, extra_inputs=None,
                hashtags=None, priorities=None, reference=None):
    """Write ONE piece for `user` and bill it, or answer why not — the whole of what
    pressing Write does, so that every door into the writer (the screen, a past take's
    promo post) is the same run with the same price, the same "a failed run is not
    charged" and the same saved SentenceWork. `kind` and `topic` are already validated
    by the caller; everything else is checked here."""
    deadline = Deadline(BUDGET_SECONDS)
    # A sound or picture to start from: checked before anything is priced, so a bad file is a
    # sentence and no charge. Only the craft kinds take one.
    ref, ref_problem = refinput.parse(reference if kind in PRIORITY_KINDS else None)
    if ref_problem:
        return Response({"detail": ref_problem}, status=status.HTTP_400_BAD_REQUEST)
    need = KINDS[kind].get("personas")
    if need and not (persona_keys(user) & set(need)):
        return Response({"detail": f"{KINDS[kind]['label']}s are written for members with the "
                                   "Manager or A&R Scout PersonaZ. Add one in ProfileZ.",
                         "needs": ["Manager", "A&R Scout"]}, status=status.HTTP_403_FORBIDDEN)
    cap = over_writer_brief(topic, membership_for(user).tier)
    if cap:
        return Response({"detail": f"Your tier takes up to {cap:,} characters of brief here — upgrade in MembershipZ for more.", "char_limit": cap},
                        status=status.HTTP_400_BAD_REQUEST)
    key = _key()
    if not key:
        return Response({"detail": "Sentence ConnectZ isn't switched on — the backend is missing GEMINI_API_KEY."},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    cost = ai_cost("standard")
    _, _, daily_left = daily_prompt_state(user)
    free = daily_left > 0 and daily_prompt_covers(cost)
    if cost and not free and not can_afford_ai(user, cost):
        return Response({"detail": "Not enough PromptZ or balance for this one.", "cost_cents": cost},
                        status=status.HTTP_402_PAYMENT_REQUIRED)

    body = {"contents": [{"parts": [{"text": prompt_for(kind, topic, genre, majority, minority,
                                                        owner=bool(is_owner_candidate(user)),
                                                        voice=resolve(user, "writer"),
                                                        hashtags=hashtags if kind in HASHTAG_KINDS else None)
                                      + priorities_clause("writing", priorities) + refinput.guard(ref)},
                                     *([refinput.part(ref)] if ref else [])]}],
            "generationConfig": {"temperature": 0.9}}
    try:
        deadline.check("the request was still being prepared when the time ran out")
        resp, tried = generate_content("text", body, key=key, timeout=deadline.remaining(cap=60),
                                       label="Sentence ConnectZ")
        # `generate_content` walks a chain of models with ONE timeout each, so
        # a call can overrun the budget by more than it was given. An answer
        # that lands after the member's wait is over is not billed: the screen
        # was told it was still running, and nothing here is theirs yet.
        deadline.check("the writer was still going when the time ran out")
    except Expired as e:
        logger.warning("Sentence ConnectZ: over budget after %.0fs — %s", deadline.spent(), e.message)
        return Response({"detail": f"The writer is taking longer than it should — {e.message}. "
                                   "Nothing was charged. Try a shorter brief, or the same one again "
                                   "in a minute.",
                         "timed_out": True, "waited_seconds": int(deadline.spent())},
                        status=status.HTTP_504_GATEWAY_TIMEOUT)
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

    asked = hashtags if kind in HASHTAG_KINDS else None
    if asked is not None:
        text = fit_hashtags(text, asked)
    items = []
    if kind in FIXERS:
        items = parse_fixes(kind, text)
        if not items:
            # Nothing usable in the reply is an empty answer: not charged, not saved.
            logger.error("Sentence ConnectZ: %s reply had no usable items — %s", kind, text[:300])
            return Response({"detail": "The writer came back with nothing usable. Nothing was charged — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        # What is stored, and so what the royalty is measured against, is the
        # lines alone: the member uses a line, not the writer's commentary on it.
        text = "\n".join(it["line"] for it in items)

    from django.utils import timezone as _tz
    _t0 = _tz.now()
    _note = spend_note or f"Sentence ConnectZ — {KINDS[kind]['label']}"
    charged = _bill(user, _note, count_daily=True)
    if charged is None:
        return Response({"detail": "Not enough PromptZ or balance for this one.", "cost_cents": cost},
                        status=status.HTTP_402_PAYMENT_REQUIRED)
    work = SentenceWork.objects.create(
        user=user, kind=kind, topic=topic, text=text,
        inputs={"genre": genre, "majority": majority, "minority": minority,
                **({"hashtags": asked} if asked is not None else {}),
                **({"items": items} if kind in FIXERS else {}), **(extra_inputs or {})},
    )
    from .models import link_spend
    link_spend(user, f"sentence:{work.id}", _t0, _note)
    extra = {}
    if asked is not None:
        # Asked vs got, so the screen never claims a number the text does not have.
        extra["hashtags"] = {"asked": asked, "got": count_hashtags(text)}
    return Response({**_work_dict(work, user), "charged_cents": charged, **extra},
                    status=status.HTTP_201_CREATED)


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
            "budget_seconds": BUDGET_SECONDS,
            "royalty_pct": KOTH_ROYALTY_PCT,
            "royalty_rule": (f"Using a piece in DistributeZ, CollabZ or BattleZ pays K-Oth "
                             f"{KOTH_ROYALTY_PCT}% of it, scaled by how much of the original you kept — "
                             f"keep half and it's {KOTH_ROYALTY_PCT / 2:g}%."),
            "legal_note": LEGAL_NOTE,
            "fix_min_ratings": MIN_RATINGS_TO_RANK,
            "fixers": {k: {"dim": f["dim"], "label": f["label"]} for k, f in FIXERS.items()},
            "rhyme_max": 4,
            "inspiration_note": INSPIRATION_NOTE,
            "hashtag_max": HASHTAG_MAX,
            "works": [_work_dict(w, request.user) for w in works],
        })

    def post(self, request):
        d = request.data or {}
        kind = str(d.get("kind", "")).strip()
        if kind not in KINDS:
            return Response({"detail": "Pick what to write."}, status=status.HTTP_400_BAD_REQUEST)
        topic = str(d.get("topic", "")).strip()
        if not topic:
            return Response({"detail": "Say what it's about."}, status=status.HTTP_400_BAD_REQUEST)
        genre = str(d.get("genre", "")).strip()[:60]
        majority = _int(d.get("majority"), 0, 4) if kind == "lyrics" else None
        minority = _int(d.get("minority"), 0, 4) if kind == "lyrics" else None
        return write_piece(request.user, kind, topic, genre, majority, minority,
                           hashtags=clean_hashtags(d.get("hashtags")) if kind in HASHTAG_KINDS else None,
                           priorities=d.get("priorities") if kind in PRIORITY_KINDS else None,
                           reference=d.get("reference") if kind in PRIORITY_KINDS else None)


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


class PunchlineRateView(APIView):
    """POST {stars: 1-5}: rate one suggested line from any fixer writer. Only the member it was
    written for can rate it, once per line (a second rating replaces the first)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk, idx):
        from .models import PunchlineRating
        work = SentenceWork.objects.filter(pk=pk, user=request.user, kind__in=list(FIXERS)).first()
        items = (work.inputs or {}).get("items") if work else None
        if not work or not isinstance(items, list) or not (0 <= idx < len(items)):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            stars = int((request.data or {}).get("stars"))
        except (TypeError, ValueError):
            stars = None
        # Out of range is refused, not clamped: a 9 is not a 5, it is a mistake.
        if stars is None or not 1 <= stars <= 5:
            return Response({"detail": "Rate it from 1 to 5."}, status=status.HTTP_400_BAD_REQUEST)
        PunchlineRating.objects.update_or_create(
            work=work, user=request.user, idx=idx,
            defaults={"stars": stars, "technique": str(items[idx].get("technique") or "other")[:24]})
        return Response({"items": fixer_items(work, request.user)})


# ---- Inspiration: how a song you admire does the thing you are fixing ------

INSPIRATION_NOTE = ("Use music you have the right to analyse. The coach listens to a song you admire and describes "
                    "HOW it does this technique — never its words. That direction is added to your brief; you still "
                    "press Write (priced separately) and the lines are new and yours. The song isn't kept.")


def inspiration_prompt(kind):
    spec = KINDS[kind]
    core = FIXERS[kind]["core"] if kind in FIXERS else spec.get("ask", kind)
    return (f"You are given a reference song. A writer wants to get better at: {spec['label']}. {core}\n"
            "Describe HOW this song does it - the habits, moves and structure - as an instruction the writer "
            "can follow in their OWN words. NEVER quote, reproduce or paraphrase line-by-line any of the song's "
            "lyrics, and do not name the artist. If there are no words to hear, say so.\n"
            'Reply with JSON only: {"unscorable": <null or one sentence>, "direction": "<3-5 sentences>", '
            '"moves": ["<short technique name>", ...]}')


def clean_direction(parsed):
    if not isinstance(parsed, dict):
        return None
    d = str(parsed.get("direction", "")).strip()[:900]
    if not d:
        return None
    moves = [str(m).strip()[:60] for m in (parsed.get("moves") or []) if str(m).strip()][:6]
    return {"direction": d, "moves": moves}


class SentenceInspirationView(APIView):
    """POST reference song + kind → a direction to add to the brief. Nothing written, nothing kept."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from . import vocalcoach as vc
        f = request.FILES.get("reference")
        kind = str(request.data.get("kind", ""))
        if kind not in KINDS or KINDS[kind].get("personas"):
            return Response({"detail": "Pick a kind to take inspiration for."}, status=status.HTTP_400_BAD_REQUEST)
        if not f or f.size == 0:
            return Response({"detail": "Pick the song you admire."}, status=status.HTTP_400_BAD_REQUEST)
        ct = (getattr(f, "content_type", "") or "").lower()
        mime = vc.gemini_mime(ct) if ct.startswith(("audio/", "video/")) else None
        if not mime:
            return Response({"detail": "Use an m4a, mp3, wav, ogg or mp4 file."}, status=status.HTTP_400_BAD_REQUEST)
        cap_mb, is_tier = vc.cap_for(request.user)
        if f.size > cap_mb * 1024 * 1024:
            return Response({"detail": f"That file is {f.size / (1024 * 1024):.0f}MB. " + vc.cap_why(cap_mb, is_tier)},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        key = _key()
        if not key:
            return Response({"detail": "Sentence ConnectZ isn't switched on."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
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
            body = {"contents": [{"parts": [{"text": inspiration_prompt(kind)}, part]}],
                    "generationConfig": {"temperature": 0.3}}
            resp, _ = generate_content("text", body, key=key, timeout=deadline.remaining(cap=120),
                                       env_vars=("GEMINI_AUDIO_MODEL",), label="Sentence Inspiration")
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
                    logger.exception("Sentence Inspiration: cleanup failed")
        text = _text_of(resp) if resp is not None and resp.status_code == 200 else ""
        m = re.search(r"\{.*\}", text or "", re.S)
        try:
            parsed = json.loads(m.group(0)) if m else None
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and str(parsed.get("unscorable") or "").strip():
            return Response({"unscorable": str(parsed["unscorable"]).strip()[:300], "cost_cents": 0})
        out = clean_direction(parsed)
        if not out:
            return Response({"detail": "The coach's answer wasn't usable. Nothing was charged — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        charged = _bill(request.user, f"Sentence ConnectZ Inspiration ({kind}) — AI", count_daily=True)
        if charged is None:
            return Response({"detail": "Not enough PromptZ or balance for this one.", "cost_cents": cost},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        return Response({**out, "kind": kind, "cost_cents": charged, "saved": False})
