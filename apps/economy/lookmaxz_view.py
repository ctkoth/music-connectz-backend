"""LookmaxZ endpoints — who may ask lives here, what the model is told in lookmaxz.py.

Everything is gated on `verified_18plus` (Stripe Identity, never a birthday) for
the reason attractivenessz.py gives, and that includes the FREE parts: a shop
and a body panel framed as "looksmaxing" are the same body-image push for a
minor as the rating is, so the adult wall is around the whole screen rather than
the one button that costs something.
"""
import io

from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import imagelinks
from . import lookshare
from . import lookmaxz as lm
from .attractivenessz import too_big
from .attractivenessz_view import presentation_price
from .media import stable_media_url
from .models import LookmaxPrefs, charge_ai_usage

# Look Inspiration (Corey: "allow others or self img"). Scoring SOMEBODY ELSE'S looks stays out:
# self-only is a harm line, not a preference — a 1-10 on a stranger's face from their Instagram is
# how a looks app gets pointed at an ex or a classmate who never agreed to it. What a member wants
# from another person's photo is the LOOK, so this describes the changeable choices in it and how
# to get them, and judges nobody: no number, nothing about face, skin, teeth or body, no names.
INSPIRE_WHAT = ("Look Inspiration: a photo of a look you want — anyone's. The coach describes the haircut, "
                "facial hair, brows and styling in it, and how to get each. No scores, and nothing about the "
                "person themselves.")
INSPIRE_RULE = ("Rating someone else's looks isn't something LookZMaxZ does: the 1-10 reading is for photos of "
                "you. Inspiration describes a look, never the person wearing it.")

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
        # A photo can also come by its image address from the social apps (imagelinks.py).
        "link_note": ("Or paste the photo's image address from Facebook, Instagram, X, TikTok, Snapchat, "
                      "LinkedIn or Pinterest. It's read once and kept nowhere."),
        "link_hosts": sorted(set(imagelinks.IMAGE_HOSTS.values())),
        "page_hosts": sorted(set(imagelinks.PAGE_HOSTS)),
        "inspire": {"what": INSPIRE_WHAT, "rule": INSPIRE_RULE},
        "keep_note": lookshare.KEEP_NOTE,
    }


def _photo(request, state):
    """(fileobj, content_type, None) from an attached photo OR its image address, or (None, None, Response)."""
    photo = request.FILES.get("photo")
    if photo:
        if too_big(photo.size):
            return None, None, Response({**state, "detail": f"That photo is over the {state['max_mb']}MB "
                                                            "the coach can read in one go."},
                                        status=status.HTTP_400_BAD_REQUEST)
        return photo, photo.content_type, None
    url = str(request.data.get("photo_url") or "").strip()
    if not url:
        return None, None, Response({**state, "detail": "Attach a photo, or paste its image address."},
                                    status=status.HTTP_400_BAD_REQUEST)
    data, ctype, why = imagelinks.fetch(url, int(state["max_mb"] * 1024 * 1024))
    if why:
        return None, None, Response({**state, "detail": why, "link_refused": True},
                                    status=status.HTTP_400_BAD_REQUEST)
    return io.BytesIO(data), ctype, None


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
        # Fetched only now, after every free refusal: a link is a network trip.
        photo, ctype, refused = _photo(request, state)
        if refused:
            return refused

        payload, why = lm.rate_looks(photo, ctype, sectors)
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
            # Keep my photo (opt-in, like Keep this take): an ordinary upload of theirs, so a share
            # or post can show what was read. Never kept without the tick.
            kept = None
            if str(request.data.get("keep_photo", "")).lower() in ("1", "true", "yes", "on"):
                try:
                    photo.seek(0)
                    raw = photo.read()
                except Exception:
                    raw = b""
                kept, why = (lookshare.keep_photo(request.user, raw, ctype) if raw
                             else (None, "Not kept — the photo couldn't be read back. It was still read."))
                payload["kept_photo"] = ({"url": stable_media_url(kept, request), "id": kept.id} if kept
                                         else {"url": "", "note": why})
            # The one way a reading can leave this response: a server-signed snapshot the member
            # may choose to share (lookshare.py). Nothing else is stored unless they do.
            payload["share"] = {"reading": lookshare.sign(request.user, payload, kept), "note": lookshare.SHARE_NOTE,
                                "photo_kept": bool(kept)}
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


class LookInspireView(APIView):
    """POST a photo of a look (anyone's) — the changeable choices in it and how to get them. No scores."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        price, state = _state(request.user)
        if not price["verified"]:
            return Response({**state, "detail": LOCKED}, status=status.HTTP_403_FORBIDDEN)
        if not price["affordable"]:
            return Response({**state, "detail": f"Inspiration costs {price['cost_cents']} 🏷️ "
                                                "and today's free prompts are spent."},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        photo, ctype, refused = _photo(request, state)
        if refused:
            return refused
        look, why = lm.inspire_look(photo, ctype)
        if look is None:
            return Response({**state, "detail": f"Couldn't read that — {why}. Nothing was charged."},
                            status=status.HTTP_502_BAD_GATEWAY)
        if not look["parts"]:
            return Response({"parts": [], "unreadable": look.get("why") or "No look to describe in that photo.",
                             "charged": False, "rule": INSPIRE_RULE})
        charge_ai_usage(request.user, price["cost_cents"], note="LookZMaxZ look inspiration", count_daily=True)
        return Response({**look, "charged": True, "cost_cents": price["cost_cents"], "rule": INSPIRE_RULE,
                         "shop": {"tab": "lookmaxz", "sectors": ["face", "styling"]}})
