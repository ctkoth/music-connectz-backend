"""Who may see each profile field — private, member, or public.

Three states, set per field by the member. `name_public` was the boolean
version of this for one field; generalising it meant folding that in rather
than keeping both, because two mechanisms answering "may this person see this"
is the two-writers failure this codebase already has a section about.

WHAT THE LEVELS MEAN
  private  only you
  member   anybody signed in
  public   anybody at all, including the logged-out profile page

DEFAULTS ARE TODAY'S BEHAVIOUR, EXACTLY
Every default below is what that field already does, read off the two card
builders (`publicz.public_profile_dict` and `social`'s member card). That is
deliberate and it is the whole migration plan: nobody's exposure changes on
the day this ships. A member who never opens the control sees no difference,
and everybody can tighten from where they already are.

Defaulting anything tighter would have been the tempting choice and the wrong
one — links and bio are on the logged-out page today, and quietly pulling them
would break a member's shopfront without asking, on a deploy they never heard
about. Loosening by default would be worse.

ONLY DEVIATIONS ARE STORED
`Profile.visibility` holds just the fields a member has actually changed, so
the column stays small and an unset field follows the default forever — which
means a default can be corrected later without rewriting every row.
"""

PRIVATE = "private"
MEMBER = "member"
PUBLIC = "public"
LEVELS = (PRIVATE, MEMBER, PUBLIC)

# How far each level reaches. Comparing rank rather than strings means a check
# is "is the field's reach at least what this viewer is", and a fourth level
# could be inserted without hunting down every comparison.
_RANK = {PRIVATE: 0, MEMBER: 1, PUBLIC: 2}

DEFAULTS = {
    # On the logged-out card today.
    "display_name": PUBLIC,
    "bio": PUBLIC,
    "personas": PUBLIC,
    "links": PUBLIC,
    "badge_title": PUBLIC,

    # On the member card today, and not on the logged-out one.
    "avatar": MEMBER,
    "gender": MEMBER,
    "sign": MEMBER,
    "regions": MEMBER,
    "nationalities": MEMBER,
    "sober": MEMBER,
    "personality": MEMBER,
    "attracted_to": MEMBER,
    "age": MEMBER,

    # Served to nobody but the member today. `birthday` is the date itself —
    # `age` above is the band, and they are separate fields on purpose, because
    # "people may know roughly how old I am" and "people may know the day I was
    # born" are different answers and the second one is a security question.
    "birthday": PRIVATE,
    "location": PRIVATE,
    "substances": PRIVATE,
    "first_name": PRIVATE,
    "last_name": PRIVATE,
}


def clean_visibility(raw):
    """Normalise what a client sent into storable overrides.

    Junk is DROPPED, never refused: a profile write must not 400 over one bad
    key, which is the rule `clean_code` already follows for a personality
    letter. An unknown field or an unknown level is silently not an override,
    so the default applies — which is the safe direction, because the default
    is the member's current exposure.

    A value equal to the default is dropped too, so the row records choices
    rather than restating the defaults back at us.
    """
    if not isinstance(raw, dict):
        return {}
    out = {}
    for field, level in raw.items():
        field = str(field)
        if field not in DEFAULTS:
            continue
        level = str(level or "").strip().lower()
        if level not in LEVELS or level == DEFAULTS[field]:
            continue
        out[field] = level
    return out


def level_for(p, field):
    """This member's setting for one field, or the default if they never said."""
    stored = p.visibility if isinstance(getattr(p, "visibility", None), dict) else {}
    level = stored.get(field)
    return level if level in LEVELS else DEFAULTS.get(field, PRIVATE)


def can_see(p, field, viewer):
    """May `viewer` see `field` on profile `p`?

    Anonymous viewers are the PUBLIC audience, so they see fields set to
    public — the level name is about the field's reach, not the viewer's rank,
    and conflating the two is the mistake that would hide public fields from
    the logged-out page this exists to serve.
    """
    if viewer is not None and getattr(viewer, "is_authenticated", False):
        if viewer.pk == p.user_id:
            return True
        return _RANK[level_for(p, field)] >= _RANK[MEMBER]
    return _RANK[level_for(p, field)] >= _RANK[PUBLIC]


def settings_for(p):
    """Every field with its current level — for the screen that sets them.

    All of them, always, including the ones left at their default: a member can
    only check what they are exposing by seeing the whole list, which is the
    same reason the ZodiacZ panel publishes all twenty-four bonuses.
    """
    return [{"field": f, "level": level_for(p, f), "default": DEFAULTS[f]}
            for f in sorted(DEFAULTS)]


# Card keys that are DERIVED from a field rather than being it. `sign_cn` is
# the animal read off the same birthday as `sign`; `personality_axes` is the
# per-axis form of `personality`. Hiding the source and serving the derivative
# would be the setting doing nothing — the exact failure mode of a control that
# looks like it worked.
_DERIVED = {
    "sign_cn": "sign",
    "personality_axes": "personality",
    "real_name": "first_name",
}


def _blank_like(value):
    """The empty form of whatever was there.

    Blanked rather than removed, so a client that expects the key keeps
    working — and blanked to the same TYPE, because a screen that does
    `card.regions.map(...)` breaks on None.

    A hidden bool becomes None rather than False: `sober: False` is a claim
    ("they said no"), and answering a question nobody is entitled to ask with
    a lie is worse than not answering it.
    """
    if isinstance(value, str):
        return ""
    if isinstance(value, list):
        return []
    if isinstance(value, dict):
        return {}
    return None


def redact(card, p, viewer):
    """Blank every field on this card that `viewer` may not see.

    One pass over the finished dict rather than a check at each key, so a field
    added to a card builder is covered the moment it is named in DEFAULTS, and
    a builder cannot quietly forget one. That is the same reason `public_name`
    is a single reader.
    """
    for key in list(card):
        field = _DERIVED.get(key, key)
        if field in DEFAULTS and not can_see(p, field, viewer):
            card[key] = _blank_like(card[key])
    return card
