"""ImageZ's AI background removal: one photo in, the subject's outline out.

The editor (frontend `src/apps/ImageZ.jsx`) runs on the member's device; this is the one
part of it that needs a model. It sends the picture it is editing, Gemini answers with
segmentation masks for the main subject(s) — a box and a small PNG per subject — and the
editor turns them into a LAYER MASK, so nothing is erased: the member can paint the mask
back wherever the model was wrong.

* **StatZ, and the daily sample** (`statz_trial` feature `imagez_cutout`) — Corey's call.
  The editor's own cut-out tools (masks, selections, the plain eraser) stay free, so the
  tier buys speed, never whether.
* **Priced at what the model actually used, with the range on the button.** A mask comes back
  as a picture, which is the expensive part of the answer, so a busy photo costs more than a
  plain one. The run is billed from Gemini's own token count at its list price, rounded up,
  never under `MIN_CENTS` and never over `MAX_CENTS` (the output is capped so it cannot cost
  more). `MAX_CENTS` is the daily free prompt's ceiling, so a free prompt always covers it;
  otherwise it is that many 🏷️. Plus the ⚡ every AI run takes, by tier. A picture with no
  clear subject is not charged at all.
* **Nothing is kept.** The photo is read and discarded; no Upload row, nothing logged but
  the size. What the member keeps is the mask in their own picture.
* **Nothing a model wrote reaches the screen unchecked.** A mask must be a PNG data URL of
  bounded size and a box four numbers inside 0..1000, or it is dropped.

Like every Gemini path here, this has never run against Google from CI (no key there).
"""
import base64
import logging
import re

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .gemini import _key, generate_content
from .models import can_afford_ai, daily_prompt_state
from .statz_trial import UPGRADE, has_statz

logger = logging.getLogger(__name__)

FEATURE = "imagez_cutout"
LABEL = "Remove background (AI) in ImageZ"
LOCKED = ("AI background removal is a StatZ feature. Try it in today's free StatZ minutes, or cut out by hand "
          "with a mask, a selection or the eraser — those are free at every tier.")
WHAT_IT_DOES = ("Finds the main subject and puts it on a layer mask — the background is hidden, not deleted, "
                "so you can paint back anything it got wrong.")
MAX_BYTES = 8 * 1024 * 1024
MAX_SUBJECTS = 5
MASK_MAX_CHARS = 3_000_000
# Gemini 2.5 Flash list prices, in cents per million tokens (input, output). Corey: price it
# appropriately — what it costs us, passed through, never a flat guess.
IN_CENTS_PER_M, OUT_CENTS_PER_M = 30, 250
MAX_OUTPUT_TOKENS = 12_000          # 12k × 250¢/M = 3¢: the output can never cost more than MAX_CENTS
MIN_CENTS, MAX_CENTS = 1, 3
MIMES = {"image/png", "image/jpeg", "image/webp"}
_DATA_URL = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\s]+)$")

PROMPT = (
    "Find the main subject or subjects of this picture — the people, animals or objects a viewer would call the "
    "subject, not the background. Give the segmentation masks for up to " + str(MAX_SUBJECTS) + " of them. "
    'Answer ONLY with JSON: a list of objects, each {"label": a few words, "box_2d": [y0, x0, y1, x1] on a 0-1000 '
    'scale, "mask": a base64 PNG data URL of the mask inside that box}. If there is no clear subject, answer [].'
)


def _decode(data_url):
    m = _DATA_URL.match((data_url or "").strip())
    if not m or m.group(1) not in MIMES:
        return None, None
    try:
        raw = base64.b64decode(re.sub(r"\s", "", m.group(2)), validate=True)
    except (ValueError, TypeError):
        return None, None
    return m.group(1), raw


def _parse_json(text):
    from .attractivenessz import _parse
    text = (text or "").strip()
    if text.startswith("["):
        import json
        try:
            return json.loads(text)
        except ValueError:
            pass
    fenced = re.search(r"\[[\s\S]*\]", text)
    if fenced:
        import json
        try:
            return json.loads(fenced.group(0))
        except ValueError:
            pass
    parsed = _parse(text)
    return parsed if isinstance(parsed, list) else (parsed or {}).get("masks") or []


def clean_masks(items):
    """Only well-formed masks survive: a PNG data URL of bounded size and a box inside 0..1000."""
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        box = it.get("box_2d")
        mask = it.get("mask")
        if not (isinstance(box, list) and len(box) == 4):
            continue
        try:
            y0, x0, y1, x1 = (int(round(float(v))) for v in box)
        except (TypeError, ValueError):
            continue
        if not (0 <= y0 < y1 <= 1000 and 0 <= x0 < x1 <= 1000):
            continue
        if not isinstance(mask, str):
            continue
        if not mask.startswith("data:"):
            mask = "data:image/png;base64," + mask
        if len(mask) > MASK_MAX_CHARS or not mask.startswith("data:image/png;base64,"):
            continue
        mime, raw = _decode(mask)
        if mime != "image/png" or not raw or not raw.startswith(b"\x89PNG"):
            continue
        out.append({"label": str(it.get("label") or "subject")[:60], "box": [y0, x0, y1, x1], "mask": mask})
        if len(out) >= MAX_SUBJECTS:
            break
    return out


