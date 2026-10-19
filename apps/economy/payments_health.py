"""Whether money can actually move, readable without a Render login.

`storage_health` exists because a service reporting "ok" while quietly
deleting everyone's uploads is not telling the whole truth about itself. The
same is true of payments, and worse: an upload that vanishes is noticed by the
member who uploaded it, whereas a payment that takes someone's money and never
credits their wallet looks — from inside the app — exactly like nothing
happened at all.

Every failure this reports is invisible from the code, because the code is
fine. They are all facts about the deployment:

  * **No secret key.** Every checkout answers 503. Loud, at least.
  * **No webhook secret.** This is the quiet one, and the reason this file
    exists. Checkout works, Stripe takes the money, and the webhook that
    credits the wallet answers 503 to every delivery — so the member is
    charged and nothing arrives. Nothing in the app can see it: the failure is
    entirely on Stripe's side of the call.
  * **Test key, live buttons.** A `sk_test_` secret with a `pk_live_`
    publishable key (or the reverse) fails at the moment somebody pays, and
    the two values are set in different places by different people months
    apart. It is the single most common way a working integration stops
    working, and nothing anywhere reports it.

BOOLEANS AND MODES ONLY — never a key, never a fragment of one, never a
length. This endpoint is open to anybody. "Configured" is the whole question,
and any detail past it is a fact about a secret, published.

And it says CONFIGURED, not working. A key that is set can still be revoked,
or belong to an account Stripe has not activated for live charges. Only a real
payment proves that.
"""
from django.conf import settings


def _mode(key, test_prefix, live_prefix):
    """"test", "live" or "" — read from the key's own prefix, not from config.

    Stripe puts the mode in the key itself, so this cannot disagree with the
    key actually in use the way a separate STRIPE_MODE setting eventually
    would.
    """
    k = (key or "").strip()
    if k.startswith(test_prefix):
        return "test"
    if k.startswith(live_prefix):
        return "live"
    return ""


def payments_state():
    secret = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    publishable = getattr(settings, "STRIPE_PUBLISHABLE_KEY", "") or ""
    webhook = getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or ""

    secret_mode = _mode(secret, "sk_test_", "sk_live_")
    pub_mode = _mode(publishable, "pk_test_", "pk_live_")
    # Only a disagreement between two modes we could actually read is a
    # mismatch. One side unset is "not configured", which is a different
    # problem with a different fix, and reporting it as a mismatch would send
    # somebody looking for the wrong thing.
    mismatch = bool(secret_mode and pub_mode and secret_mode != pub_mode)

    problems = []
    if not secret:
        problems.append("STRIPE_SECRET_KEY is not set — every checkout answers 503.")
    if secret and not webhook:
        problems.append(
            "STRIPE_WEBHOOK_SECRET is not set — checkout works and Stripe takes "
            "the money, but the webhook that credits the wallet refuses every "
            "delivery, so a member is charged and nothing arrives."
        )
    if mismatch:
        problems.append(
            f"Key modes disagree: the secret key is {secret_mode} and the "
            f"publishable key is {pub_mode}. Payments fail at the moment "
            "somebody pays."
        )
    if secret_mode == "test":
        problems.append(
            "Stripe is in TEST mode — real cards are declined. Fine for a "
            "staging deploy, wrong for a live one."
        )

    paypal_id = getattr(settings, "PAYPAL_CLIENT_ID", "") or ""
    paypal_secret = getattr(settings, "PAYPAL_SECRET", "") or ""

    return {
        "stripe": {
            "configured": bool(secret),
            "mode": secret_mode or "unknown",
            "publishable_mode": pub_mode or "unknown",
            "modes_agree": not mismatch,
            # Named separately from `configured` because it is the half that
            # fails silently, and the half people forget on a new deploy.
            "webhook_configured": bool(webhook),
        },
        "paypal": {
            "configured": bool(paypal_id and paypal_secret),
            "mode": (getattr(settings, "PAYPAL_MODE", "") or "sandbox"),
        },
        # Withdrawals ride the same Stripe key, so they cannot work without it.
        "payouts": {"configured": bool(secret)},
        "ready": bool(secret and webhook and not mismatch),
        "problems": problems,
    }
