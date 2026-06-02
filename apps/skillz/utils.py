"""XP -> level math, shared by progress + serializers."""

def level_for_xp(xp: int):
    """Returns (level, xp_into_level, xp_to_next). Level n costs n*100 cumulative-ish."""
    xp = max(0, int(xp or 0))
    level, need, rem = 1, 100, xp
    while rem >= need and level < 99:
        rem -= need
        level += 1
        need = level * 100
    return level, rem, need
