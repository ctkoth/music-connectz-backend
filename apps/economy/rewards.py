"""Rewarded ads (AdMob SSV) and the OfferZ offerwall — real, fraud-resistant
server-to-server reward callbacks.

Both are config-gated (fail closed): each endpoint reports "not configured"
until its env vars are set, so nothing is payable until you wire in your
provider account and client SDK.

AdMob rewarded video (mobile / Capacitor app):
  The client shows the ad via the AdMob SDK, passing the member's id as
  `custom_data`. When the reward is earned, GOOGLE'S servers call
  `/api/economy/adz/admob-ssv/` with the reward + an ECDSA signature. We verify
  the signature against Google's public verifier keys before granting SpinAZ,
  and dedupe by `transaction_id`. (See AdmobConfigView for the ids the client
  needs.)

OfferZ offerwall:
  The provider server calls `/api/economy/offerz/callback/` when a member
  completes an offer. We verify an HMAC-SHA256 signature over
  `user_id:amount:txn_id` with OFFERZ_CALLBACK_SECRET, then grant SpinAZ,
  deduped by `txn_id`.
"""
import hashlib
import hmac
import time

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import RewardGrant, award_spinaz, wallet_for

User = get_user_model()

GOOGLE_VERIFIER_KEYS_URL = "https://www.gstatic.com/admob/reward/verifier-keys.json"
_keys_cache = {"at": 0, "keys": {}}


def _google_verifier_keys():
    """Fetch + cache Google's AdMob SSV public keys ({key_id: pem}). Cached 6h."""
    now = time.time()
    if _keys_cache["keys"] and now - _keys_cache["at"] < 6 * 3600:
        return _keys_cache["keys"]
    resp = requests.get(GOOGLE_VERIFIER_KEYS_URL, timeout=10)
    resp.raise_for_status()
    keys = {str(k["keyId"]): k["pem"] for k in resp.json().get("keys", [])}
    _keys_cache.update(at=now, keys=keys)
    return keys


def _verify_admob_signature(query_string, signature_b64, key_id):
    """Verify the AdMob SSV ECDSA-SHA256 signature. `query_string` is the raw
    query up to (not including) '&signature='. Returns True/False."""
    import base64

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils  # noqa: F401

    pem = _google_verifier_keys().get(str(key_id))
    if not pem:
        return False
    pub = serialization.load_pem_public_key(pem.encode())
    # base64url, may be missing padding.
    sig = base64.urlsafe_b64decode(signature_b64 + "=" * (-len(signature_b64) % 4))
    try:
        pub.verify(sig, query_string.encode(), ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False


class AdmobConfigView(APIView):
    """Public ad config the client SDK needs (app id + rewarded unit id) and
    whether rewarded ads are switched on server-side."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "enabled": bool(getattr(settings, "ADMOB_APP_ID", "") and getattr(settings, "ADMOB_REWARDED_UNIT_ID", "")),
            "app_id": getattr(settings, "ADMOB_APP_ID", ""),
            "rewarded_unit_id": getattr(settings, "ADMOB_REWARDED_UNIT_ID", ""),
        })


class AdmobSsvView(APIView):
    """GET — Google's rewarded-ad server-side-verification callback. Verifies the
    signature, then grants SpinAZ once per transaction_id."""

    permission_classes = [AllowAny]

    def get(self, request):
        if not getattr(settings, "ADMOB_APP_ID", ""):
            return Response({"detail": "AdMob is not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        raw = request.META.get("QUERY_STRING", "")
        params = request.GET
        signature = params.get("signature")
        key_id = params.get("key_id")
        if not signature or not key_id:
            return Response({"detail": "missing signature"}, status=status.HTTP_400_BAD_REQUEST)
        # Signed content is everything before '&signature='.
        idx = raw.find("&signature=")
        if idx == -1:
            return Response({"detail": "malformed"}, status=status.HTTP_400_BAD_REQUEST)
        signed = raw[:idx]
        try:
            ok = _verify_admob_signature(signed, signature, key_id)
        except requests.RequestException:
            return Response({"detail": "verifier unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not ok:
            return Response({"detail": "bad signature"}, status=status.HTTP_403_FORBIDDEN)

        uid = params.get("custom_data") or params.get("user_id")
        txn = params.get("transaction_id") or ""
        try:
            amount = max(0, int(float(params.get("reward_amount") or 0)))
        except (TypeError, ValueError):
            amount = 0
        user = User.objects.filter(pk=uid).first() if uid else None
        if not user or not txn or amount <= 0:
            # Return 200 so Google doesn't retry a permanently-bad callback.
            return Response({"ok": False})
        _, created = RewardGrant.objects.get_or_create(
            provider=RewardGrant.PROVIDER_ADMOB, txn_id=txn,
            defaults={"user": user, "spinaz": amount},
        )
        if created:
            award_spinaz(user, amount, note="Rewarded ad (AdMob)")
        return Response({"ok": True})


class OfferzView(APIView):
    """GET — the offerwall URL for this member (with their id as sub-id), and
    whether OfferZ is switched on."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        base = getattr(settings, "OFFERZ_URL", "")
        enabled = bool(base and getattr(settings, "OFFERZ_CALLBACK_SECRET", ""))
        url = ""
        if enabled:
            sep = "&" if "?" in base else "?"
            url = f"{base}{sep}user_id={request.user.id}"
        earned = sum(
            g.spinaz for g in RewardGrant.objects.filter(
                provider=RewardGrant.PROVIDER_OFFERZ, user=request.user
            ).only("spinaz")
        )
        return Response({"enabled": enabled, "url": url, "earned_spinaz": earned})


class OfferzCallbackView(APIView):
    """GET/POST — the offerwall provider's server callback. Verifies an
    HMAC-SHA256 signature over 'user_id:amount:txn_id' with
    OFFERZ_CALLBACK_SECRET, then grants SpinAZ once per txn_id."""

    permission_classes = [AllowAny]

    def get(self, request):
        return self._handle(request.GET)

    def post(self, request):
        return self._handle(request.data or request.POST)

    def _handle(self, data):
        secret = getattr(settings, "OFFERZ_CALLBACK_SECRET", "")
        if not secret:
            return Response({"detail": "OfferZ is not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        uid = str(data.get("user_id") or "")
        txn = str(data.get("txn_id") or data.get("trans_id") or "")
        sig = str(data.get("sig") or data.get("signature") or "")
        try:
            amount = max(0, int(float(data.get("amount") or 0)))
        except (TypeError, ValueError):
            amount = 0
        expected = hmac.new(secret.encode(), f"{uid}:{amount}:{txn}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig.lower()):
            return Response({"detail": "bad signature"}, status=status.HTTP_403_FORBIDDEN)
        user = User.objects.filter(pk=uid).first() if uid else None
        if not user or not txn or amount <= 0:
            return Response({"ok": False})
        _, created = RewardGrant.objects.get_or_create(
            provider=RewardGrant.PROVIDER_OFFERZ, txn_id=txn,
            defaults={"user": user, "spinaz": amount},
        )
        if created:
            award_spinaz(user, amount, note="OfferZ offerwall")
        return Response({"ok": True})
