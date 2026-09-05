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

from .catalog import (
    AI_MODELS,
    AI_MODEL_ORDER,
    OCC_MAX_ACRONYM_CHARS,
    OCC_MAX_ACRONYMS,
    OCC_MAX_HISTORY_CHARS,
    OCC_IMAGE_TYPES,
    OCC_MAX_IMAGE_B64,
    OCC_MAX_HISTORY_TURNS,
    OCC_MAX_KNOWLEDGE_CHARS,
    OCC_MAX_KNOWLEDGE_ITEMS,
    OCC_MAX_PROMPT_CHARS,
    OCC_MAX_TOTAL_CHARS,
    ai_model_for,
    occ_limits,
)
from .models import (
    can_afford_ai,
    charge_ai_usage,
    DAILY_PROMPT_MAX_CENTS,
    daily_prompt_covers,
    daily_prompt_state,
    membership_for,
    profile_for,
    wallet_for,
)
from .views import credit_owner, is_owner

# The voice shapes the system prompt and nothing else. Which ENGINE runs it is
# the member's own choice, gated by tier and priced by what it actually costs —
# see catalog.AI_MODELS. Voice used to carry the price too, which is how the
# "cheapest" voice ended up on the most expensive model in the catalogue.


def _create_with_fallback(client, primary, fallback, **kwargs):
    """Generate with `primary`, falling back to `fallback` if that model isn't
    available on this account or region.

    Callers pass a fallback at or BELOW the primary's price. The member is
    billed for the engine they chose either way, so substituting something
    dearer would have the platform quietly paying the difference for a swap
    nobody asked for.

    Only availability errors trigger the retry; auth, rate-limit and billing
    errors propagate unchanged — those are not something a cheaper model fixes.
    """
    try:
        return client.messages.create(model=primary, **kwargs)
    except Exception as exc:
        msg = str(exc).lower()
        unavailable = "404" in msg or "not_found" in msg or (
            "model" in msg and any(w in msg for w in ("not found", "does not exist", "unavailable", "not available", "invalid"))
        )
        if primary != fallback and unavailable:
            return client.messages.create(model=fallback, **kwargs)
        raise

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

# The framing around the member's own additions. Named so their length can be
# counted against the budget — leaving them out of the arithmetic is how the
# first version of this cap came in 100 characters over.
ACRO_INTRO = ("\n\nYou remember these shorthands the member uses and may use them "
              "naturally in this chat (never in formal documents): ")
