"""Game genre / subgenre catalog for GameZ. Users pick from this list; AI can
auto-suggest the best match from a title/description."""

GENRES = {
    "Action":      ["Platformer", "Shooter", "Fighting", "Beat 'em up", "Hack & Slash", "Stealth"],
    "Adventure":   ["Point & Click", "Visual Novel", "Interactive Fiction", "Survival", "Open World"],
    "RPG":         ["Action RPG", "JRPG", "Roguelike", "Tactical RPG", "Dungeon Crawler", "MMORPG"],
    "Strategy":    ["Real-Time Strategy", "Turn-Based", "Tower Defense", "4X", "Auto-Battler"],
    "Simulation":  ["Life Sim", "Vehicle Sim", "Management", "City Builder", "Farming"],
    "Puzzle":      ["Match-3", "Physics", "Logic", "Hidden Object", "Word"],
    "Rhythm":      ["Music/Beat", "Dance", "Note Highway", "Karaoke"],      # native fit for Music ConnectZ
    "Sports":      ["Arcade", "Simulation", "Management"],
    "Racing":      ["Arcade", "Simulation", "Kart"],
    "Casual":      ["Hypercasual", "Idle/Clicker", "Endless Runner", "Party"],
    "Sandbox":     ["Creative", "Crafting", "Voxel"],
    "Horror":      ["Survival Horror", "Psychological", "Jump Scare"],
    "Card/Board":  ["Deckbuilder", "Collectible", "Board Adaptation"],
    "Shooter":     ["FPS", "Top-Down", "Bullet Hell", "Battle Royale"],
}


def flat_subgenres():
    out = []
    for g, subs in GENRES.items():
        for s in subs:
            out.append((g, s))
    return out


def heuristic_suggest(text):
    """No-AI fallback: keyword match to a genre/subgenre."""
    t = (text or "").lower()
    table = [
        (("beat", "rhythm", "music", "note", "dance", "karaoke"), ("Rhythm", "Music/Beat")),
        (("shoot", "fps", "gun", "bullet"), ("Shooter", "FPS")),
        (("race", "racing", "kart", "drift"), ("Racing", "Arcade")),
        (("puzzle", "match", "tetris", "logic"), ("Puzzle", "Logic")),
        (("rpg", "quest", "dungeon", "level up", "loot"), ("RPG", "Action RPG")),
        (("platform", "jump", "mario", "runner"), ("Action", "Platformer")),
        (("tower", "defense", "strategy", "base"), ("Strategy", "Tower Defense")),
        (("horror", "scary", "survive the night"), ("Horror", "Survival Horror")),
        (("card", "deck", "collect"), ("Card/Board", "Deckbuilder")),
        (("idle", "clicker", "tap", "casual"), ("Casual", "Idle/Clicker")),
        (("sim", "build", "manage", "farm", "city"), ("Simulation", "Management")),
    ]
    for keys, gs in table:
        if any(k in t for k in keys):
            return gs
    return ("Casual", "Hypercasual")
