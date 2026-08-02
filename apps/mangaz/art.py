"""Draw MangaZ art from a CharacterZ. Premium and StatZ only.

This is the Premium hook: paying members turn a character sheet into cover and
page art, so the same face shows up drawn the same way across a whole book.

Two decisions worth stating:

**It's a capability, not chrome.** The MangaZ icon, the tabs and the app itself
stay free for everyone. What Premium buys is the ability to MAKE something —
which is what people actually pay for, and what keeps paying rather than
feeling nickel-and-dimed by a prettier button.

**It reuses Image ConnectZ.** The generation, the billing and the 503-when-
unconfigured behaviour all come from `economy.gemini`, so there is one image
pipeline and one place that charges for it. A second copy would drift on price,
on model name, and eventually on who gets charged.

The character's face, when they have one, is passed as a reference image, so
"draw Rin again" produces Rin rather than a new stranger with the same name.
"""
import base64
import logging
import os

import requests
from django.conf import settings

from apps.economy.catalog import ai_cost
from apps.economy.models import (TIER_DEBUG, TIER_PREMIUM, TIER_STATZ,
                                 can_afford_ai, charge_ai_usage,
                                 membership_for, wallet_for)

logger = logging.getLogger(__name__)

BASE = "https://generativelanguage.googleapis.com/v1beta"

# Who may generate art. Free members get all of MangaZ except this.
ART_TIERS = {TIER_PREMIUM, TIER_STATZ, TIER_DEBUG}

# House style, applied to every MangaZ generation. Rooms can contain minors, so
# this is not a place to inherit whatever the member's other prompts set.
STYLE = ("Black and white manga panel art, clean linework, screentone shading. "
         "Suitable for a mixed-age collaborative room: no sexual content, no "
         "graphic violence, nothing needing an adult rating.")


class ArtUnavailable(RuntimeError):
    """The image service can't be reached. A 503, not a 500 — a dependency is
    down, the member did nothing wrong, and their page must survive it."""


class ArtNotAllowed(RuntimeError):
    """Their tier doesn't include art generation. Carries the upgrade path so
    the refusal is a door rather than a wall."""


def can_generate(user):
    return membership_for(user).tier in ART_TIERS


def _key():
    return (getattr(settings, "GEMINI_API_KEY", "")
            or os.environ.get("GEMINI_API_KEY", ""))


def build_prompt(character, brief=""):
    """What the model is told. Explicit, so a member can see what was drawn
    from — art generated from hidden inputs is art nobody can correct."""
    sheet = character.prompt_sheet()
    bits = [STYLE, f"Character: {sheet['name']}."]
    if sheet.get("bio"):
        bits.append(f"Who they are: {sheet['bio']}")
    if sheet.get("traits"):
        bits.append("Traits: " + ", ".join(sheet["traits"]) + ".")
    if brief.strip():
        bits.append(f"This panel: {brief.strip()[:600]}")
    return " ".join(bits), sheet


def _reference(character):
    """The character's FaceZ image as base64, when they have one.

    This is what makes a cast recognisable across a book. Read failures are
    swallowed on purpose — a missing file should cost you likeness, not the
    whole page.
    """
    face = character.face
    if not face or not getattr(face, "image", None):
        return None
    try:
        with face.image.open("rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")
    except Exception as exc:
        logger.info("mangaz: reference image unreadable for character %s: %s",
                    character.id, exc)
        return None


def draw_from_character(user, character, brief=""):
    """Generate art for this character. Returns (data_uri, prompt_record, model).

    Raises ArtNotAllowed if their tier doesn't include it, and ArtUnavailable
    for anything else — an unconfigured key, a network failure, a model that
    returned no image. All of those are the same thing to the member.
    """
    if not can_generate(user):
        raise ArtNotAllowed(
            "Generating art from your CharacterZ is a Premium feature. "
            "Everything else in MangaZ — writing, collabs, rooms — stays free.")
    key = _key()
    if not key:
        raise ArtUnavailable(
            "Art generation isn't configured on this server yet — set "
            "GEMINI_API_KEY. Your page is safe; add art by hand for now.")

    cost = ai_cost("standard")
    if cost and not can_afford_ai(user, cost):
        raise ArtUnavailable(
            "Not enough PromptZ or balance to generate art right now.")

    prompt, sheet = build_prompt(character, brief)
    model = os.environ.get("GEMINI_IMAGE_MODEL",
                           "gemini-2.5-flash-image-preview")
    parts = [{"text": prompt}]
    reference = _reference(character)
    if reference:
        parts.insert(0, {"inlineData": {"mimeType": "image/jpeg",
                                        "data": reference}})
    try:
        r = requests.post(
            f"{BASE}/models/{model}:generateContent?key={key}",
            json={"contents": [{"parts": parts}],
                  "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}},
            timeout=90,
        )
        data = r.json()
        img, mime = None, "image/png"
        for part in (data.get("candidates") or [{}])[0].get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                img = inline["data"]
                mime = inline.get("mimeType") or inline.get("mime_type") or mime
                break
        if not img:
            detail = (data.get("error") or {}).get("message") or "No image returned."
            raise ArtUnavailable(f"Image service: {detail}"[:200])
    except ArtUnavailable:
        raise
    except Exception as exc:
        logger.warning("mangaz: art generation failed: %s", exc)
        raise ArtUnavailable(
            "The art didn't come back just now. Nothing was charged — try "
            "again, or add art by hand.") from exc

    # Charged only after an image actually exists. Billing a member for a call
    # that returned nothing is the thing that ends a subscription.
    charged = 0
    if cost:
        charge_ai_usage(user, cost, note=f"MangaZ art: {character.name}")
        charged = cost
    record = {"mode": "character_art", "sheet": sheet, "brief": brief[:600],
              "used_reference": bool(reference), "cost_cents": charged}
    return f"data:{mime};base64,{img}", record, model
