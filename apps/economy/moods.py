"""How a thing made you FEEL, apart from whether you rated it well.

Karma is the up/down vote and it decides what a comment earns. A mood is the
other half of what people mean by a reaction: ❤️ love, 😂 funny, 😲 shocked,
🤔 curious, 😢 sad, 😡 hate. "Like" is not on this list on purpose — it is the
karma up-vote, and two likes would be two answers to "how many people liked
this", which this codebase keeps writing notes about.

The substance rule, said where it can be broken: **a mood is a reaction and never
a measurement.** It moves no rating, median, royalty factor, skill level, price or
search rank, and pays nothing — to the reactor or the maker — so there is nothing
to farm and nothing that ever teaches a member to chase one. `test_moods` fails
if another module reads a mood.

The list is the server's, in one place, and is served with every item
(`social/` → `moods`). The client never retypes it, so adding a mood is a line
here and every screen has it.
"""
MOODS = (
    ("love", "❤️", "Love"),
    ("laugh", "😂", "Funny"),
    ("shocked", "😲", "Shocked"),
    ("curious", "🤔", "Curious"),
    ("sad", "😢", "Sad"),
    ("hate", "😡", "Hate"),
)
KEYS = tuple(k for k, _e, _l in MOODS)


def catalog():
    return [{"key": k, "emoji": e, "label": l} for k, e, l in MOODS]


def clean(value):
    """A mood key, or "" (clear). Anything unknown is refused by the caller, never guessed."""
    v = str(value or "").strip().lower()
    return v if v in KEYS or v == "" else None


def summary(item_id, user):
    """({mood: count}, my mood) for one item — two queries, however many reactions."""
    from django.db.models import Count
    from .models import MoodReaction
    counts = {m: 0 for m in KEYS}
    for row in MoodReaction.objects.filter(item_id=item_id).values("mood").annotate(n=Count("id")):
        if row["mood"] in counts:
            counts[row["mood"]] = row["n"]
    mine = MoodReaction.objects.filter(item_id=item_id, user=user).values_list("mood", flat=True).first() or ""
    return counts, mine
