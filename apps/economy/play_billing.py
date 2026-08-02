"""Google Play Billing — verify a purchase server-side, then grant it.

Why this exists: Play's payments policy requires digital goods bought inside the
Android app to go through Google Play Billing, not Stripe. See GOOGLE_PLAY.md §9 —
it's the most likely reason the app gets pulled.

The rule that shapes every line here: **the client is never trusted.** A
`purchaseToken` from the Digital Goods API is a claim, not a receipt. It is
checked against Google's Play Developer API, the product id is mapped to a value
*server-side*, and the token is recorded so a replay can't be paid twice. A client
that says "I bought the $50 pack" gets whatever `PLAY_PRODUCTS` says that product
id is worth, or nothing.

Four things that are easy to get wrong and are handled:

1. **Idempotency.** One purchase token grants exactly once, enforced by a unique
   column, not by a check-then-write.
2. **Acknowledgement.** Play auto-refunds any purchase not acknowledged within
   three days. We acknowledge after granting — in that order, so a failure leaves
   a refundable purchase rather than a granted-but-unpaid one.
3. **Account binding.** The client sets `obfuscatedExternalAccountId` to the
   member's id. If Google reports one and it isn't this member, the purchase is
   refused — otherwise a leaked token could be redeemed by another account.
4. **Pending purchases.** `purchaseState: 2` means the member chose cash at a
   convenience store. It is not a sale yet, so nothing is granted.

Configuration (Render env):

    PLAY_PACKAGE_NAME=net.musicconnectz.app
    PLAY_SERVICE_ACCOUNT_JSON={"type":"service_account", …}   # the whole JSON

The service account comes from Google Cloud, is granted "View financial data" +
"Manage orders" in Play Console → Users and permissions, and needs the
androidpublisher scope. Nothing here works until it's set; the endpoint answers
503 rather than pretending.
"""
import json
import logging
import os
import time

import requests
from django.db import transaction
from django.utils import timezone

from .catalog import (FOUNDING_MONTH_CENTS, FOUNDING_YEAR_CENTS,
                      LIFETIME_PRICE_CENTS, PREMIUM_MONTH_CENTS,
                      PREMIUM_YEAR_CENTS)
from .models import TIER_PREMIUM, TIER_STATZ, credit_funds, grant_lifetime, membership_for

log = logging.getLogger("apps.omviardz")

API_ROOT = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/androidpublisher"
TIMEOUT = 20

KIND_WALLET = "wallet"
KIND_PREMIUM = "premium"
KIND_STATZ = "statz"
KIND_LIFETIME = "lifetime"

# What each Play product id is worth. THE PRICES HERE ARE NOT CHARGED — Google
# charges what the Play Console says. These are what the member RECEIVES, and the
# two have to be kept in step by hand when you create the products in Console.
# A mismatch is a real risk, so `audit_play_products` prints both to compare.
PLAY_PRODUCTS = {
    # Consumable wallet top-ups. `cents` is what lands in the wallet.
    "topup_500": {"kind": KIND_WALLET, "cents": 500, "name": "$5 wallet top-up",
                  "type": "product"},
    "topup_1000": {"kind": KIND_WALLET, "cents": 1000, "name": "$10 wallet top-up",
                   "type": "product"},
    "topup_2500": {"kind": KIND_WALLET, "cents": 2500, "name": "$25 wallet top-up",
                   "type": "product"},
    "topup_5000": {"kind": KIND_WALLET, "cents": 5000, "name": "$50 wallet top-up",
                   "type": "product"},
    # Subscriptions — granted as a tier, revoked when Play says it lapsed.
    "premium_month": {"kind": KIND_PREMIUM, "cents": PREMIUM_MONTH_CENTS,
                      "name": "Premium monthly", "type": "subscription"},
    "premium_year": {"kind": KIND_PREMIUM, "cents": PREMIUM_YEAR_CENTS,
                     "name": "Premium yearly", "type": "subscription"},
    "statz_month": {"kind": KIND_STATZ, "cents": FOUNDING_MONTH_CENTS,
                    "name": "StatZ monthly", "type": "subscription"},
    "statz_year": {"kind": KIND_STATZ, "cents": FOUNDING_YEAR_CENTS,
                   "name": "StatZ yearly", "type": "subscription"},
    # One-time, non-consumable.
    "statz_lifetime": {"kind": KIND_LIFETIME, "cents": LIFETIME_PRICE_CENTS,
                       "name": "StatZ lifetime", "type": "product"},
}

