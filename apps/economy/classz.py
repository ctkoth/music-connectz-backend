"""ThuroZ, SeXi and Thorough: a rating of 6.9 or more, as ONE word.

Corey: SeXi is Thorough on attractiveness, so all three read the same bar — 6.9 OR MORE (it was strictly above,
which made a member sitting exactly on 6.9 Thorough in BodieZ and not ThuroZ or SeXi).

Corey: classify anything above 6.9 as Thuro, and make it a filter everywhere a member
decides who they see or work with. The five range gates already do that with numbers
(`gates.py`); a class is the same gate with the number chosen once, here, so a host taps
"ThuroZ only" instead of typing 7 into a box and wondering what everybody else typed.

Two classes, one rule:

* **ThuroZ** — the member's OVERALL profile rating (`OverallRating`, the number the
  rating range gate already reads) has a median above 6.9.
* **SeXi** — the same bar on the community attractiveness median.

THE SUBSTANCE RULE, APPLIED. *Could a member get a good one without getting good?* With a
bare median, yes: one friend's 10 is a median of 10. So a class needs `MIN_RATINGS` (3)
voices behind the number, and the median, so one rater cannot move it. For ThuroZ the AI
coach is three of those voices once it has scored three of the member's takes (Corey's
call; see `coach_voices` for what that traded away), so it can stand in for members. Three, not the
royalty formula's five, because this pays nothing — the cost of being wrong is somebody
seen in a list, not money — and a bar the platform is too small to clear is an empty room.
What it traded away: three accounts that agree can still make one. The count is said
beside the class wherever it is explained, so nobody reads it as more than it is.

IT PAYS NOTHING AND MOVES NOTHING. No ⚡, 🍥, royalty, price or rank reads a class. It
decides who a member SEES or lets in, and only when that member asks. A class that paid
would be worth faking.

SeXi inherits every line the attractiveness number already has: a member who hides
their number is not SeXi (`attractiveness_shown`), and a minor never is, whoever asks.

EXCLUSIVE, like every gate: no ratings, or too few, is "not in the class", and the screen
says how many members that leaves out rather than letting an empty list read as "nobody
is good". Nothing here is stored: the class is read from the ratings at request time, so
it falls the moment the median does.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

ABOVE = 6.9
MIN_RATINGS = 3
# What the AI coach's voice is worth toward a class: three, so it can stand in for member
# ratings or add to them (Corey's call). The same number the royalty formula's skill blend
# uses, read from there so the two cannot drift.
from .royaltyfactor import COACH_VOTES  # noqa: E402

CLASSES = {
    "thuro": {
        "label": "ThuroZ", "emoji": "\u203c\ufe0f", "icon": "thuroz.jpg",
        "metric": "overall rating",
        "rule": f"overall rating of {ABOVE:g} or more from at least {MIN_RATINGS} voices (members, or the AI coach as {COACH_VOTES})",
        "what": "Members the room rates 6.9 or more overall. One word instead of a number in a box.",
        "earn_tab": "ratez",
    },
    "sexi": {
        "label": "SeXi", "emoji": "\U0001f525", "icon": "sexi.png",
        "metric": "attractiveness",
        "rule": f"attractiveness of {ABOVE:g} or more from at least {MIN_RATINGS} members, shown by them",
        "what": "Members the room rates 6.9 or more on looks, who chose to show their number. Adults only.",
        "earn_tab": "ratez",
    },
}
CLASSES["thorough"] = {
    "label": "Thorough", "emoji": "\U0001f4af", "icon": "thorough.png",
    "metric": "Thorough rating",
    "rule": (f"a Thorough rating of {ABOVE:g} or more from finished BodieZ training in the last 28 days, "
             "with the badge shown"),
    "what": ("Members whose training is Thorough: 6.9 or more over at least 3 lifts. A badge for how completely "
             "somebody trains, not for how good their music is. Only members who show the badge are in it."),
    "earn_tab": "bodiez",
}
NOTE = ("A class is read from members' ratings when you ask and is never stored. It pays nothing "
        "and changes no rating, price or royalty: it only decides who you see or let in.")


def in_class(median, count):
    """Above the bar, with enough voices behind the number."""
    return median is not None and (count or 0) >= MIN_RATINGS and median >= ABOVE


def coach_voices(user_ids):
    """{user_id: (median of their recent takes, how many takes)} — the AI coach's voice.

    Corey: the coach counts toward a class as THREE voices (`COACH_VOTES`), so it can
    replace member ratings or supplement them. It LISTENED: the number is the median of
    the member's last `COACH_WINDOW` scored takes, on any coach, and it needs
    `MIN_COACH_TAKES` of them, so one lucky take is not a voice.

    What that traded away, said plainly: the coach scores the file it is sent and cannot
    tell whose performance it is. A take is the member's by their own declaration, so
    three takes of somebody else's record would read as ThuroZ with no member agreeing.
    A class pays nothing and moves no rating, so what that buys is being SEEN under a
    filter and let through a gate that asked for it; if it is abused, the cheap fix is
    to require one member's rating again (set `COACH_VOTES` to 2).

    It cuts both ways — a weak run of takes counts against, exactly as a strong one counts
    for — and the member's standing says the coach is in the number. One query.
    """
    from .models import TakeScore, _median
    from .royaltyfactor import COACH_WINDOW, MIN_COACH_TAKES
    ids = list(user_ids)
    if not ids:
        return {}
    takes = {}
    for uid, overall in (TakeScore.objects.filter(user_id__in=ids, overall__isnull=False)
                         .order_by("user_id", "-created_at").values_list("user_id", "overall")):
        row = takes.setdefault(uid, [])
        if len(row) < COACH_WINDOW:
            row.append(overall)
    return {uid: (_median(v), len(v)) for uid, v in takes.items() if len(v) >= MIN_COACH_TAKES}


def thuro_stat(human_scores, coach):
    """(median, voices, members, coach median or None) for one member's overall rating."""
    from .models import _median
    scores = list(human_scores or [])
    coach_median = coach[0] if coach else None
    if coach_median is not None:
        scores += [coach_median] * COACH_VOTES
    return _median(scores), len(scores), len(human_scores or []), coach_median


