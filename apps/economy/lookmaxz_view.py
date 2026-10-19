"""LookmaxZ endpoints — who may ask lives here, what the model is told in lookmaxz.py.

Everything is gated on `verified_18plus` (Stripe Identity, never a birthday) for
the reason attractivenessz.py gives, and that includes the FREE parts: a shop
and a body panel framed as "looksmaxing" are the same body-image push for a
minor as the rating is, so the adult wall is around the whole screen rather than
the one button that costs something.
"""
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import lookmaxz as lm
from .attractivenessz import too_big
from .attractivenessz_view import presentation_price
from .models import LookmaxPrefs, charge_ai_usage

LOCKED = ("LookmaxZ is 18+ and verified — not a self-reported birthday. "
          "Verify your identity in ProfileZ first.")
UPGRADE = {"tab": "membershipz", "target": "membershipz-plans", "label": "Upgrade to StatZ"}


def _catalogue():
    return {k: {"label": s["label"], "emoji": s["emoji"], "source": s["source"],
                "means": s["means"], "factors": s["factors"], "see_pro": s["see_pro"],
                "factor_info": {f: {"label": lab, **lm.FACTORS[(k, f)]} for f, lab in s["factors"].items()}}
            for k, s in lm.SECTORS.items()}


def _state(user):
    price = presentation_price(user)
    return price, {
        **{k: price[k] for k in ("cost_cents", "daily_prompts", "daily_prompts_left", "free_today",
                                 "affordable", "configured", "max_mb", "verified")},
        "requires_18plus_verification": True,
        "sectors": _catalogue(),
        "photo_sectors": lm.PHOTO_SECTORS,
        "default_sectors": lm.DEFAULT_SECTORS,
        "opt_in_sectors": lm.OPT_IN_SECTORS,
        "proportions_disclaimer": lm.PROPORTIONS_DISCLAIMER,
        "physique_disclaimer": lm.PHYSIQUE_DISCLAIMER,
        "proportions_rule": lm.PROPORTIONS_RULE,
        "caveat": lm.CAVEAT, "care_note": lm.CARE_NOTE,
        "scale": lm.SCALE, "rating_rule": lm.RATING_RULE,
        # Said before the upload: the price is for the RUN, not per sector, so asking for
        # more sectors costs nothing extra; the free parts are named so nobody thinks
        # they are paying for the shop.
        "cost_note": ("One photo, one price, however many sectors you ask for. A photo that "
                      "can't be read is never charged. Body, the shop and your marketplaces are free."),
        "affiliate_note": "These links carry no affiliate tag: we earn nothing if you buy.",
    }


