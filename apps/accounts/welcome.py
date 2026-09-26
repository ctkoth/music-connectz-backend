"""What a new member is owed for joining, in ONE place, whichever door they used.

`RegisterSerializer.create` had all of this inline, and the OAuth door had none
of it. So a member who joined with Google, Spotify, SoundCloud or any other
provider was:

  * not paid the signup welcome 🍥 — which the trial page and the signup screen
    both state up front, so the promise was false for exactly the members using
    the one-tap doors;
  * not credited to whoever invited them (`?ref=`), so an invite that ended in
    a provider button paid nobody;
  * not given the Boss Take they had scored at /try before there was an account
    to put it in — the take the whole trial page exists to save.

Two functions rather than one because `RegisterSerializer` writes the birthday
between them and its order is kept exactly as it was. The OAuth door calls
`welcome_oauth_member`, which runs both in a savepoint and SWALLOWS failure:
signing in with a provider must never be the thing that fails because a bonus
had a bad day. (Register is different on purpose — it is one atomic block, so a
failure there leaves no half-made account to be stuck behind.)
"""
import logging

from django.contrib.auth import get_user_model
from django.db import transaction

logger = logging.getLogger(__name__)

User = get_user_model()


def award_signup_bonuses(user):
    """The welcome 🍥 for the member, and the platform owner's bonus for a join."""
    from apps.economy.models import SIGNUP_WELCOME_SPINAZ, award_spinaz
    from apps.economy.views import platform_owner

    award_spinaz(user, SIGNUP_WELCOME_SPINAZ, "signup welcome bonus",
                 app_key="profilez", target="signup")
    owner = platform_owner()
    if owner and owner.id != user.id:
        award_spinaz(owner, SIGNUP_WELCOME_SPINAZ, f"new member join ({user.username})",
                     app_key="profilez", target="signup")


def attach_signup_context(user, ref="", trial_token=""):
    """Whatever brought them: an inviter, and a take scored at the door.

    Both are best-effort by design — a stale token or an unknown inviter must
    never cost somebody their registration — and both take strings that arrived
    from somebody who was not signed in, so neither is trusted raw.
    """
    from apps.economy.models import claim_trial_take, record_referral

    code = str(ref or "").strip()
    if code and code.lower() != user.username.lower():
        referrer = User.objects.filter(username__iexact=code).first()
        if referrer:
            record_referral(referrer, user)

    token = str(trial_token or "").strip()
    if token:
        claim_trial_take(user, token)


def welcome_oauth_member(user, data):
    """The OAuth door's version: everything above, for a NEW account only.

    Callers gate this on `made` — a returning member must never be paid the
    welcome again. Runs in a savepoint so a failure part-way undoes the part
    that ran, and logs instead of raising so the sign-in itself always lands.
    """
    data = data or {}
    try:
        with transaction.atomic():
            award_signup_bonuses(user)
            attach_signup_context(user, data.get("ref"), data.get("trial_token"))
    except Exception:  # noqa: BLE001 — a bonus must never break a sign-in
        logger.exception("oauth: could not welcome new member %s", getattr(user, "id", "?"))