def classes_for(profiles, overall=None, attract=None, coach=None):
    """{user_id: [class keys]} for these profiles, batched.

    `overall` is `overall_scores` and `attract` is `attractiveness_stats`, when a caller
    already holds them (the member search does). SeXi also needs the member's own
    show/hide switch, and takes no coach voice: no AI reading of a face is ever stored.
    """
    from .models import (Membership, attractiveness_stats, overall_scores, profile_is_minor)
    profiles = list(profiles)
    ids = [p.user_id for p in profiles]
    if not ids:
        return {}
    overall = overall_scores(ids) if overall is None else overall
    attract = attractiveness_stats(ids) if attract is None else attract
    coach = coach_voices(ids) if coach is None else coach
    maybe_sexi = [i for i in ids if in_class(*attract.get(i, (None, 0)))]
    hidden = (set(Membership.objects.filter(user_id__in=maybe_sexi, attractiveness_public=False)
                  .values_list("user_id", flat=True)) if maybe_sexi else set())
    # Thorough is the BodieZ badge, read as it is WORN: a hidden badge is a disclosure, so it is no entry here
    # either (the same `visible=True` rule every mark follows). One query for the whole page.
    from .models import Badge
    from .thoroughz import KEYS as THOROUGH_KEYS
    thorough = set(Badge.objects.filter(user_id__in=ids, key__in=THOROUGH_KEYS, visible=True)
                   .values_list("user_id", flat=True))
    out = {}
    for p in profiles:
        keys = []
        median, voices, _members, _coach = thuro_stat(overall.get(p.user_id), coach.get(p.user_id))
        if in_class(median, voices):
            keys.append("thuro")
        if (p.user_id in maybe_sexi and p.user_id not in hidden and not profile_is_minor(p)):
            keys.append("sexi")
        if p.user_id in thorough:
            keys.append("thorough")
        if keys:
            out[p.user_id] = keys
    return out


