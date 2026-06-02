"""Seed the 7 DawZ proposals with feature-first descriptions. Idempotent."""
from .models import DawProposal

DAWS = [
    ("fruity-mobius", "Fruity Möbius", "🍑", "#ec4899", "FL Studio",
     "Loop-first, pattern-based production with an infinite collab twist.",
     ["Step sequencer + pattern blocks", "Piano roll with strum/arp tools",
      "Möbius mode: open collab slots where partners cycle the loop endlessly",
      "Per-channel FX racks", "Fast pattern-to-song arranger"]),
    ("arsenal", "Arsenal", "⚔️", "#22d3ee", "Pro Tools",
     "Industry-grade tracking and mixing for serious sessions.",
     ["High track-count multitrack recording", "Comping + take folders",
      "Advanced bus/aux routing", "Built-in mastering chain", "Session templates"]),
    ("witchcraft", "Witchcraft", "🔮", "#a855f7", "Ableton Live / Mixcraft",
     "Clip-launch sound design for moodier, scene-based creation.",
     ["Clip + scene launcher", "Sound-design FX racks", "Sigil-style preset packs",
      "Warped loop arranging", "Live performance scenes"]),
    ("trump-toupee", "Trump Toupee", "🎤", "#f97316", "Bitwig",
     "Modular voice-FX engine for layered vocal processing.",
     ["Modular FX grid", "Pitch + formant stacks", "Layered voice processing",
      "Hardware-style modulators", "One-shot bounce export"]),
    ("azrael", "Azrael", "💀", "#84cc16", "Reaper",
     "Lean, deeply customizable, low-overhead multitrack.",
     ["Fully customizable UI/layout", "Scripting + macro actions",
      "Low-latency multitrack", "Custom FX chains", "Flexible stem export"]),
    ("intuition", "Intuition", "🤔", "#eab308", "Logic Pro",
     "Melody-first composition with rich MIDI tooling.",
     ["MIDI + score editor", "Software instrument library",
      "Chord + arrangement helpers", "Flex-time + smart tempo", "Track stacks"]),
    ("formula-won", "FormulaWon", "🚦", "#10b981", "GarageBand",
     "Friendly on-ramp — make a track in minutes.",
     ["Simplified arrange view", "Smart instruments", "Built-in learn-to-play lessons",
      "Quick loops library", "One-tap share to your postZ"]),
]


def seed_dawz():
    made = 0
    for i, (key, name, emoji, color, comp, tagline, feats) in enumerate(DAWS):
        _, created = DawProposal.objects.get_or_create(
            key=key,
            defaults={"name": name, "emoji": emoji, "color": color,
                      "comparable_to": comp, "tagline": tagline,
                      "description": tagline, "features": feats, "order": i})
        made += int(created)
    return made
