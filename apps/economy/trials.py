"""Daily trials — let people feel the tier before they buy it.

From the spec:

  * Free members trial Premium for **4 hours** a day, with a warning 15 minutes
    before it ends and an upgrade CTA when it locks.
  * Premium members trial StatZ (automations, CallZ, SuggestionZ) for
    **4 minutes** a day, with a warning 15 seconds before it ends.

The design decision that makes this real rather than decorative: `effective_tier`
is what the gates read. A trial that doesn't actually unlock anything is a
countdown timer attached to nothing. It expires on a timestamp, so there is no
job to run and no way for a trial to quietly become permanent — the moment
`expires_at` passes, every gate goes back to the paid tier on its own.

One trial per tier per day, keyed on a UTC date. That means the day rolls over
at midnight UTC rather than in the member's timezone; simple, and honest about
it in the payload rather than pretending otherwise.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import (TIER_DEBUG, TIER_FREE, TIER_PREMIUM, TIER_STATZ,
                     membership_for)

# tier being trialled -> who can trial it, for how long, and when to warn.
TRIAL_SPECS = {
    TIER_PREMIUM: {
        "from_tier": TIER_FREE,
        "seconds": 4 * 60 * 60,     # 4 hours
        "warn_seconds": 15 * 60,    # heads-up 15 minutes out
        "label": "Premium 🥇",
        "blurb": "Four hours of Premium, free, once a day.",
    },
    TIER_STATZ: {
        "from_tier": TIER_PREMIUM,
        "seconds": 4 * 60,          # 4 minutes
        "warn_seconds": 15,         # heads-up 15 seconds out
        "label": "StatZ 📈",
        "blurb": "Four minutes of StatZ — automations, CallZ and SuggestionZ.",
    },
}

TIER_RANK = [TIER_FREE, TIER_PREMIUM, TIER_STATZ, TIER_DEBUG]


def _rank(tier):
    try:
        return TIER_RANK.index(tier)
    except ValueError:
        return 0


class Trial(models.Model):
    """One member's trial of one tier on one day."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="trials")
    tier = models.CharField(max_length=12, db_index=True)
    day = models.DateField(db_index=True)
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        # The daily cap, enforced by the database rather than by a check that a
        # concurrent request could race past.
        unique_together = ("user", "tier", "day")
        ordering = ["-started_at"]

    def __str__(self):
        return f"Trial<{self.user_id}> {self.tier} until {self.expires_at:%H:%M}"

    @property
    def seconds_left(self):
        return max(0, int((self.expires_at - timezone.now()).total_seconds()))

    @property
    def is_active(self):
        return self.seconds_left > 0


def active_trial(user):
    """The member's running trial, or None. Never touches the database to
    expire anything — an expired row simply stops matching."""
    if not user or not getattr(user, "is_authenticated", False):
        return None
    return (Trial.objects.filter(user=user, expires_at__gt=timezone.now())
            .order_by("-expires_at").first())


def effective_tier(user):
    """The tier the gates should honour: the paid one, or a better active trial.

    Always takes the HIGHER of the two. A Premium member trialling StatZ gets
    StatZ; a Premium member whose old Premium trial row is somehow still live
    never gets pushed *down*.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return TIER_FREE
    paid = membership_for(user).tier
    trial = active_trial(user)
    if trial and _rank(trial.tier) > _rank(paid):
        return trial.tier
    return paid


def eligible_tier(user):
    """Which tier this member could trial next, or None."""
    paid = membership_for(user).tier
    for tier, spec in TRIAL_SPECS.items():
        if spec["from_tier"] == paid:
            return tier
    return None


def can_start(user, tier=None):
    """(ok, reason). Reason is member-facing when it's a no."""
    tier = tier or eligible_tier(user)
    spec = TRIAL_SPECS.get(tier)
    if not spec:
        return False, "There's no trial for that."
    paid = membership_for(user).tier
    if _rank(paid) >= _rank(tier):
        return False, f"You already have {tier.title()}."
    if spec["from_tier"] != paid:
        return False, (f"{spec['label']} trials are for "
                       f"{spec['from_tier'].title()} members.")
    if active_trial(user):
        return False, "You've got a trial running right now."
    if Trial.objects.filter(user=user, tier=tier,
                            day=timezone.now().date()).exists():
        return False, "You've used today's trial. Another one tomorrow."
    return True, ""


def start(user, tier=None):
    """(trial, error). Creates the row, or explains why not."""
    tier = tier or eligible_tier(user)
    ok, reason = can_start(user, tier)
    if not ok:
        return None, reason
    spec = TRIAL_SPECS[tier]
    now = timezone.now()
    trial, created = Trial.objects.get_or_create(
        user=user, tier=tier, day=now.date(),
        defaults={"expires_at": now + timezone.timedelta(seconds=spec["seconds"])},
    )
    if not created:
        # Lost a race against another request — the unique constraint held, and
        # the member gets the trial that already exists rather than an error.
        return trial, ""
    return trial, ""


def status(user):
    """Everything a countdown, a warning and a lock screen need."""
    trial = active_trial(user)
    paid = membership_for(user).tier
    next_tier = eligible_tier(user)
    out = {
        "paid_tier": paid,
        "effective_tier": effective_tier(user),
        "active": None,
        "available": None,
        # Said out loud because a member watching a clock deserves to know why
        # it reset when it did.
        "resets": "midnight UTC",
    }

    if trial:
        spec = TRIAL_SPECS.get(trial.tier, {})
        left = trial.seconds_left
        warn_at = spec.get("warn_seconds", 0)
        out["active"] = {
            "tier": trial.tier,
            "label": spec.get("label", trial.tier),
            "seconds_left": left,
            "expires_at": trial.expires_at.isoformat(),
            "warn_seconds": warn_at,
            # The client shouldn't have to work out when to raise the banner.
            "warning": left <= warn_at,
            "upgrade": f"/api/economy/{trial.tier}/checkout/",
        }

    if next_tier:
        ok, reason = can_start(user, next_tier)
        spec = TRIAL_SPECS[next_tier]
        out["available"] = {
            "tier": next_tier,
            "label": spec["label"],
            "blurb": spec["blurb"],
            "seconds": spec["seconds"],
            "can_start": ok,
            "reason": reason or None,
        }
    return out