def price_from_usage(usage):
    """Cents for one run from Gemini's usageMetadata, rounded up, between MIN_CENTS and MAX_CENTS."""
    import math
    usage = usage if isinstance(usage, dict) else {}
    try:
        tin = int(usage.get("promptTokenCount") or 0)
        tout = int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
    except (TypeError, ValueError):
        return MAX_CENTS
    if not tin and not tout:
        return MAX_CENTS        # no count means we cannot show it was cheaper: charge the stated top
    return max(MIN_CENTS, min(MAX_CENTS, math.ceil((tin * IN_CENTS_PER_M + tout * OUT_CENTS_PER_M) / 1_000_000)))


def _charge(user, cents):
    """`gemini._bill` at this run's real price: a free daily prompt first, then PromptZ, then cash —
    and nothing reaches the owner's wallet when a free prompt paid."""
    from .models import charge_ai_usage, daily_prompt_covers
    from .views import credit_owner
    _, _, left = daily_prompt_state(user)
    free = daily_prompt_covers(cents) and left > 0
    if charge_ai_usage(user, cents, note="ImageZ — AI background removal", count_daily=True) is None:
        return None
    if free:
        return 0
    credit_owner(user, cents, "ImageZ — AI background removal")
    return cents


def state(user):
    from .models import ai_energy_cost
    cost = MAX_CENTS
    _, _, left = daily_prompt_state(user)
    allowed = has_statz(user)
    return {
        "feature": FEATURE, "label": LABEL, "allowed": allowed, "locked_reason": "" if allowed else LOCKED,
        "upgrade": UPGRADE, "what_it_does": WHAT_IT_DOES, "cost_cents": cost, "cost_min_cents": MIN_CENTS,
        "cost_note": f"{MIN_CENTS}–{MAX_CENTS} 🏷️ — what the AI actually used, rounded up — or one free daily prompt.",
        "energy_cost": ai_energy_cost(user), "free_today": bool(cost) and left > 0,
        "affordable": bool(not cost or left > 0 or can_afford_ai(user, cost)), "charged_on_failure": False,
        "configured": bool(_key()), "max_mb": MAX_BYTES // (1024 * 1024),
    }


class ImageZCutoutView(APIView):
    """GET /api/economy/imagez/cutout/ — the price and whether this member may run it.
    POST {image: data URL} — the subject masks, billed only when one came back."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(state(request.user))

    def post(self, request):
        st = state(request.user)
        if not st["allowed"]:
            return Response({**st, "detail": LOCKED}, status=status.HTTP_403_FORBIDDEN)
        if not st["configured"]:
            return Response({**st, "detail": "The AI isn't switched on yet. Nothing was charged."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not st["affordable"]:
            return Response({**st, "detail": f"A run costs {st['cost_cents']} 🏷️ and today's free prompts are spent."},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        mime, raw = _decode(str((request.data or {}).get("image") or ""))
        if not raw:
            return Response({"detail": "Send the picture as a PNG, JPEG or WebP. Nothing was charged."},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(raw) > MAX_BYTES:
            return Response({"detail": f"That picture is over {st['max_mb']} MB — make the image size smaller first. "
                                       "Nothing was charged."}, status=status.HTTP_400_BAD_REQUEST)
        body = {"contents": [{"parts": [{"text": PROMPT},
                                        {"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode()}}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": MAX_OUTPUT_TOKENS,
                                     "thinkingConfig": {"thinkingBudget": 0}}}
        try:
            resp, _tried = generate_content("text", body, key=_key(), timeout=90, label="ImageZ cut-out")
        except requests.RequestException:
            logger.exception("ImageZ cut-out: could not reach Gemini")
            return Response({"detail": "Couldn't reach the AI — nothing was charged."}, status=status.HTTP_502_BAD_GATEWAY)
        if resp.status_code != 200:
            logger.error("ImageZ cut-out: Gemini %s — %s", resp.status_code, resp.text[:300])
            return Response({"detail": "The AI couldn't read that picture right now — nothing was charged."},
                            status=status.HTTP_502_BAD_GATEWAY)
        try:
            payload = resp.json()
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError):
            payload, text = {}, ""
        masks = clean_masks(_parse_json(text))
        if not masks:
            return Response({"masks": [], "cost_cents": 0,
                             "detail": "The AI found no clear subject to cut out — nothing was charged."})
        price = price_from_usage(payload.get("usageMetadata"))
        charged = _charge(request.user, price)
        return Response({"masks": masks, "cost_cents": charged, "price_cents": price})
