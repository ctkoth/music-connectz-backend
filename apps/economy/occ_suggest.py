"""SuggestionZ and AutomationZ — the two toggles, finally doing something.

Both have been stored booleans since OCC shipped. The settings screen gated
them by tier, saved them, and nothing anywhere read them. A switch that changes
no behaviour is the same lie as a rate nothing pays.

What they are, and the difference between them:

* **SuggestionZ** (Premium) reads the member's own data and proposes work,
  saying WHAT it would do, WHY, and HOW. It then waits. A Premium member taps
  "Do it" — the confirmation is the feature, not a limitation of the tier.
* **AutomationZ** (StatZ) removes that tap for the suggestions that are safe to
  take without asking, and notifies you as it happens.

**AutomationZ does not invent actions.** It removes a confirmation from work
that was going to be offered anyway. That distinction is the whole safety
argument: the member is never surprised by a category of action they hadn't
already been shown.

And most suggestions are NOT auto-safe, deliberately. Anything that publishes
your work, spends your money, or is visible to other members keeps its
confirmation at every tier, StatZ included. `auto_safe` is therefore a property
of the ACTION, never of the member's tier — a tier can remove a tap, it cannot
make an irreversible thing reversible.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Badge,
    OccOutput,
    OccTask,
    notify,
    membership_for,
    occ_settings_for,
    profile_for,
    recheck_badges,
)
from .occ_spec import tier_at_least
from .personaz import personas_of


def _unpriced_skills(user):
    """Skills the member claims with no rate — posts using them cost nothing."""
    out = []
    for persona in personas_of(profile_for(user)):
        for s in (persona.get("skills") or []):
            if isinstance(s, dict) and s.get("name") and not s.get("rate_cents"):
                out.append(s["name"])
    return out[:10]


def _unverified_links(user):
    return [l for l in (profile_for(user).links or [])
            if isinstance(l, dict) and l.get("url") and not l.get("verified")][:5]


def suggestions_for(user):
    """What OCC would propose right now, from evidence already in the data.

    Every entry explains itself — what, why, how — because the spec is explicit
    that all three are required, and because a suggestion you can't evaluate is
    an instruction.
    """
    out = []

    # --- auto-safe: touches only this member's own state, and is reversible.
    earned = [k for k in _earnable(user)]
    if earned:
        out.append({
            "key": "claim_badges", "auto_safe": True, "kind": OccTask.KIND_OTHER,
            "title": f"Claim {len(earned)} badge{'s' if len(earned) > 1 else ''} you've earned",
            "what": "Award the badges whose conditions you already meet.",
            "why": "You've done the work; the badge and its effect are sitting there "
                   "unclaimed, so you're not getting the Energy or the allowances.",
            "how": "Re-checks the evidence already in your account and grants what passes.",
        })

    stale = OccTask.objects.filter(user=user, status=OccTask.STATUS_FAILED).count()
    if stale >= 5:
        out.append({
            "key": "clear_failed", "auto_safe": True, "kind": OccTask.KIND_OTHER,
            "title": f"Clear {stale} failed tasks",
            "what": "Cancel the failed tasks cluttering TaskZ.",
            "why": "A list you can't read is a list you stop reading, and the "
                   "failures are hiding what's actually queued.",
            "how": "Marks them cancelled. Nothing is deleted and nothing is undone.",
        })

    # --- suggest-only: publishes, spends, or is visible to other people.
    unshared = OccOutput.objects.filter(user=user, shared_post__isnull=True).count()
    if unshared:
        out.append({
            "key": "share_work", "auto_safe": False, "kind": OccTask.KIND_OTHER,
            "title": f"Post {unshared} piece{'s' if unshared > 1 else ''} of WorkZ",
            "what": "Share what OCC made so it can be rated and commented on.",
            "why": "Unposted work earns nothing — no rating, no skill rating, no reach.",
            "how": "Open WorkZ and press Post it. It costs the skills you put on it, "
                   "and the row says how much first.",
            "tab": "occ", "target": "occ-workz",
        })

    unpriced = _unpriced_skills(user)
    if unpriced:
        out.append({
            "key": "price_skills", "auto_safe": False, "kind": OccTask.KIND_OTHER,
            "title": f"Put a price on {len(unpriced)} skill{'s' if len(unpriced) > 1 else ''}",
            "what": f"Set an hourly rate for {', '.join(unpriced[:3])}"
                    + ("…" if len(unpriced) > 3 else "") + ".",
            "why": "An unpriced skill is worth nothing to the search that matches "
                   "people by price, and posts using it cost you no Energy — which "
                   "sounds free but means the work reads as worthless.",
            "how": "ProfileZ → PersonaZ → set a rate per skill.",
            "tab": "profilez", "target": "personaz",
        })

    links = _unverified_links(user)
    if links:
        out.append({
            "key": "verify_social", "auto_safe": False, "kind": OccTask.KIND_OTHER,
            "title": f"Verify {len(links)} linked account{'s' if len(links) > 1 else ''}",
            "what": "Prove the accounts on your profile are yours.",
            "why": "Unverified followers don't count toward reach, and reach is what "
                   "pays your hourly Energy. It also earns Verified Reach 📡 (+25%).",
            "how": "SocialZ → Verify. We read the follower count off the page; you "
                   "never type it.",
            "tab": "profilez", "target": "socialz",
        })

    return out


def _earnable(user):
    """Badge keys the member qualifies for but hasn't been given yet.

    Read-only: it asks the same checks `recheck_badges` asks, without awarding,
    so a suggestion can be COUNTED before it is taken.
    """
    from .models import BADGES
    have = {b.key for b in Badge.objects.filter(user=user)}
    out = []
    for key, spec in BADGES.items():
        check = spec.get("check")
        if not check or key in have:
            continue
        try:
            if check(user):
                out.append(key)
        except Exception:
            continue
    return out


def perform(user, key):
    """Run an auto-safe suggestion. Returns (detail, undo_payload)."""
    if key == "claim_badges":
        won = recheck_badges(user)
        return f"Claimed {len(won)} badge(s): {', '.join(won)}" if won else "Nothing to claim", \
               {"action": "claim_badges", "granted": won}
    if key == "clear_failed":
        ids = list(OccTask.objects.filter(user=user, status=OccTask.STATUS_FAILED)
                   .values_list("id", flat=True))
        OccTask.objects.filter(id__in=ids).update(status=OccTask.STATUS_CANCELLED)
        return f"Cleared {len(ids)} failed task(s)", {"action": "clear_failed", "ids": ids}
    return "", {}


class OccSuggestView(APIView):
    """GET what OCC would propose; POST turns proposals into TaskZ rows.

    The POST is where the two toggles finally differ from each other:
    AutomationZ runs the auto-safe ones on the spot; SuggestionZ leaves every
    one of them waiting for a tap.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        s = occ_settings_for(request.user)
        tier = membership_for(request.user).tier
        items = suggestions_for(request.user)
        automation = bool(s.automation and tier_at_least(tier, "statz"))
        return Response({
            "suggestions": items,
            "suggestionz": bool(s.suggestionz and tier_at_least(tier, "premium")),
            "suggestionz_allowed": tier_at_least(tier, "premium"),
            "automation": automation,
            "automation_allowed": tier_at_least(tier, "statz"),
            "auto_safe": [i["key"] for i in items if i["auto_safe"]],
            "needs_you": [i["key"] for i in items if not i["auto_safe"]],
            # Said plainly, because "StatZ automates everything" is the thing a
            # member would otherwise assume and be wrong about.
            "note": "AutomationZ only removes the confirmation from actions that are "
                    "safe to take without asking. Anything that publishes your work, "
                    "spends your balance, or other members can see keeps its "
                    "confirmation on every tier.",
        })

    def post(self, request):
        s = occ_settings_for(request.user)
        tier = membership_for(request.user).tier
        if not tier_at_least(tier, "premium"):
            return Response(
                {"detail": "SuggestionZ is a Premium feature — it reads your account "
                           "and tells you what's worth doing next.",
                 "required_tier": "premium"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not s.suggestionz:
            return Response({"detail": "SuggestionZ is switched off in OCC settings.",
                             "tab": "occ", "target": "occ-settings"},
                            status=status.HTTP_409_CONFLICT)

        automation = bool(s.automation and tier_at_least(tier, "statz"))
        wanted = (request.data or {}).get("key")
        items = [i for i in suggestions_for(request.user)
                 if not wanted or i["key"] == wanted]
        made, ran = [], []
        for item in items:
            task = OccTask.objects.filter(user=request.user, title=item["title"]).first()
            if task and task.status in (OccTask.STATUS_SUGGESTED, OccTask.STATUS_QUEUED):
                continue        # already proposed; proposing again is nagging
            auto = automation and item["auto_safe"]
            task = OccTask.objects.create(
                user=request.user, title=item["title"][:200], kind=item["kind"],
                what=item["what"], why=item["why"], how=item["how"],
                status=OccTask.STATUS_QUEUED if auto else OccTask.STATUS_SUGGESTED,
                automated=auto,
            )
            if auto:
                detail, undo = perform(request.user, item["key"])
                task.status = OccTask.STATUS_DONE
                task.progress = 100
                task.detail = detail
                task.undo_payload = undo
                task.save(update_fields=["status", "progress", "detail", "undo_payload",
                                         "updated_at"])
                # The promise AutomationZ makes in exchange for not asking.
                # NOT log_resource: LogZ is a resource ledger and returns early
                # on a zero amount, so those calls wrote nothing at all. A
                # notification is the record that actually reaches the member.
                notify(request.user, "occ",
                       f"🤖 OCC did '{task.title}' without asking — {detail}. "
                       "Undo it in TaskZ.")
                ran.append(task.id)
            else:
                made.append(task.id)

        return Response({
            "suggested": made, "ran": ran,
            "automation": automation,
            "detail": (f"{len(ran)} done, {len(made)} waiting on you."
                       if automation else f"{len(made)} suggestion(s) waiting on you."),
        }, status=status.HTTP_201_CREATED)
