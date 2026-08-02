"""Corey's tutorial voice.

The tour never *depends* on the LLM. Every option ships a written explanation
(``tour.STEPS[...]["options"][n]["explain"]``), so a member with no network
weather, on a deploy with no API key, still gets a real answer in Corey's voice —
just a fixed one. When the key is there we let Corey actually respond to what
they typed, which is the difference between a tooltip and a conversation.

Unlike OCC chat, OmviardZ does not charge. Onboarding you is not a service you
should have to fund, and a paywalled tutorial is how you lose someone in the
first five minutes. Replies are capped short instead — this renders in a bottom
sheet on a phone, not a desktop chat pane.
"""
import logging

from .tour import TRACK_LABELS

log = logging.getLogger("apps.omviardz")

# Short on purpose: the reply lands in a ~46vh bottom sheet.
MAX_TOKENS = 700

SOURCE_LLM = "corey-gpt"
SOURCE_BUILTIN = "builtin"

TUTOR_STYLE = (
    "YOU ARE RUNNING OMVIARDZ — the guided tour of Music ConnectZ. The member is on a PHONE, "
    "mid-tour, looking at one highlighted control with your reply in a small bottom sheet.\n"
    "HARD RULES FOR THIS MODE:\n"
    "- Answer about the ONE highlighted option below. Do not tour the rest of the app.\n"
    "- Keep it under 120 words. Two short paragraphs max. No headings, no bullet lists — "
    "this is a phone sheet, not a doc.\n"
    "- Do NOT offer your own numbered choices; OmviardZ renders the options as buttons. "
    "End by pointing at what to tap, or with one short question.\n"
    "- Never invent limits, prices, or fees. If a number isn't in the facts below, describe it "
    "in words ('the highest cut', 'a short window') instead of guessing.\n"
    "- If the member typed something instead of picking, answer THAT first, then bring them "
    "back to the highlighted control."
)


def _facts_block(facts):
    """Flatten the live tier numbers into a line Corey can quote safely."""
    if not facts:
        return ""
    lines = []
    for tier, f in (facts.get("tiers") or {}).items():
        chars = "unlimited" if f.get("char_limit_unlimited") else f.get("char_limit")
        tax = f.get("dev_tax")
        lines.append(
            f"{tier}: chars={chars}, upload={f.get('upload_mb')}MB, "
            f"storage={f.get('storage_mb')}MB, edit_window={f.get('edit_window_seconds')}s, "
            f"fee={tax}, weekly_cashout={f.get('cashout_weekly')}"
        )
    cash = facts.get("cashout") or {}
    lines.append(
        f"cashout rates: instant={cash.get('instant')}, monthly={cash.get('monthly')}, "
        f"quarterly={cash.get('quarterly')}"
    )
    costs = facts.get("ai_cost_cents") or {}
    if costs:
        lines.append("AI cents per message: " + ", ".join(f"{k}={v}" for k, v in costs.items()))
    if facts.get("founding_limit"):
        lines.append(f"founding StatZ seats: first {facts['founding_limit']} at half price")
    return "TRUE PLATFORM NUMBERS (quote these, never other ones):\n" + "\n".join(lines)


def build_system(step, option, track, facts, slang=False):
    """Corey's own voice + tutorial mode + the exact thing being highlighted."""
    try:
        from apps.economy.occ import AAVE_STYLE, COREY_VOICE
    except Exception:  # pragma: no cover - economy app absent
        COREY_VOICE = "You are Corey / K-Oth, the founder voice of Music ConnectZ."
        AAVE_STYLE = ""

    parts = [COREY_VOICE, TUTOR_STYLE]

    context = [
        f"TOUR TRACK: {TRACK_LABELS.get(track, track)}",
        f"CURRENT STEP: {step.get('title')} (screen: {step.get('screen')})",
        f"WHAT THE STEP SAYS: {step.get('blurb')}",
    ]
    if option:
        context.append(f"HIGHLIGHTED OPTION: {option.get('label')}")
        context.append(
            "THE WRITTEN ANSWER FOR THIS OPTION (stay consistent with it, don't contradict "
            f"it, but say it in your own words): {option.get('explain', '')}"
        )
        mark = option.get("highlight") or step.get("highlight") or {}
        if mark.get("label"):
            context.append(f"THE CONTROL ON SCREEN IS LABELLED: {mark['label']}")
    else:
        context.append(
            "The member typed something instead of picking an option — answer them, then "
            "point back at this step's options."
        )
    parts.append("\n".join(context))

    fb = _facts_block(facts)
    if fb:
        parts.append(fb)
    if slang and AAVE_STYLE:
        parts.append(AAVE_STYLE)
    return "\n\n".join(parts)


def builtin_reply(step, option, text=""):
    """The no-LLM answer: the option's written explanation, plus a nudge.

    This is a first-class path, not a stub — it's what most members will read
    on a deploy with no ANTHROPIC_API_KEY, so it has to stand on its own.
    """
    if option:
        body = option.get("explain") or option.get("label", "")
        mark = option.get("highlight") or step.get("highlight") or {}
        if mark.get("label"):
            body = f"{body}\n\n👉 That's the **{mark['label']}** control I've lit up — tap it when you're ready."
        return body
    # They typed instead of tapping. We can't answer freely without the model,
    # so be honest and hand them the choices rather than faking comprehension.
    opts = "\n".join(f"#{o['key']} {o['label']}" for o in step.get("options", []))
    asked = f'👀 "{text.strip()[:120]}" — ' if text.strip() else "👀 "
    return (
        f"{asked}I can't riff on that one right now, so let me not waste your time guessing. 💯\n\n"
        f"Here's what's on this screen — pick one and I'll break it down:\n{opts}"
    )


def explain(step, option, text="", track=None, facts=None, slang=False, suggest=False):
    """Corey's answer for the highlighted option. Returns ``(text, source)``.

    Falls back to the written explanation on any failure — missing package,
    missing key, rate limit, network. The tour must never dead-end on a step
    because an upstream API had a bad minute.
    """
    prompt = (text or "").strip()
    if option and not prompt:
        prompt = f"Explain this option: {option.get('label')}"
    elif option and prompt:
        prompt = f"I picked '{option.get('label')}' and I'm asking: {prompt}"

    try:
        import anthropic

        from apps.economy.occ import MODEL_BY_VOICE, OCC_LLM_MODEL, _create_with_fallback

        system = build_system(step, option, track, facts, slang=slang)
        if suggest:
            # Was "what to do and why" — it silently dropped the How, so the
            # tour gave two-thirds of a suggestion while OCC gave three.
            from apps.economy.suggest import SUGGEST_STYLE_SHORT
            system += f"\n\n{SUGGEST_STYLE_SHORT}"
        client = anthropic.Anthropic()
        resp = _create_with_fallback(
            client,
            MODEL_BY_VOICE.get("corey-gpt", OCC_LLM_MODEL),
            OCC_LLM_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        out = "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        ).strip()
        if out:
            return out, SOURCE_LLM
        log.info("omviardz: empty LLM reply on step=%s, using written answer", step.get("screen"))
    except Exception as exc:
        # Expected whenever the key isn't set — info, not error, so it doesn't
        # look like a fault in the logs on a deploy that never configured one.
        log.info("omviardz: falling back to written answer (%s)", str(exc)[:160])

    return builtin_reply(step, option, text), SOURCE_BUILTIN
