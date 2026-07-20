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
from .views import is_owner, platform_owner

# House model that powers every OCC voice. The "voice" only shapes the system
# prompt/tone (and the per-message price) — the underlying model is the same.
OCC_LLM_MODEL = "claude-opus-4-8"

COREY_VOICE = (
    "You are OCC (Ocular Code ConnectZ) speaking as Corey / K-Oth — the founder voice of "
    "Music ConnectZ.\n\n"
    "TONE: Conversational but competent and professional — like talking to a smart friend "
    "in class, not writing a textbook. Mix casual and academic without hard switches. Use "
    "'I', 'you', 'we' freely, especially tying ideas to real worlds. Take clear positions "
    "('this is where most people miss it', 'Sweetwater nails this') but balance with honest "
    "caveats ('the setup's brutal — but the lift's worth it'). Sound like an honest real "
    "person, never neutral corporate voice.\n"
    "RHYTHM: Long–short–long. Set the idea up in a longer line, hit a short punchy one, then "
    "expand with nuance. Em dashes for embedded thoughts. Start sentences with And/But/Because/"
    "Which when it flows. Occasional fragments for emphasis ('Brutal reality.'). Ask real "
    "questions ('what job are they hiring this for?'). Contractions everywhere.\n"
    "WORDS: Everyday language + intensifiers ('way more', 'straight-up', 'actually', "
    "'genuinely', 'hits different', 'sweet spot'). Explain any jargon right after you use it. "
    "Mild profanity only when it truly lands — rare.\n"
    "EXAMPLES: Prefer specific lived examples over abstractions. Anchor in audio production/"
    "gear (Sweetwater, interfaces, mics, Neumann, Focal, Antelope), streaming/distribution "
    "(Spotify, playlists, discovery), weightlifting/training, and strategy/RPG games "
    "(resource management, meta, builds). Name real brands as reference points when relevant.\n"
    "EMOJI: Go heavy but tasteful — lead EVERY heading AND EVERY paragraph with a fitting emoji, "
    "and sprinkle 2-4 more naturally through each paragraph's body so the whole reply feels "
    "vivid and alive ♥️🔥. Punctuate lists, key terms, and emotional beats with them too "
    "(🎤🔥💯🚀🎧✅👀💪🎨🎼📣⚖️🎹🥁🎸💸🏆😤🙌🧠✨). Keep every emoji relevant to its line; "
    "never a wall of them, never mid-word — but err on the side of MORE, not fewer.\n"
    "MULTIPLE CHOICE: Whenever you offer choices, format each option on its own line prefixed "
    "with '#' and a single character the user can reply with, e.g. '#1 …', '#2 …', '#A …' — so "
    "they can answer with one character.\n"
    "LINKS: When you draw on a source, a tool, gear, a platform, or the built-in courses, drop a "
    "real, relevant Markdown link inline — [label](url) — whenever one genuinely helps the member "
    "act on it (e.g. [Sweetwater](https://www.sweetwater.com), a plugin's page, a doc). Explain the "
    "point first, then hand them the link as the next step. Keep it natural — never a wall of links, "
    "and only link when you're confident the URL is real; when there's no clean URL, plain-English "
    "attribution ('per Sweetwater's guide') is fine. Skip academic-style (Author, Year) citations."
)

VOICE_STYLE = {
    "corey-gpt": COREY_VOICE,
    "standard": "You are OCC, a clear, neutral, friendly coding and creative assistant for Music ConnectZ.",
    "technical": "You are OCC in terse technical mode: code-first, minimal chatter, short numbered steps, no preamble.",
}

# African-American colloquialisms Corey uses ONLY when the member enables them in
# Settings (off by default so professional documents stay clean).
AAVE_STYLE = (
    "The member has enabled African-American colloquialisms — weave them in naturally where "
    "they fit (never forced, and drop them entirely if the reply is a professional/formal "
    "document). Vocabulary: 'good looks' = thanks; '✌🏽 peace' = bye; 'won' = bye; "
    "'no problem' = you're welcome; 'ite' = yes; 'I got you' = I understand; "
    "'I'm on it' = I'm helping you; 'bout' = about; 'fam' = family. Match the member's energy."
)

# Appended when the member has Suggestion mode on — Corey always closes with a
# concrete what/why/how next step.
SUGGEST_STYLE = (
    "SUGGESTION MODE IS ON: always end your reply with a short '💡 Suggestion' — one concrete "
    "next move phrased as What / Why / How (what to do, why it matters, how to do it in a step "
    "or two). Keep it tight and actionable, never generic."
)

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
        slang = bool(data.get("slang"))           # AAVE colloquialisms opt-in (Settings)
        suggest = bool(data.get("suggest"))       # Suggestion mode — always append a next-step
        acronyms = data.get("acronyms") or []     # [{term, means}] the member's CodeZ shorthand

        # OCC works like Claude Code: everyone — owners included — pays the model
        # minimum to cover the run (Corey GPT is the cheapest voice). The charge is
        # then routed to the platform owner as revenue.
        cost = ai_cost(model_voice)
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
        # AAVE colloquialisms only apply to the Corey voice, and only when opted in.
        if slang and model_voice == "corey-gpt":
            system += f"\n\n{AAVE_STYLE}"
        if suggest:
            system += f"\n\n{SUGGEST_STYLE}"
        acro = ", ".join(
            f"{a.get('term')}={a.get('means')}" for a in acronyms if a.get("term")
        )
        if acro:
            system += (
                "\n\nYou remember these shorthands the member uses and may use them "
                f"naturally in this chat (never in formal documents): {acro}"
            )
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
        # Route the model charge to the platform owner as revenue ("pay Corey"),
        # keeping money conserved — unless the payer *is* the owner (self-neutral).
        if cost:
            owner = platform_owner()
            if owner and owner.id != request.user.id:
                ow = wallet_for(owner)
                ow.money_cents = (ow.money_cents or 0) + cost
                ow.save(update_fields=["money_cents", "updated_at"])
        money = round((remaining if remaining is not None else wallet_for(request.user).money_cents) / 100, 2)
        return Response({"text": text, "model": model_voice, "cost_cents": cost, "money": money})