# Google's purchaseState for one-time products.
STATE_PURCHASED = 0
STATE_CANCELLED = 1
STATE_PENDING = 2

# subscriptionsv2 states that mean "this member is entitled right now". Grace
# period counts: their card failed but Play is still retrying, and cutting off a
# paying member mid-retry is how you turn a billing blip into a cancellation.
ACTIVE_SUB_STATES = {
    "SUBSCRIPTION_STATE_ACTIVE",
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
}

_token_cache = {"access_token": "", "expires_at": 0.0}


# ---------------------------------------------------------------- config
def package_name():
    return os.environ.get("PLAY_PACKAGE_NAME", "net.musicconnectz.app")


def service_account():
    """The service account dict, or None when Play Billing isn't configured.

    Accepts the JSON inline (PLAY_SERVICE_ACCOUNT_JSON) or a path to it
    (PLAY_SERVICE_ACCOUNT_FILE) — Render sets env vars, a container mounts files,
    and both are normal.
    """
    raw = os.environ.get("PLAY_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        path = os.environ.get("PLAY_SERVICE_ACCOUNT_FILE", "").strip()
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    raw = fh.read()
            except OSError as exc:  # pragma: no cover
                log.info("play: cannot read service account file (%s)", exc)
                return None
    if not raw:
        return None
    try:
        sa = json.loads(raw)
    except ValueError:
        log.info("play: PLAY_SERVICE_ACCOUNT_JSON is not valid JSON")
        return None
    if not (sa.get("client_email") and sa.get("private_key")):
        log.info("play: service account JSON is missing client_email/private_key")
        return None
    return sa


def configured():
    return service_account() is not None


# ---------------------------------------------------------------- auth
def access_token(force=False):
    """A cached OAuth token for the Play Developer API, or None.

    Signed locally with PyJWT (already a dependency for Apple OAuth) rather than
    pulling in google-auth for one JWT.
    """
    now = time.time()
    if not force and _token_cache["access_token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["access_token"]

    sa = service_account()
    if not sa:
        return None
    try:
        import jwt

        claims = {
            "iss": sa["client_email"],
            "scope": SCOPE,
            "aud": TOKEN_URL,
            "iat": int(now),
            "exp": int(now) + 3600,
        }
        assertion = jwt.encode(claims, sa["private_key"], algorithm="RS256")
        resp = requests.post(
            TOKEN_URL,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                  "assertion": assertion},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            return None
        _token_cache["access_token"] = token
        _token_cache["expires_at"] = now + int(payload.get("expires_in", 3600))
        return token
    except Exception as exc:
        log.warning("play: could not get an access token (%s)", str(exc)[:200])
        return None


def _get(url):
    token = access_token()
    if not token:
        return None, "Play Billing is not configured on the server."
    try:
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return None, f"Could not reach Google Play: {str(exc)[:120]}"
    if resp.status_code == 404:
        # Google says 404 for a token it has never seen — which is what a forged
        # or already-consumed token looks like.
        return None, "Google Play does not recognise that purchase."
    if resp.status_code == 401:
        # Token may have been revoked mid-flight; one retry with a fresh one.
        token = access_token(force=True)
        if token:
            resp = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                                timeout=TIMEOUT)
    if resp.status_code >= 400:
        log.info("play: verify failed %s %s", resp.status_code, resp.text[:300])
        return None, f"Google Play rejected the check ({resp.status_code})."
    try:
        return resp.json(), ""
    except ValueError:
        return None, "Google Play returned something unreadable."


# ---------------------------------------------------------------- verification
def verify_product(product_id, purchase_token):
    """Check a one-time product purchase. Returns (info, error)."""
    url = f"{API_ROOT}/{package_name()}/purchases/products/{product_id}/tokens/{purchase_token}"
    data, err = _get(url)
    if err:
        return None, err
    state = data.get("purchaseState", STATE_CANCELLED)
    if state == STATE_PENDING:
        return None, "That purchase is still pending with Google — nothing to grant yet."
    if state != STATE_PURCHASED:
        return None, "That purchase was cancelled or refunded."
    return {
        "order_id": data.get("orderId", ""),
        "account_id": data.get("obfuscatedExternalAccountId", ""),
        "acknowledged": data.get("acknowledgementState") == 1,
        "purchased_at": data.get("purchaseTimeMillis", ""),
        "raw_state": state,
    }, ""


def verify_subscription(purchase_token):
    """Check a subscription via subscriptionsv2. Returns (info, error).

    v2 rather than v1 because v1 is deprecated, and because v2 reports the
    product through `lineItems` — which is what lets us confirm the member is
    actually subscribed to the product they claimed rather than a cheaper one.
    """
    url = f"{API_ROOT}/{package_name()}/purchases/subscriptionsv2/tokens/{purchase_token}"
    data, err = _get(url)
    if err:
        return None, err
    state = data.get("subscriptionState", "")
    if state not in ACTIVE_SUB_STATES:
        return None, f"That subscription is not active ({state or 'unknown state'})."
    line_items = data.get("lineItems") or []
    products = [li.get("productId") for li in line_items if li.get("productId")]
    ids = data.get("externalAccountIdentifiers") or {}
    return {
        "order_id": data.get("latestOrderId", ""),
        "account_id": ids.get("obfuscatedExternalAccountId", ""),
        "products": products,
        "expires_at": (line_items[0].get("expiryTime") if line_items else ""),
        "acknowledged": data.get("acknowledgementState") == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        "raw_state": state,
    }, ""


def acknowledge(product_id, purchase_token, subscription=False):
    """Tell Google we've delivered the goods.

    Play auto-refunds anything unacknowledged after three days. Best-effort by
    design: the member has already been granted what they bought, so a failure
    here must not undo that — it gets logged, and the worst case is Google
    refunding a purchase we honoured, which is visible in the Console rather than
    silent.
    """
    token = access_token()
    if not token:
        return False
    kind = "subscriptions" if subscription else "products"
    url = (f"{API_ROOT}/{package_name()}/purchases/{kind}/{product_id}"
           f"/tokens/{purchase_token}:acknowledge")
    try:
        resp = requests.post(url, headers={"Authorization": f"Bearer {token}"},
                             json={}, timeout=TIMEOUT)
        if resp.status_code >= 400:
            log.info("play: acknowledge failed %s %s", resp.status_code, resp.text[:200])
            return False
        return True
    except requests.RequestException as exc:
        log.info("play: acknowledge failed (%s)", str(exc)[:160])
        return False


# ---------------------------------------------------------------- granting
def _grant(user, product_id, spec):
    """Apply what the product buys. Returns a short description of what happened."""
    kind = spec["kind"]
    if kind == KIND_WALLET:
        # Same treatment as a Stripe/PayPal top-up so the member gets identical
        # credit for identical money whichever way they paid. NOTE: Google has
        # already taken its 15-30% before this, so the platform's own developer
        # tax on top is a double cut — a pricing decision, flagged in
        # GOOGLE_PLAY.md rather than silently changed here.
        dev, net = credit_funds(user, spec["cents"], note=f"Play: {spec['name']}")
        return f"credited {net}c (dev tax {dev}c)"
    if kind == KIND_LIFETIME:
        return "lifetime granted" if grant_lifetime(user) else "lifetime sold out"

    tier = TIER_PREMIUM if kind == KIND_PREMIUM else TIER_STATZ
    m = membership_for(user)
    m.tier = tier
    m.last_paid_at = timezone.now()
    m.last_payment_ref = f"play:{product_id}"
    m.last_payment_kind = f"play_{product_id}"
    m.save(update_fields=["tier", "last_paid_at", "last_payment_ref",
                          "last_payment_kind", "updated_at"])
    return f"tier set to {tier}"


def redeem(user, product_id, purchase_token):
    """Verify a Play purchase and grant it, exactly once. Returns (result, error).

    The order of operations is the whole point:

        map the product server-side  ->  verify with Google  ->  bind to the user
        ->  claim the token (unique insert)  ->  grant  ->  acknowledge

    Claiming before granting means a concurrent duplicate request loses the race
    at the database rather than crediting twice.
    """
    from .models import PlayPurchase

    product_id = str(product_id or "").strip()
    purchase_token = str(purchase_token or "").strip()
    if not product_id or not purchase_token:
        return None, "product_id and purchase_token are required."

    spec = PLAY_PRODUCTS.get(product_id)
    if not spec:
        return None, f"Unknown product '{product_id}'."
    if not configured():
        return None, "Play Billing is not configured on the server."

    is_sub = spec["type"] == "subscription"
    info, err = (verify_subscription(purchase_token) if is_sub
                 else verify_product(product_id, purchase_token))
    if err:
        return None, err

    # A subscription token proves entitlement to whatever Google lists on it, not
    # to whatever the client typed.
    if is_sub and info["products"] and product_id not in info["products"]:
        return None, (f"That subscription is for {info['products'][0]}, not {product_id}.")

    # Account binding: the client sets this to the member's id at purchase time.
    # Absent is tolerated (older clients); present and wrong is refused.
    claimed = str(info.get("account_id") or "")
    if claimed and claimed != str(user.id):
        log.warning("play: token for account %s redeemed by user %s", claimed, user.id)
        return None, "That purchase belongs to a different account."

    existing = PlayPurchase.objects.filter(purchase_token=purchase_token).first()
    if existing:
        # Idempotent: the same token replayed returns the original outcome.
        return {
            "product_id": existing.product_id,
            "granted": existing.granted,
            "detail": existing.detail,
            "duplicate": True,
        }, ""

    try:
        with transaction.atomic():
            claim = PlayPurchase.objects.create(
                user=user, product_id=product_id, purchase_token=purchase_token,
                order_id=info.get("order_id", "")[:120], kind=spec["kind"],
                value_cents=spec["cents"], subscription=is_sub,
            )
            claim.detail = _grant(user, product_id, spec)
            claim.granted = True
            claim.save(update_fields=["detail", "granted"])
    except Exception as exc:
        # A unique-constraint collision means another request won the race and has
        # already granted it. Anything else is a real failure.
        dup = PlayPurchase.objects.filter(purchase_token=purchase_token).first()
        if dup:
            return {"product_id": dup.product_id, "granted": dup.granted,
                    "detail": dup.detail, "duplicate": True}, ""
        log.warning("play: grant failed for %s (%s)", product_id, str(exc)[:200])
        return None, "Could not apply that purchase. Nothing was charged twice."

    # After granting, never before: a failure here leaves a purchase Google may
    # refund, which is recoverable. The reverse would grant goods we weren't paid
    # for and leave no trace.
    acked = acknowledge(product_id, purchase_token, subscription=is_sub)
    if acked and not claim.acknowledged:
        claim.acknowledged = True
        claim.save(update_fields=["acknowledged"])

    return {
        "product_id": product_id,
        "name": spec["name"],
        "kind": spec["kind"],
        "granted": True,
        "detail": claim.detail,
        "acknowledged": acked,
        "duplicate": False,
    }, ""


def catalog_payload():
    """The products the client may offer. Values are what the member receives."""
    return {
        "configured": configured(),
        "package_name": package_name(),
        "products": [
            {"product_id": pid, "name": spec["name"], "kind": spec["kind"],
             "type": spec["type"], "grants_cents": spec["cents"]}
            for pid, spec in PLAY_PRODUCTS.items()
        ],
        "note": (
            "Create these exact product ids in Play Console. Google charges the price "
            "set there; grants_cents is what this backend gives the member."
        ),
    }
