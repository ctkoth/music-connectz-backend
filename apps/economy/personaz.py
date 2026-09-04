"""One shape for a PersonaZ entry, and the recovery for the rows that lost it.

A persona is `{key, name, skills}`. It has been stored as a bare string (just a
key) and as the whole dict, and `clean_persona` accepts both — that part was
already true and is not new.

What is new is the third shape, which is not a shape anyone designed: a string
holding the *printed form* of a dict.

    "{'name': 'Independent Artist', 'emoji': '🎤', 'skills': []}"

Something ran `str()` over a persona before it reached the database. The write
path that did it is long fixed — `accounts.views` carries the note — but
**fixing a writer never repairs what it already wrote**, and this is the exact
failure the client-side `socialData.js` calls out about localStorage: the bad
shape is already sitting in people's accounts, so a member stays broken until
they happen to save their profile again.

Worse, it broke quietly. Every consumer of `profile.personas` in this codebase
guards with `if not isinstance(persona, dict): continue` — postz's skill
pricing, questz's rate check, occ_suggest, social's rate range, publicz's
public card. Those guards are correct and they are why nothing ever crashed;
they are also why nobody noticed. A member in this state does not see an error.
They see a persona that renders as machine noise on their profile, their
priced skills silently missing from what a post costs, and their public card
quietly short one persona. Nothing to report, so nothing gets reported.

So the recovery lives HERE and runs on the way IN and on the way OUT: a save
un-mangles it for good, and a read un-mangles it in the meantime for everybody
who has not saved since. `manage.py repair_personas --write` is the sweep that
makes the read-side repair stop being needed.
"""
import ast
import json
from urllib.parse import urlparse


def _recover(text):
    """A dict back out of a string that is the printed form of one, else None.

    `ast.literal_eval` evaluates literals only — no names, no calls, no
    attribute access — so this cannot execute what a member typed. JSON is
    tried too, because the same mistake made in JavaScript produces double
    quotes and `str()` in Python produces single ones, and a repair that only
    handles the language that caused it once is a repair that runs out.
    """
    text = (text or "").strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    for parse in (ast.literal_eval, json.loads):
        try:
            out = parse(text)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            continue
        if isinstance(out, dict):
            return out
    return None


def clean_persona(raw):
    """Normalize one PersonaZ entry, keeping its skills and their start dates.

    Always returns a dict, so downstream code has one shape to reason about.
    Skill stints are the input to `profile_max_experience`, so they are
    preserved verbatim — both the new `periods` list and the legacy single
    `start`.
    """
    if not isinstance(raw, dict):
        # A printed dict is recovered and then run through the SAME path a real
        # dict takes, rather than being special-cased into a shape of its own.
        # Whatever the supported shape carries is what survives the repair, and
        # it stays that way without anyone maintaining two versions of it.
        recovered = _recover(raw if isinstance(raw, str) else None)
        if recovered is not None:
            return clean_persona(recovered)
        return {"key": str(raw)[:60], "name": str(raw)[:60], "skills": []}

    skills = []
    for s in (raw.get("skills") or [])[:100]:
        if not isinstance(s, dict):
            name = str(s)[:80]
            if name:
                skills.append({"name": name})
            continue
        name = str(s.get("name", ""))[:80]
        if not name:
            continue
        # Stints. Experience is the SUM of these, so a member who stopped is
        # not credited for the years they were away. The legacy single `start`
        # is read as one still-open stint and preserved on the way through —
        # dropping it here would silently zero somebody's experience.
        periods = []
        for pr in (s.get("periods") or [])[:20]:
            if not isinstance(pr, dict):
                continue
            start = str(pr.get("start") or "")[:10]
            if not start:
                continue
            end = str(pr.get("end") or "")[:10]
            periods.append({"start": start, "end": end} if end else {"start": start})
        # Hourly rate, in cents. The blueprint prices CallZ by "the other
        # member's skill rate per hour" and nothing stored one, so the price
        # range had no metric to gate on.
        try:
            rate = max(0, int(s.get("rate_cents") or 0))
        except (TypeError, ValueError):
            rate = 0
        entry = {"name": name}
        if periods:
            entry["periods"] = periods
        else:
            start = str(s.get("start") or "")[:10]
            if start:
                entry["start"] = start
        if rate:
            entry["rate_cents"] = rate
        skills.append(entry)

    key = str(raw.get("key") or raw.get("name") or "")[:60]
    return {"key": key, "name": str(raw.get("name") or key)[:60], "skills": skills}


def personas_of(profile):
    """Every persona on a profile, in the one shape, repaired if it needs it.

    Read paths call this instead of touching `profile.personas` directly, so a
    member whose row was mangled sees their own personas correctly TODAY rather
    than after the next sweep and after their next save.
    """
    return [clean_persona(x) for x in (getattr(profile, "personas", None) or [])]


def needs_repair(stored):
    """True when this stored list is not already what `clean_persona` makes.

    The sweep's test, kept beside the repair so the two cannot disagree about
    what "broken" means.
    """
    stored = stored or []
    return [clean_persona(x) for x in stored] != list(stored)


# ---- Profile links ----
#
# A link is `{label, url}`, and it is rendered as `<a href>` on the member card
# AND on the logged-out public profile. `POST /api/economy/profile/` wrote the
# list straight off the request body, so an unvalidated URL there is a stored
# `javascript:` waiting for the next person to open somebody's page — React
# warns about one and puts it in the DOM anyway.
#
# The writer validates now. Like the persona repair above, that does nothing
# for what it already wrote, and this one is not cosmetic — so reads go through
# `links_of` too, and nobody is one un-run management command away from serving
# an executable href to a stranger.
SAFE_LINK_SCHEMES = ("http", "https", "mailto")


def clean_link(raw):
    """One `{label, url}`, or None if the URL is not one we will render.

    A scheme allowlist rather than a `javascript:` denylist: `data:`,
    `vbscript:` and every future one are refused by not being named, which is
    the only version of this check that does not need editing every time
    somebody finds a new way to spell it.
    """
    if isinstance(raw, str):
        raw = {"url": raw, "label": ""}
    if not isinstance(raw, dict):
        return None
    url = str(raw.get("url") or "").strip()[:500]
    if not url:
        return None
    try:
        scheme = (urlparse(url).scheme or "").lower()
    except ValueError:
        return None
    # A bare "musicconnectz.net" has no scheme and is what people actually
    # type, so it is completed rather than refused.
    if not scheme:
        url = "https://" + url
    elif scheme not in SAFE_LINK_SCHEMES:
        return None
    return {"label": str(raw.get("label") or "")[:80], "url": url}


def links_of(profile):
    """Every renderable link on a profile. Refused ones are dropped, not fixed:
    there is no honest guess at what somebody meant by `javascript:`."""
    return [l for l in (clean_link(x) for x in (getattr(profile, "links", None) or [])) if l]


def profile_needs_repair(profile):
    """True when this profile's stored JSON is not what the cleaners make of it."""
    personas = list(profile.personas or [])
    links = list(profile.links or [])
    return ([clean_persona(x) for x in personas] != personas
            or links_of(profile) != links)
