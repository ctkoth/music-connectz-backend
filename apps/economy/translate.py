"""TranslateZ — neutral transcreation endpoint powering LanguageZ.

Transcreates (culturally adapts, not literal) a batch of UI strings or user
content into a target language, preserving emoji, placeholders, and brand names.
Runs server-side so the Anthropic key never touches the client. Charges the
model minimum ONCE per batch (like OCC) on success; 402 when the member can't
afford it, 503 when the LLM backend isn't configured (the client keeps the
original English and does not charge).
"""
import json

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .ai_price import ai_price
from .catalog import ai_cost
from .models import charge_ai_usage, can_afford_ai, wallet_for
from .views import credit_owner

TRANSLATE_MODEL = "claude-opus-4-8"
MAX_TEXTS = 60

# Brand/app names that must never be translated.
_BRANDS = (
    "Music ConnectZ, MCZ, CollabZ, BattleZ, VenueZ, MerchZ, SpinAZ, Energy, "
    "PersonaZ, NationalitieZ, SubstanceZ, PreferenceZ, ZodiacZ, LanguageZ, "
    "DirectZ, SingZ, RapZ, BodieZ, DawZ, OCC, RateZ, LabelZ, DistributeZ, "
    "RoyaltieZ, SpecZ, Lilith, GroupZ, MessageZ, CallZ, AdZ, GameZ, StatZ, Premium, Free"
)


def _system(target_name):
    return (
        f"You are a professional transcreator. Transcreate each input string into {target_name}. "
        "Transcreate — culturally adapt so it reads natural and native, not a literal word-for-word swap. "
        "Rules you MUST follow: (1) Preserve every emoji exactly, in the same spots. "
        "(2) Preserve placeholders, numbers, %, currency symbols, and $-style tokens exactly. "
        f"(3) Never translate these brand/app names, keep them verbatim: {_BRANDS}. "
        "(4) Keep it concise — UI labels stay short. "
        "(5) Return ONLY a compact JSON array of strings, same length and order as the input, no prose, no keys."
    )


def _configured():
    """Whether the transcreation backend can actually run — the client, not just
    the import. An unconfigured endpoint is unavailable, not free."""
    try:
        import anthropic
    except ImportError:                                      # pragma: no cover
        return False
    try:
        anthropic.Anthropic()
    except Exception:                                        # pragma: no cover
        return False
    return True


class TranslateView(APIView):
    """GET  → what one batch costs this member, before they send one.
    POST { texts: [str], target_lang, target_name?, source_lang? } → transcreated
    strings. Charges the model minimum once per batch on success."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """The price of a batch, stated before the batch.

        Worth being precise about what the unit is: this charges ONCE per batch
        of up to MAX_TEXTS strings, not once per string. A member quoted a
        per-string price would batch defensively and pay the same either way.
        """
        out = ai_price(
            request.user,
            configured=_configured(),
            # `charge_ai_usage` below is called without `count_daily`, so the
            # day's free prompts do not cover a batch.
            uses_allowance=False,
            # Nothing is charged until an array of the right length parses out
            # of the model's answer — a 503 on the backend, the parse, or the
            # length check all return before the charge.
            charged_on_failure=False,
            failure_note="A batch that doesn't come back translated isn't "
                         "charged — the charge runs only after one parses.",
            action="Transcreate a batch",
        )
        # Priced per batch, not per string, and per batch is the number that
        # decides how a member uses this.
        out["unit"] = "batch"
        out["max_texts"] = MAX_TEXTS
        # English costs nothing because there is nothing to do — the POST
        # short-circuits before the model. A price line that ignored this would
        # quote a charge for a no-op.
        out["free_langs"] = ["en", "eng", "english"]
        return Response(out)

    def post(self, request):
        data = request.data or {}
        texts = data.get("texts") or []
        if isinstance(texts, str):
            texts = [texts]
        texts = [str(t) for t in texts][:MAX_TEXTS]
        target_lang = str(data.get("target_lang", "")).strip().lower()
        target_name = str(data.get("target_name", "") or target_lang).strip() or target_lang
        if not texts or not target_lang:
            return Response({"detail": "texts and target_lang are required."}, status=status.HTTP_400_BAD_REQUEST)
        # No-op for English or empty payloads — free.
        if target_lang in ("en", "eng", "english") or not any(t.strip() for t in texts):
            return Response({"translations": texts, "cost_cents": 0, "money": round(wallet_for(request.user).money_cents / 100, 2)})

        cost = ai_cost("standard")
        if cost and not can_afford_ai(request.user, cost):
            return Response(
                {"detail": "Not enough balance to translate.", "cost_cents": cost},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        try:
            import anthropic
        except ImportError:
            return Response({"detail": "Translation backend unavailable.", "translations": None},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model=TRANSLATE_MODEL,
                max_tokens=2048,
                system=_system(target_name),
                messages=[{"role": "user", "content": json.dumps(texts, ensure_ascii=False)}],
            )
            raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        except Exception as exc:
            return Response({"detail": f"Translation backend error: {exc}"[:200], "translations": None},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Parse the JSON array; tolerate code fences or stray prose around it.
        out = None
        try:
            out = json.loads(raw)
        except Exception:
            a, b = raw.find("["), raw.rfind("]")
            if a != -1 and b != -1 and b > a:
                try:
                    out = json.loads(raw[a:b + 1])
                except Exception:
                    out = None
        if not isinstance(out, list) or len(out) != len(texts):
            return Response({"detail": "Could not parse translation.", "translations": None},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        out = [str(x) for x in out]

        remaining = charge_ai_usage(request.user, cost, note=f"TranslateZ {target_lang}")
        credit_owner(request.user, cost, f"TranslateZ {target_lang}")
        money = round((remaining if remaining is not None else wallet_for(request.user).money_cents) / 100, 2)
        return Response({"translations": out, "cost_cents": cost, "money": money})