TAUGHT_INTRO = ("\n\nThe member has taught you the following — treat it as authoritative "
                "and lead with it when relevant:\n")

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
        # Every field below is capped. The per-message price assumes a turn of
        # about 10,000 input tokens and nothing used to hold it to that — see
        # catalog.OCC_MAX_TOTAL_CHARS for why that was expensive.
        prompt = str(data.get("prompt", "")).strip()
        if len(prompt) > OCC_MAX_PROMPT_CHARS:
            return Response(
                {"detail": f"That message is {len(prompt):,} characters — keep it under "
                           f"{OCC_MAX_PROMPT_CHARS:,}. Send the long part as a file or "
                           "split it across turns.",
                 "limits": occ_limits()},
                status=status.HTTP_400_BAD_REQUEST)
        if not prompt:
            return Response({"detail": "prompt is required."}, status=status.HTTP_400_BAD_REQUEST)
        model_voice = str(data.get("model", "corey-gpt")).lower()
        knowledge = data.get("knowledge") or []  # [{course, text}] the user taught OCC
        history = data.get("history") or []       # [{role: 'user'|'occ', text}]
        slang = bool(data.get("slang"))           # AAVE colloquialisms opt-in (Settings)
        suggest = bool(data.get("suggest"))       # Suggestion mode — always append a next-step
        acronyms = data.get("acronyms") or []     # [{term, means}] the member's CodeZ shorthand

        # OCC works like Claude Code: everyone — owners included — pays the model
        # minimum to cover the run. The charge is then routed to the platform
        # owner as revenue.
        #
        # The ENGINE is what costs, not the voice. Corey / standard / technical
        # are system prompts; a tone has no per-token price, and charging for one
        # is how the cheapest voice ended up running the priciest model. The
        # member's engine choice is gated by tier and resolved here so a lapsed
        # subscription falls back rather than 402s.
        tier = membership_for(request.user).tier
        model_key, model_spec = ai_model_for(profile_for(request.user).ai_model, tier)
        cost = model_spec["cost_cents"]

        # The day's free prompts cover a run before any balance is touched —
        # OCC is a genuine prompt run, which is exactly what that allowance is
        # for. It was never wired in here, so a member whose whole AI budget was
        # the free allowance couldn't open the app's main AI screen at all; the
        # vocal coach and the Gemini surfaces have honoured it all along.
        # Read before spending, because charge_ai_usage consumes it.
        _, _, daily_left = daily_prompt_state(request.user)
        # Whether prompts REMAIN is only half of it — the allowance also has a
        # ceiling, and this member may have picked an engine above it.
        covered_free = daily_prompt_covers(cost) and daily_left > 0

        # Check affordability up front so we don't call the model then fail to bill.
        if cost and not covered_free and not can_afford_ai(request.user, cost):
            # Two different walls, and telling somebody the wrong one sends them
            # to wait until tomorrow for an allowance that was never going to
            # cover this engine. Say which it is.
            why = ("today's free prompts are spent"
                   if daily_prompt_covers(cost)
                   else f"a free daily prompt covers up to {DAILY_PROMPT_MAX_CENTS} 🏷️ "
                        f"— switch engine to run it free")
            return Response(
                {"detail": f"{model_spec['emoji']} {model_spec['name']} costs "
                           f"{cost} 🏷️ a message and {why}.",
                 "cost_cents": cost, "engine": model_key,
                 "daily_prompt_max_cents": DAILY_PROMPT_MAX_CENTS,
                 "open_in": "modelz"},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        try:
            import anthropic
        except ImportError:
            return Response({"detail": "LLM backend unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # The system prompt is assembled from parts rather than concatenated as
        # it goes, because the TOTAL has to fit a budget and you cannot trim a
        # string you have already joined. Fixed parts first (the voice and the
        # courses are what OCC *is*), then the member's own additions, which are
        # what gets shortened when the budget bites.
        fixed = f"{VOICE_STYLE.get(model_voice, VOICE_STYLE['corey-gpt'])}\n\n{COURSES}"
        # AAVE colloquialisms only apply to the Corey voice, and only when opted in.
        if slang and model_voice == "corey-gpt":
            fixed += f"\n\n{AAVE_STYLE}"
        if suggest:
            fixed += f"\n\n{SUGGEST_STYLE}"

        acro = ", ".join(
            f"{str(a.get('term'))[:OCC_MAX_ACRONYM_CHARS]}="
            f"{str(a.get('means', ''))[:OCC_MAX_ACRONYM_CHARS]}"
            for a in acronyms[:OCC_MAX_ACRONYMS] if a.get("term")
        )
        taught = "\n".join(
            f"- ({str(k.get('course', 'general'))[:60]}) "
            f"{str(k.get('text', ''))[:OCC_MAX_KNOWLEDGE_CHARS]}"
            for k in knowledge[:OCC_MAX_KNOWLEDGE_ITEMS] if k.get("text")
        )

        messages = []
        for turn in history[-OCC_MAX_HISTORY_TURNS:]:
            role = "assistant" if turn.get("role") == "occ" else "user"
            text = str(turn.get("text", "")).strip()[:OCC_MAX_HISTORY_CHARS]
            if text:
                messages.append({"role": role, "content": text})

        # The per-field caps stop any ONE runaway value; this stops them adding
        # up. Twenty taught items at their own cap is 40,000 characters on its
        # own, which is the whole budget before the voice prompt is even counted
        # — so a cap per field was never going to be enough by itself.
        #
        # Trimmed in order of what costs the member least: the oldest turns of a
        # conversation they can still see on screen, then the taught knowledge
        # they can re-teach, then the shorthand. The message they just typed is
        # never touched — it is the thing they asked for.
        trimmed = 0
        room = (OCC_MAX_TOTAL_CHARS - len(fixed) - len(prompt)
                - len(ACRO_INTRO) - len(TAUGHT_INTRO))
        while messages and sum(len(m["content"]) for m in messages) + len(acro) + len(taught) > room:
            messages.pop(0)
            trimmed += 1
        spare = room - sum(len(m["content"]) for m in messages)
        if len(acro) + len(taught) > spare:
            taught = taught[:max(0, spare - len(acro))]
        if len(acro) > spare:
            acro = acro[:max(0, spare)]
            taught = ""

        system = fixed
        if acro:
            system += ACRO_INTRO + acro
        if taught:
            system += TAUGHT_INTRO + taught

        # Optional image (a data URL) for vision tasks — e.g. "detect gym gear from a photo".
        image = data.get("image")
        if isinstance(image, str) and image.startswith("data:") and "," in image:
            header, b64 = image.split(",", 1)
            media_type = header.split(";")[0].split(":")[-1] or "image/jpeg"
            # Both checks are the same lesson twice: a client-supplied size with
            # no ceiling is a bill, and a client-supplied media type passed
            # straight to an API is a rejection you can't read. Refuse here,
            # by name, before the model runs and before anything is charged.
            if len(b64) > OCC_MAX_IMAGE_B64:
                return Response(
                    {"detail": "That image is too big — send one under about "
                               f"{OCC_MAX_IMAGE_B64 // 1_000_000}MB.",
                     "limits": occ_limits()},
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            if media_type not in OCC_IMAGE_TYPES:
                return Response(
                    {"detail": f"OCC can't read {media_type} — send a JPEG, PNG, GIF or WebP.",
                     "limits": occ_limits()},
                    status=status.HTTP_400_BAD_REQUEST)
            messages.append({"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": prompt},
            ]})
        else:
            image = None
            messages.append({"role": "user", "content": prompt})

        try:
            client = anthropic.Anthropic()
            # The member's chosen engine, falling back DOWN the ladder if it
            # isn't available on this account. Down rather than to a fixed
            # flagship: the member is billed for what they picked either way, so
            # a fallback that costs more than their choice is the platform
            # paying the difference for a substitution nobody asked for.
            resp = _create_with_fallback(
                client, model_spec["id"], AI_MODELS[AI_MODEL_ORDER[0]]["id"],
                max_tokens=3072,       # fuller Corey answers (was 1024)
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

        # The note names the ENGINE as well as the voice, because the engine is
        # what the money went on. A LogZ row reading "OCC corey-gpt · 15c" with
        # no way to tell which model ran is a balance that can't be explained.
        remaining = charge_ai_usage(
            request.user, cost, note=f"OCC {model_voice} · {model_spec['name']}",
            count_daily=True)
        # Route the model charge to the platform owner as revenue ("pay Corey"),
        # keeping money conserved — unless the payer *is* the owner (self-neutral),
        # or a free daily prompt covered it. Nothing left the member's wallet in
        # that case, so nothing may arrive in the owner's: paying the owner out
        # of an allowance is the platform minting money from itself.
        if cost and not covered_free:
            # Same note the member's own row carries, so both ends of the
            # movement name the engine the money went on.
            credit_owner(request.user, cost,
                         f"OCC {model_voice} · {model_spec['name']}")
        money = round((remaining if remaining is not None else wallet_for(request.user).money_cents) / 100, 2)
        allowance, _, daily_now = daily_prompt_state(request.user)
        out = {"text": text, "model": model_voice, "cost_cents": cost, "money": money,
               # Which engine ran and what it cost, so the reply can say it
               # rather than the member inferring it from a balance.
               "engine": model_key, "engine_name": model_spec["name"],
               "engine_emoji": model_spec["emoji"],
               # A run that cost nothing has to say so, or the member assumes
               # they were charged and stops asking.
               "free_prompt": covered_free,
               # And what an allowance is worth, so a member on a dear engine
               # can see WHY it wasn't free rather than guessing.
               "daily_prompt_max_cents": DAILY_PROMPT_MAX_CENTS,
               # Say when history was dropped to stay inside the size budget.
               # Silently forgetting the start of a conversation is worse than
               # forgetting it out loud.
               **({"history_trimmed": trimmed} if trimmed else {}),
               "limits": occ_limits(),
               "daily_prompts_left": daily_now, "daily_prompts": allowance}

        # A reply you can't take anywhere is a dead end with a scrollbar. Asked
        # to, OCC keeps the exchange as WorkZ — in the PostZ format — so it can
        # be shared, rated, commented on, or carried into another app.
        if data.get("save_work"):
            from .models import OccOutput
            from .occ_workz import output_dict
            work = OccOutput.objects.create(
                user=request.user,
                tab=str(data.get("tab", "occ") or "occ")[:32],
                input_text=prompt,
                input_items=([{"url": "", "type": "image", "title": "prompt image", "lyrics": ""}]
                             if image else []),
                title=(prompt.strip().splitlines() or ["OCC reply"])[0][:160],
                description=text[:20000],
                media_type="document",
            )
            out["work"] = output_dict(work, request)
        else:
            # Even when it isn't kept, say where it COULD go rather than
            # leaving the member to guess that saving is possible at all.
            out["can_save_work"] = {"app": "occ", "target": "occ:workz",
                                    "label": "Keep this as WorkZ"}
        return Response(out)
