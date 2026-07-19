"""OCC's real LLM backend — Corey GPT and the other OCC voices.

Runs server-side so the Anthropic API key never touches the client. Charges the
minimum model cost (pass-through, owner-free) only on a successful generation;
if the key isn't configured the endpoint returns 503 and the frontend falls back
to its built-in templated replies.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import ai_cost
from .models import charge_ai_usage, wallet_for
from .views import is_owner

# House model that powers every OCC voice. The "voice" only shapes the system
# prompt/tone (and the per-message price) — the underlying model is the same.
OCC_LLM_MODEL = "claude-opus-4-8"

VOICE_STYLE = {
    "corey-gpt": (
        "You are OCC (Ocular Code ConnectZ) speaking as Corey / K-Oth — the founder "
        "voice of Music ConnectZ. Confident, street-smart, encouraging, plain-spoken; "
        "light slang is fine ('say less', 'bet', 'straight up'), never corny. Break work "
        "into a short numbered plan, then offer the next move. "
        "Use emoji generously — lead lines and headers with a fitting emoji, tag each "
        "step in a plan with one, and drop them naturally through your sentences to set "
        "the vibe (🎤🔥💯🚀🎧✅👀💪🎨🎼📣⚖️). At least a few per reply; keep them relevant, "
        "never a wall of emoji and never mid-word."
    ),
    "standard": "You are OCC, a clear, neutral, friendly coding and creative assistant for Music ConnectZ.",
    "technical": "You are OCC in terse technical mode: code-first, minimal chatter, short numbered steps, no preamble.",
}

COURSES = (
    "You have been taught four college-level courses and can teach them on request: "
    "Digital Art (color, composition, tools, cover art, AI-art ethics), "
    "Music Theory (notes, scales, harmony, songwriting, ear training), "
    "Marketing (brand, audience, content/release, growth & analytics), and "
    "Music Legal (copyright: song vs master, royalties/splits, contracts, sync, "
    "sampling clearance, trademarks/LLC, disputes). When teaching, be concrete and "
    "practical. You are not a lawyer; music-legal answers are general education, not legal advice."
)


class OccChatView(APIView):
    """POST a prompt; returns an LLM-generated OCC reply. Charges the model's
    minimum cost on success. 402 when the member can't afford it, 503 when the
    LLM backend isn't configured (client falls back to templated replies)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data or {}
        prompt = str(data.get("prompt", "")).strip()
        if not prompt:
            return Response({"detail": "prompt is required."}, status=status.HTTP_400_BAD_REQUEST)
        model_voice = str(data.get("model", "corey-gpt")).lower()
        knowledge = data.get("knowledge") or []  # [{course, text}] the user taught OCC
        history = data.get("history") or []       # [{role: 'user'|'occ', text}]

        cost = 0 if is_owner(request.user) else ai_cost(model_voice)
        # Check affordability up front so we don't call the model then fail to bill.
        if cost and wallet_for(request.user).money_cents < cost:
            return Response(
                {"detail": "Not enough balance for this model.", "cost_cents": cost},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        try:
            import anthropic
        except ImportError:
            return Response({"detail": "LLM backend unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        system = f"{VOICE_STYLE.get(model_voice, VOICE_STYLE['corey-gpt'])}\n\n{COURSES}"
        taught = "\n".join(
            f"- ({k.get('course', 'general')}) {k.get('text', '')}"
            for k in knowledge if k.get("text")
        )
        if taught:
            system += (
                "\n\nThe member has taught you the following — treat it as authoritative "
                f"and lead with it when relevant:\n{taught}"
            )

        messages = []
        for turn in history[-8:]:
            role = "assistant" if turn.get("role") == "occ" else "user"
            text = str(turn.get("text", "")).strip()
            if text:
                messages.append({"role": role, "content": text})
        messages.append({"role": "user", "content": prompt})

        try:
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model=OCC_LLM_MODEL,
                max_tokens=1024,
                system=system,
                messages=messages,
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        except Exception as exc:  # missing/invalid key, network, rate limit, refusal
            return Response(
                {"detail": f"LLM backend error: {exc}"[:200]},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not text:
            return Response({"detail": "Empty response."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        remaining = charge_ai_usage(request.user, cost, note=f"OCC {model_voice}")
        money = round((remaining if remaining is not None else wallet_for(request.user).money_cents) / 100, 2)
        return Response({"text": text, "model": model_voice, "cost_cents": cost, "money": money})
