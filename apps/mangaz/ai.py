"""The Intelligence AI write paths for MangaZ.

Two ways a member gets AI writing, and both build the prompt here rather than
taking one from the client. A client-supplied prompt would let somebody use
the platform's key for anything at all, and would make "what was this written
from" unanswerable.

Nothing here decides the royalty. The caller records `source` on the Page and
`MangaZ.ai_royalty_cents` reads it back off the pages — so the charge follows
what was actually generated, not what anyone claimed.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

MODEL = os.environ.get("MANGAZ_AI_MODEL", "claude-sonnet-5")
MAX_TOKENS = 1200

# House rules that go on every MangaZ generation. Stated here, once, because a
# room can contain minors — this is not a place to inherit whatever tone the
# member's other prompts happened to set.
SYSTEM = (
    "You write manga scripts for Music ConnectZ. Return page-ready script: "
    "panel directions in brackets, dialogue as CHARACTER: line. Keep it "
    "suitable for a mixed-age collaborative room — no sexual content, no "
    "graphic violence, nothing that would need an adult rating. Write the "
    "characters as described and do not invent new ones unless asked."
)


class AiUnavailable(RuntimeError):
    """Raised when the model can't be reached. Surfaced as a 503 rather than a
    500 — it's a dependency being down, not the member doing anything wrong."""


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise AiUnavailable(
            "AI writing isn't configured on this server yet — set "
            "ANTHROPIC_API_KEY. Your script is safe; save the page by hand.")
    try:
        import anthropic
    except ImportError as exc:            # pragma: no cover
        raise AiUnavailable("The AI client isn't installed.") from exc
    return anthropic.Anthropic(api_key=key)


def _run(prompt):
    """Send one prompt. Returns the text. Raises AiUnavailable on any failure.

    Deliberately catches broadly: every failure mode here — network, rate
    limit, a model that stopped existing — is the same thing to the member,
    which is "not right now", and none of them should lose the page they were
    part-way through writing.
    """
    client = _client()
    try:
        message = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
            messages=[{"role": "user", "content": prompt}])
        return "".join(block.text for block in message.content
                       if getattr(block, "type", "") == "text").strip()
    except AiUnavailable:
        raise
    except Exception as exc:
        logger.warning("mangaz: AI call failed: %s", exc)
        raise AiUnavailable(
            "The AI didn't answer just now. Nothing was charged — try again, "
            "or write the page by hand.") from exc


def write_from_script(user, script):
    """Lay a member's own script out as manga pages.

    The member wrote the words. The AI is doing panel breakdown, which is why
    this still counts as AI-assisted: the output is generated, even though the
    story isn't.
    """
    prompt = (
        "Lay this script out as a manga page. Keep the writer's words — break "
        "them into panels, add panel directions, and do not rewrite the "
        "dialogue.\n\n"
        f"{script.strip()[:8000]}")
    text = _run(prompt)
    return text, {"mode": "script", "script_chars": len(script)}, MODEL


def write_from_character(user, character, beat=""):
    """Write a page as this character, from their sheet.

    The character's bio, MBTI and voice are the whole point — an AI writing
    "a character" with nothing to go on writes the same person every time, and
    the sheet is what makes two members' casts sound different.
    """
    sheet = character.prompt_sheet()
    ask = beat.strip() or "Write the next page of their story."
    prompt = (
        "Write a manga page for this character. Their sheet:\n"
        f"{json.dumps(sheet, indent=2)}\n\n"
        f"What should happen: {ask[:2000]}\n\n"
        "Write them consistently with the sheet — the MBTI and the voice note "
        "are how they behave and how they talk, not decoration.")
    text = _run(prompt)
    return text, {"mode": "character", "sheet": sheet, "beat": ask[:2000]}, MODEL