class LookmaxZView(APIView):
    """GET gate, price, sectors, marketplaces and Body; POST a photo to read."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        price, state = _state(request.user)
        if not price["verified"]:
            return Response({**state, "locked": LOCKED})
        return Response({**state, **lm.markets_for(request.user),
                         "body": lm.body_sector(request.user)})

    def post(self, request):
        price, state = _state(request.user)
        if not price["verified"]:
            return Response({**state, "detail": LOCKED}, status=status.HTTP_403_FORBIDDEN)
        if str(request.data.get("confirm_self", "")).strip().lower() not in ("true", "1", "yes"):
            return Response({**state, "detail": "You must confirm this is a photo of yourself. "
                                                "Reading someone else's isn't what this does."},
                            status=status.HTTP_400_BAD_REQUEST)
        photo = request.FILES.get("photo")
        if not photo:
            return Response({**state, "detail": "Attach a photo."}, status=status.HTTP_400_BAD_REQUEST)
        if too_big(photo.size):
            return Response({**state, "detail": f"That photo is over the {state['max_mb']}MB "
                                                "the coach can read in one go."},
                            status=status.HTTP_400_BAD_REQUEST)
        raw = request.data.get("sectors") or ""
        wanted = [s for s in str(raw).replace(" ", "").split(",") if s in lm.PHOTO_SECTORS]
        sectors = [s for s in lm.PHOTO_SECTORS if s in wanted] or list(lm.DEFAULT_SECTORS)
        # An opt-in sector is only read when the member said, in so many words, that they
        # understand what it is. Asking for it without that is refused, not quietly dropped.
        for k in sectors:
            if lm.SECTORS[k].get("opt_in") and str(request.data.get(f"{k}_ack", "")).strip().lower() \
                    not in ("true", "1", "yes"):
                return Response({**state, "detail": f"{lm.SECTORS[k]['label']} needs you to confirm you "
                                                    "have read what it is and isn't — tick the box under it."},
                                status=status.HTTP_400_BAD_REQUEST)
        if not price["affordable"]:
            return Response({**state, "detail": f"A reading costs {price['cost_cents']} 🏷️ "
                                                "and today's free prompts are spent."},
                            status=status.HTTP_402_PAYMENT_REQUIRED)

        payload, why = lm.rate_looks(photo, photo.content_type, sectors)
        if payload is None:
            return Response({**state, "detail": f"Couldn't read that — {why}."},
                            status=status.HTTP_502_BAD_GATEWAY)

        charged = False
        if not payload["unreadable"]:
            # Billed only now: an unreadable photo, or one that showed none of the
            # asked-for sectors, is never charged.
            charge_ai_usage(request.user, price["cost_cents"],
                            note="LookmaxZ presentation reading", count_daily=True)
            charged = True
        shop_info = lm.markets_for(request.user)
        markets = shop_info["markets"]
        body = lm.body_sector(request.user)
        payload["sectors"]["body"] = body
        payload["shop"] = {k: lm.shop_for_sector(k, markets, s["scores"])
                           for k, s in payload["sectors"].items()}
        payload.update({"charged": charged, "cost_cents": price["cost_cents"],
                        "markets": markets, "market_source": shop_info["source"],
                        "care_note": lm.CARE_NOTE,
                        "affiliate_note": state["affiliate_note"]})
        return Response(payload)


class LookmaxZShopView(APIView):
    """GET ?sector=skin — the whole shelf for a sector, free, no photo.

    A low score is not the only reason to look for a moisturiser, and a shop that
    opens only after a paid reading would put a price on browsing.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        price = presentation_price(request.user)
        if not price["verified"]:
            return Response({"detail": LOCKED}, status=status.HTTP_403_FORBIDDEN)
        sector = request.query_params.get("sector", "")
        sectors = [sector] if sector in lm.SECTORS else list(lm.SECTORS)
        info = lm.markets_for(request.user)
        return Response({"markets": info["markets"], "source": info["source"],
                         "shop": {k: lm.shop_for_sector(k, info["markets"]) for k in sectors},
                         "affiliate_note": "These links carry no affiliate tag: we earn nothing if you buy."})


class LookmaxZMarketsView(APIView):
    """GET your marketplaces; PUT {markets: [...]} to replace them (StatZ).

    The tier buys WHERE you shop, never whether: everyone has Amazon, eBay and
    Walmart, in that order. A PUT from anyone else is refused with the sentence
    and the way up, and nothing they had is touched.
    """
    permission_classes = [IsAuthenticated]

    def _body(self, user):
        info = lm.markets_for(user)
        return {**info, "defaults": lm.DEFAULT_MARKETS, "custom_max": lm.CUSTOM_MAX,
                "rule": ("A marketplace is a name and a search address starting https:// with "
                         "{q} where the search words go, e.g. https://shop.example.com/search?q={q}.")}

    def get(self, request):
        if not presentation_price(request.user)["verified"]:
            return Response({"detail": LOCKED}, status=status.HTTP_403_FORBIDDEN)
        return Response(self._body(request.user))

    def put(self, request):
        if not presentation_price(request.user)["verified"]:
            return Response({"detail": LOCKED}, status=status.HTTP_403_FORBIDDEN)
        if not lm._is_statz(request.user):
            return Response({**self._body(request.user), "upgrade": UPGRADE,
                             "detail": "Choosing your own marketplaces is StatZ. You still shop on "
                                       "Amazon, eBay and Walmart."},
                            status=status.HTTP_403_FORBIDDEN)
        cleaned, dropped = lm.clean_markets(request.data.get("markets"))
        LookmaxPrefs.objects.update_or_create(user=request.user, defaults={"markets": cleaned})
        note = (f"Saved {len(cleaned)}. {dropped} weren't kept — each needs a name and an https:// "
                "address with {q} once, and there is room for "
                f"{lm.CUSTOM_MAX}.") if dropped else f"Saved {len(cleaned)}."
        return Response({**self._body(request.user), "saved_note": note, "dropped": dropped})

    def delete(self, request):
        LookmaxPrefs.objects.filter(user=request.user).delete()
        return Response(self._body(request.user))