def state_for(user):
    """Where this member stands on each class, in numbers they can check."""
    from .models import (attractiveness_stats, membership_for, overall_scores, profile_for,
                         profile_is_minor)
    from .royaltyfactor import MIN_COACH_TAKES
    p = profile_for(user)
    held = classes_for([p]).get(user.id, [])
    coach = coach_voices([user.id]).get(user.id)
    t_median, t_voices, t_members, t_coach = thuro_stat(overall_scores([user.id]).get(user.id), coach)
    a_median, a_count = attractiveness_stats([user.id]).get(user.id, (None, 0))
    out = {}
    who = (f"{t_members} member{'' if t_members == 1 else 's'}"
           + (f" and the AI coach ({t_coach:g} across your recent takes, counted as {COACH_VOTES})" if t_coach is not None else ""))
    row = {"is": "thuro" in held, "median": t_median, "count": t_voices, "members": t_members,
           "coach": t_coach, "coach_votes": COACH_VOTES if t_coach is not None else 0,
           "ratings_needed": max(0, MIN_RATINGS - t_voices)}
    if row["is"]:
        row["line"] = f"You are ThuroZ: {t_median:g} from {who}."
    elif t_voices < MIN_RATINGS:
        row["line"] = (f"{t_voices} of {MIN_RATINGS} voices so far ({who}). ThuroZ needs {MIN_RATINGS} and a "
                       f"median of {ABOVE:g} or more. The AI coach counts as {COACH_VOTES} once it has scored "
                       f"{MIN_COACH_TAKES} of your takes, so that alone is enough.")
    else:
        row["line"] = f"Your median is {t_median:g} from {who}. ThuroZ is {ABOVE:g} or more."
    out["thuro"] = row
    from .thoroughz import member_rating
    mr = member_rating(user)
    row = {"is": "thorough" in held, "median": mr["exact"], "count": mr["lifts"], "members": 0,
           "coach": None, "coach_votes": 0, "ratings_needed": 0}
    if row["is"]:
        row["line"] = f"You are Thorough: {mr['exact']:g} over {mr['lifts']} lifts."
    elif mr["exact"] is None:
        row["line"] = f"{mr['lifts']} of 3 lifts logged in the last 28 days. Thorough needs 3 and a rating of {ABOVE:g} or more."
    elif mr["exact"] >= ABOVE:
        row["line"] = f"Your rating is {mr['exact']:g}, but your Thorough badge is hidden, so you are not listed. Showing it is your choice."
    else:
        row["line"] = f"Your rating is {mr['exact']:g}. Thorough is {ABOVE:g} or more."
    out["thorough"] = row
    if not profile_is_minor(p):            # SeXi: not offered, explained or counted for a minor
        row = {"is": "sexi" in held, "median": a_median, "count": a_count, "members": a_count,
               "coach": None, "coach_votes": 0, "ratings_needed": max(0, MIN_RATINGS - a_count)}
        if row["is"]:
            row["line"] = f"You are SeXi: {a_median:g} from {a_count} members."
        elif a_count < MIN_RATINGS:
            row["line"] = (f"{a_count} of {MIN_RATINGS} ratings so far. SeXi needs {MIN_RATINGS} members' "
                           f"ratings and a median of {ABOVE:g} or more. No AI counts here: a reading of a face is never stored.")
        elif not membership_for(user).attractiveness_public:
            row["line"] = "Your number is hidden, so you are not listed as SeXi. Showing it is your choice."
        else:
            row["line"] = f"Your median is {a_median:g} from {a_count} members. SeXi is {ABOVE:g} or more."
        out["sexi"] = row
    return out


class ClassZView(APIView):
    """GET /api/economy/classz/ — what each class means, and where the caller stands."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mine = state_for(request.user)
        return Response({
            "above": ABOVE, "min_ratings": MIN_RATINGS, "note": NOTE,
            "classes": [{"key": k, **{f: v[f] for f in ("label", "emoji", "icon", "rule", "what", "earn_tab")}}
                        for k, v in CLASSES.items() if k in mine],
            "mine": mine,
        })
