"""What a username may be — one rule, read by everything that writes one.

`UsernameAvailabilityView` already carried this regex and was the ONLY thing
that applied it. It is behind `IsAuthenticated`, so the one screen that needs
it — the signup form, where by definition nobody is signed in — could not call
it, and nothing did. Meanwhile `RegisterSerializer` is a plain
`serializers.Serializer` rather than a `ModelSerializer`, so Django's own
`UnicodeUsernameValidator` never ran either, and `create_user()` does not call
`full_clean()`. The field was `CharField(max_length=150)` and nothing else.

So every one of these registered, and each is a real account:

    "a/b"                 public profile 404s — no screen can address them
    "who?"  "hash#tag"    their own referral link truncates at the ? or #
    "<script>x</script>"  goes wherever a handle goes, including <title>
    "@everyone"           reads as a mention
    "."                   a handle that is a path segment

That is the two-writers failure this codebase already documents for profile
fields, with the checker as the writer that cleans and the one that actually
creates accounts as the passthrough. The rule lives here now and BOTH import
it.

Why these characters: a username is a URL segment (`/api/auth/users/<name>/`,
the public profile) and a query value (the `?ref=` invite, which is the
growth mechanic). Letters, digits and underscore survive both untouched, with
no encoding for anyone to get wrong.
"""
import re

# Deliberately narrow. Widening it later is safe; narrowing it strands the
# members who registered under the wider rule — the same thing TIER_LIMITS
# says about never lowering a live limit without a plan for whoever is over it.
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")

USERNAME_RULE = "3-20 characters: letters, numbers, and underscores only."

# Handles that are ours, or that read as somebody they are not. Checked
# case-insensitively.
RESERVED = {
    "admin", "administrator", "root", "owner", "staff", "support", "help",
    "moderator", "mod", "system", "everyone", "here", "channel", "official",
    "musicconnectz", "music_connectz", "mcz", "api", "login", "register",
    "logout", "settings", "account", "me", "null", "undefined", "anonymous",
}


def username_problem(value, *, taken=True):
    """Why this username can't be used, or None if it can.

    `taken` is False when the caller has already decided the uniqueness
    question itself — the availability view answers "is this yours?" before
    "is it somebody else's", and asking the database twice would be the point
    of having one helper thrown away.
    """
    value = (value or "").strip()
    if not USERNAME_RE.match(value):
        return f"Must be {USERNAME_RULE}"
    if value.lower() in RESERVED:
        return "That handle is reserved."
    if taken:
        from django.contrib.auth import get_user_model
        if get_user_model().objects.filter(username__iexact=value).exists():
            return "That username is taken."
    return None
