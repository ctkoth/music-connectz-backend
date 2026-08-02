"""One rule, in one place: collaborate across ages, don't date across them.

Music ConnectZ is an all-ages creative platform. A 15-year-old artist working
with a 30-year-old producer is the ordinary case — it is what a school music
programme, a label internship and every art community on the internet already
are, and gating it would remove the thing that makes the platform worth being
on for young members.

So the line is NOT drawn around collaboration. It is drawn around the surfaces
that are about somebody's body or romantic availability:

    COLLABORATIVE   open across ages
                    CollabZ, MangaZ, BattleZ, VenueZ, PostZ, messaging
                    about work, skills, genres, ratings of the WORK

    ADULTS ONLY     verified 18+ on both sides, no exceptions
                    attractiveness rating, attractiveness search,
                    FaceZ scoring, "attracted to", anything dating-shaped

The distinction is between *rating what somebody made* and *rating what
somebody looks like*. A minor's mix can be scored 1–10 all day; a minor's face
cannot be scored at all, by anyone, including other minors.

Before this module, that was backwards: MangaZ rooms gated adults out of
collaborating, while `AttractivenessRateView` let any adult score a 14-year-old
1–10 and `searchfilters` would happily return that minor for an
"attractiveness 8+" query. The collaboration was fenced and the dating surface
was not.

## Why unknown age is treated differently in each direction

`is_minor` returns False for an unknown age, so a half-finished profile doesn't
break collaboration. `adults_only_error` refuses on an unknown age, because
"we don't know" is not "we checked". Same missing data, opposite defaults —
chosen so the failure mode on each side is the harmless one.
"""
from .models import profile_age, profile_for


def age_of(user):
    """Their age, or None when we don't know."""
    return profile_age(profile_for(user))


def is_minor(user):
    """True only when we KNOW they're under 18.

    Unknown counts as not-a-minor on purpose: this gates collaboration, and
    turning every incomplete profile into a locked one teaches people to lie
    about their birthday, which makes the data worse for the checks that
    actually matter.
    """
    age = age_of(user)
    return age is not None and age < 18


def is_verified_adult(user):
    """A birthday typed into a form is not age verification."""
    return bool(getattr(profile_for(user), "verified_18plus", False))


def can_collaborate(user_a, user_b):
    """Anyone may make things with anyone. Stated as a function so the answer
    lives next to the restriction rather than being an absence of one."""
    return True


def adults_only_error(actor, target=None):
    """Why this pair may not use a body/dating surface, or None.

    Both sides have to be adults, and a minor is refused whether they are the
    one being rated or the one doing the rating — a 16-year-old scoring adults
    out of 10 is the same feature pointed the other way.

    Unknown age is refused here, unlike in `is_minor`. On this side of the line
    the safe default is "no": an unverified profile that turns out to belong to
    a 15-year-old is exactly the case this exists to stop.
    """
    for who, user in (("You", actor), ("They", target)):
        if user is None:
            continue
        if is_minor(user):
            return (f"{who} can't use this — rating how people look is 18+ "
                    f"only. Collaborating, posting and rating each other's "
                    f"work are open to everyone.")
        if age_of(user) is None:
            return (f"{who}'ll need a birthday on the profile first — rating "
                    f"how people look is 18+ only.")
    return None


def excluded_from_body_ratings(user):
    """True when this member must not appear in any looks-based list at all.

    Not the same as opting out: a member choosing to hide their score is a
    preference, this is a floor. It is checked at read time as well as write
    time, because ratings collected before a birthday was filled in must stop
    counting the moment we learn who they belong to.
    """
    return is_minor(user) or age_of(user) is None
