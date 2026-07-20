"""Cross-user VenueZ (host/join events) and RateZ attractiveness.

Money moves between real users' wallets with the developer tax enforced
server-side (via pay_between). Attractiveness is a community-aggregated median
that gates venues, mirroring the collab/battle filter.
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AttractivenessRating,
    Face,
    FaceRating,
    OverallRating,
    Profile,
    Reaction,
    ItemRating,
    item_rating_median,
    SocialComment,
    profile_for,
    Venue,
    VenueAttendance,
    attractiveness_median,
    overall_median,
    face_median,
    membership_for,
    pay_between,
    profile_age,
    haversine_km,
    Follow,
    follow_counts,
    relationship,
    energy_rate_per_hour,
    notify,
    Post,
    blocked_user_ids,
    Block,
    wallet_for,
)
from .serializers import WalletSerializer

User = get_user_model()
VALID_TYPES = {"party", "openmic", "theater", "show", "custom"}


def _venue_dict(v, request):
    return {
        "id": v.id,
        "title": v.title,
        "mode": v.mode,
        "vtype": v.vtype,
        "custom_name": v.custom_name,
        "host": v.host.username,
        "mine": v.host_id == request.user.id,
        "host_price_cents": v.host_price_cents,
        "visitor_pay_cents": v.visitor_pay_cents,
        "min_attract": v.min_attract,
        "attending": v.attendances.filter(visitor=request.user).exists(),
        "created_at": v.created_at,
    }


class VenuesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        venues = Venue.objects.select_related("host").all()[:200]
        return Response({"venues": [_venue_dict(v, request) for v in venues]})

    def post(self, request):
        d = request.data
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "title required"}, status=status.HTTP_400_BAD_REQUEST)
        mode = d.get("mode") if d.get("mode") in (Venue.MODE_COLLAB, Venue.MODE_PERF) else Venue.MODE_COLLAB
        vtype = d.get("vtype") if d.get("vtype") in VALID_TYPES else "party"

        def cents(key):
            try:
                return max(0, int(d.get(key) or 0))
            except (TypeError, ValueError):
                return 0

        v = Venue.objects.create(
            host=request.user, title=title[:120], mode=mode, vtype=vtype,
            custom_name=str(d.get("custom_name", ""))[:60],
            host_price_cents=cents("host_price_cents"),
            visitor_pay_cents=cents("visitor_pay_cents") if mode == Venue.MODE_COLLAB else 0,
            min_attract=min(10, max(0, cents("min_attract"))),
        )
        return Response({"venue": _venue_dict(v, request)}, status=status.HTTP_201_CREATED)


class VenueJoinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        venue = Venue.objects.select_related("host").filter(pk=pk).first()
        if not venue:
            return Response({"detail": "venue not found"}, status=status.HTTP_404_NOT_FOUND)
        if venue.host_id == request.user.id:
            return Response({"detail": "you can't attend your own venue"}, status=status.HTTP_400_BAD_REQUEST)

        # Scalable attractiveness gate — rated visitors below the bar are blocked.
        if venue.min_attract > 0:
            med = attractiveness_median(request.user)
            if med is not None and med < venue.min_attract:
                return Response(
                    {"detail": f"needs attractiveness {venue.min_attract}+, yours is {med}"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        vw = wallet_for(request.user)
        if vw.money_cents < venue.host_price_cents:
            return Response({"detail": "insufficient balance to attend"}, status=status.HTTP_402_PAYMENT_REQUIRED)

        with transaction.atomic():
            # Visitor pays the host (developer tax enforced).
            pay_between(request.user, venue.host, venue.host_price_cents, note=f"VenueZ: {venue.title} (attend)")
            earned_net = 0
            # Collaborative: host also pays the visitor their skill price, if the host can cover it.
            if venue.mode == Venue.MODE_COLLAB and venue.visitor_pay_cents > 0:
                hw = wallet_for(venue.host)
                if hw.money_cents >= venue.visitor_pay_cents:
                    _dev, earned_net = pay_between(venue.host, request.user, venue.visitor_pay_cents, note=f"VenueZ: {venue.title} (skill payout)")
            VenueAttendance.objects.update_or_create(
                venue=venue, visitor=request.user,
                defaults={"paid_cents": venue.host_price_cents, "earned_cents": earned_net},
            )

        return Response({
            "wallet": WalletSerializer(wallet_for(request.user)).data,
            "paid_cents": venue.host_price_cents,
            "earned_cents": earned_net,
        })


class AttractivenessView(APIView):
    """GET my attractiveness median + opt-in; POST toggles the opt-in."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        m = membership_for(request.user)
        return Response({
            "median": attractiveness_median(request.user),
            "count": AttractivenessRating.objects.filter(target=request.user).count(),
            "public": m.attractiveness_public,
        })

    def post(self, request):
        m = membership_for(request.user)
        m.attractiveness_public = bool(request.data.get("public", True))
        m.save(update_fields=["attractiveness_public", "updated_at"])
        return Response({"public": m.attractiveness_public})


class AttractivenessRateView(APIView):
    """Rate another user's attractiveness (1-10). Upserts one rating per rater."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        username = str(request.data.get("target_username", "")).strip()
        try:
            score = int(request.data.get("score"))
        except (TypeError, ValueError):
            return Response({"detail": "score (1-10) required"}, status=status.HTTP_400_BAD_REQUEST)
        if not (1 <= score <= 10):
            return Response({"detail": "score must be 1-10"}, status=status.HTTP_400_BAD_REQUEST)
        target = User.objects.filter(username=username).first()
        if not target:
            return Response({"detail": "unknown user"}, status=status.HTTP_404_NOT_FOUND)
        if target.id == request.user.id:
            return Response({"detail": "can't rate yourself"}, status=status.HTTP_400_BAD_REQUEST)

        AttractivenessRating.objects.update_or_create(
            rater=request.user, target=target, defaults={"score": score}
        )
        m = membership_for(target)
        return Response({
            "target": target.username,
            "median": attractiveness_median(target) if m.attractiveness_public else None,
            "public": m.attractiveness_public,
        })


# ---- FaceZ (community-rated faces) ----
def _face_dict(f, request):
    my = FaceRating.objects.filter(rater=request.user, face=f).values_list("score", flat=True).first()
    return {
        "id": f.id,
        "owner": f.owner.username,
        "mine": f.owner_id == request.user.id,
        "name": f.name,
        "url": request.build_absolute_uri(f.image.url) if f.image else None,
        "median": face_median(f),
        "count": f.ratings.count(),
        "my_rating": my,
    }


class FaceZView(APIView):
    """GET your faces + a feed of others' faces to rate; POST uploads a face."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        mine = [_face_dict(f, request) for f in request.user.faces.all()[:100]]
        feed = [
            _face_dict(f, request)
            for f in Face.objects.exclude(owner=request.user).select_related("owner").order_by("-created_at")[:60]
        ]
        return Response({"mine": mine, "feed": feed})

    def post(self, request):
        img = request.FILES.get("image")
        if not img:
            return Response({"detail": "image (multipart) required"}, status=status.HTTP_400_BAD_REQUEST)
        f = Face.objects.create(owner=request.user, image=img, name=str(request.data.get("name", ""))[:80])
        return Response({"face": _face_dict(f, request)}, status=status.HTTP_201_CREATED)


class FaceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        f = request.user.faces.filter(pk=pk).first()
        if not f:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        f.image.delete(save=False)
        f.delete()
        return Response({"deleted": pk})


class FaceRateView(APIView):
    """Rate someone else's face 1-10 (one per rater per face, upserted)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        f = Face.objects.filter(pk=pk).first()
        if not f:
            return Response({"detail": "face not found"}, status=status.HTTP_404_NOT_FOUND)
        if f.owner_id == request.user.id:
            return Response({"detail": "can't rate your own face"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            score = int(request.data.get("score"))
        except (TypeError, ValueError):
            return Response({"detail": "score (1-10) required"}, status=status.HTTP_400_BAD_REQUEST)
        if not (1 <= score <= 10):
            return Response({"detail": "score must be 1-10"}, status=status.HTTP_400_BAD_REQUEST)
        FaceRating.objects.update_or_create(rater=request.user, face=f, defaults={"score": score})
        return Response({"id": f.id, "median": face_median(f), "count": f.ratings.count(), "my_rating": score})


# ---- Cross-user profiles ----
PROFILE_FIELDS = ("display_name", "bio", "location", "gender", "birthday", "sign",
                  "nationalities", "regions", "substances", "sober",
                  "attracted_to", "asexual", "traits", "personas", "links",
                  "external_followers")


def _avatar_url(p, request):
    try:
        return request.build_absolute_uri(p.avatar.url) if p.avatar else None
    except ValueError:
        return None


def _profile_card(p, request=None):
    """Compact card for search results."""
    m = getattr(p.user, "membership", None)
    return {
        "username": p.user.username,
        "display_name": p.display_name or p.user.username,
        "avatar": _avatar_url(p, request) if request else None,
        "gender": p.gender,
        "sign": p.sign,
        "regions": p.regions,
        "nationalities": p.nationalities,
        "sober": p.sober,
        "attracted_to": p.attracted_to,
        "median": attractiveness_median(p.user),
        "attractiveness": attractiveness_median(p.user),
        "overall": overall_median(p.user),
        "age": profile_age(p),
        "shares_location": bool(p.share_location and p.lat is not None and p.lng is not None),
        "tier": m.tier if m else "free",
        "founding": bool(m and m.founding),
        "lifetime": bool(m and m.lifetime),
        **follow_counts(p.user),
    }


def _profile_full(p, request):
    card = _profile_card(p, request)
    card.update({
        "bio": p.bio, "location": p.location, "birthday": p.birthday,
        "substances": p.substances, "asexual": p.asexual, "traits": p.traits,
        "personas": p.personas, "links": p.links, "mine": p.user_id == request.user.id,
        "my_attractiveness": AttractivenessRating.objects.filter(rater=request.user, target=p.user).values_list("score", flat=True).first(),
        "my_overall": OverallRating.objects.filter(rater=request.user, target=p.user).values_list("score", flat=True).first(),
        "overall_count": OverallRating.objects.filter(target=p.user).count(),
        "relationship": relationship(request.user, p.user),
        "energy_per_hour": energy_rate_per_hour(p.user) if p.user_id == request.user.id else None,
    })
    return card


class SocialView(APIView):
    """Cross-user reactions + comments for any item.

    GET  /api/economy/social/?item=<id>            → {up, down, my, comments:[...]}
    POST /api/economy/social/react/  {item, value} → toggle like(+1)/dislike(-1)/clear(0)
    POST /api/economy/social/comment/ {item, body} → add a comment
    """

    permission_classes = [IsAuthenticated]

    def _payload(self, item, request):
        ups = Reaction.objects.filter(item_id=item, value=1).count()
        downs = Reaction.objects.filter(item_id=item, value=-1).count()
        mine = Reaction.objects.filter(item_id=item, user=request.user).first()
        comments = [
            {"id": c.id, "user": c.user.username, "body": c.body, "at": c.created_at.isoformat()}
            for c in SocialComment.objects.filter(item_id=item).select_related("user")[:100]
        ]
        my_rating = ItemRating.objects.filter(user=request.user, item_id=item).values_list("score", flat=True).first()
        return {
            "item": item, "up": ups, "down": downs, "my": mine.value if mine else 0, "comments": comments,
            "rating": item_rating_median(item), "my_rating": my_rating,
            "rating_count": ItemRating.objects.filter(item_id=item).count(),
        }

    def get(self, request):
        item = (request.query_params.get("item") or "").strip()
        if not item:
            return Response({"detail": "item required"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self._payload(item, request))

    def _notify_target(self, item, kind, text, actor):
        """If the item is a post, tell its author about the interaction."""
        if not item.startswith("post:"):
            return
        try:
            post = Post.objects.select_related("author").get(pk=int(item.split(":", 1)[1]))
        except (ValueError, Post.DoesNotExist):
            return
        notify(post.author, kind, text, actor=actor, item_id=item)

    def post(self, request, action=None):
        item = str((request.data or {}).get("item", "")).strip()[:160]
        if not item:
            return Response({"detail": "item required"}, status=status.HTTP_400_BAD_REQUEST)
        if action == "react":
            try:
                value = int((request.data or {}).get("value", 0))
            except (TypeError, ValueError):
                value = 0
            value = max(-1, min(1, value))
            if value == 0:
                Reaction.objects.filter(user=request.user, item_id=item).delete()
            else:
                Reaction.objects.update_or_create(user=request.user, item_id=item, defaults={"value": value})
                if value == 1:
                    self._notify_target(item, "like", f"@{request.user.username} liked your post 👍", request.user)
        elif action == "comment":
            body = str((request.data or {}).get("body", "")).strip()[:500]
            if not body:
                return Response({"detail": "body required"}, status=status.HTTP_400_BAD_REQUEST)
            SocialComment.objects.create(user=request.user, item_id=item, body=body)
            self._notify_target(item, "comment", f"@{request.user.username} commented on your post 💬", request.user)
        elif action == "rate":
            try:
                score = int((request.data or {}).get("score", 0))
            except (TypeError, ValueError):
                score = 0
            if score == 0:
                ItemRating.objects.filter(user=request.user, item_id=item).delete()
            elif 1 <= score <= 10:
                ItemRating.objects.update_or_create(user=request.user, item_id=item, defaults={"score": score})
                self._notify_target(item, "rate", f"@{request.user.username} rated your post {score}/10 ⭐", request.user)
            else:
                return Response({"detail": "score must be 1-10 (or 0 to clear)"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self._payload(item, request))


class ProfileView(APIView):
    """GET your profile; POST upserts it (public, searchable by others)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_profile_full(profile_for(request.user), request))

    def post(self, request):
        p = profile_for(request.user)
        d = request.data
        for f in PROFILE_FIELDS:
            if f in d:
                setattr(p, f, d[f])
        p.save()
        return Response(_profile_full(p, request))


class ProfileAvatarView(APIView):
    """Upload the current user's profile picture (multipart 'avatar')."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        f = request.FILES.get("avatar")
        if not f:
            return Response({"detail": "avatar file required"}, status=status.HTTP_400_BAD_REQUEST)
        p = profile_for(request.user)
        p.avatar = f
        p.save(update_fields=["avatar", "updated_at"])
        return Response(_profile_full(p, request))


class ProfileRateView(APIView):
    """Rate another member's profile picture: dimension = overall | attractiveness,
    score 1-10. Upserts one rating per rater/target/dimension."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        username = str(request.data.get("target_username", "")).strip()
        dimension = str(request.data.get("dimension", "overall")).strip().lower()
        if dimension not in ("overall", "attractiveness"):
            return Response({"detail": "dimension must be overall|attractiveness"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            score = int(request.data.get("score"))
        except (TypeError, ValueError):
            return Response({"detail": "score (1-10) required"}, status=status.HTTP_400_BAD_REQUEST)
        if not (1 <= score <= 10):
            return Response({"detail": "score must be 1-10"}, status=status.HTTP_400_BAD_REQUEST)
        target = User.objects.filter(username=username).first()
        if not target:
            return Response({"detail": "unknown user"}, status=status.HTTP_404_NOT_FOUND)
        if target.id == request.user.id:
            return Response({"detail": "can't rate yourself"}, status=status.HTTP_400_BAD_REQUEST)

        model = OverallRating if dimension == "overall" else AttractivenessRating
        model.objects.update_or_create(rater=request.user, target=target, defaults={"score": score})
        return Response({
            "target": target.username,
            "dimension": dimension,
            "overall": overall_median(target),
            "attractiveness": attractiveness_median(target),
        })


class FollowView(APIView):
    """POST {username, action: follow|unfollow} → updated counts + relationship.
    GET ?username= → that user's counts + your relationship to them."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        username = (request.query_params.get("username") or "").strip()
        target = User.objects.filter(username=username).first()
        if not target:
            return Response({"detail": "unknown user"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"username": target.username, **follow_counts(target), "relationship": relationship(request.user, target)})

    def post(self, request):
        username = str((request.data or {}).get("username", "")).strip()
        action = str((request.data or {}).get("action", "follow")).lower()
        target = User.objects.filter(username=username).first()
        if not target:
            return Response({"detail": "unknown user"}, status=status.HTTP_404_NOT_FOUND)
        if target.id == request.user.id:
            return Response({"detail": "can't follow yourself"}, status=status.HTTP_400_BAD_REQUEST)
        if action == "unfollow":
            Follow.objects.filter(follower=request.user, following=target).delete()
        else:
            if target.id in blocked_user_ids(request.user):
                return Response({"detail": "You've blocked this user (or they blocked you)."}, status=status.HTTP_403_FORBIDDEN)
            _, created = Follow.objects.get_or_create(follower=request.user, following=target)
            if created:
                mutual = Follow.objects.filter(follower=target, following=request.user).exists()
                notify(target, "follow",
                       f"@{request.user.username} {'is now your friend 🤝' if mutual else 'followed you'}",
                       actor=request.user, item_id=f"profile:{request.user.username}")
        return Response({"username": target.username, **follow_counts(target), "relationship": relationship(request.user, target)})


class ProfileLocationView(APIView):
    """Opt-in GPS location for in-person distance filtering.
    POST {share: bool, lat, lng}. Turning share off clears the coordinates."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        p = profile_for(request.user)
        share = bool(request.data.get("share", True))
        p.share_location = share
        if not share:
            p.lat = p.lng = None
        else:
            try:
                p.lat = float(request.data.get("lat"))
                p.lng = float(request.data.get("lng"))
            except (TypeError, ValueError):
                return Response({"detail": "lat and lng required when sharing"}, status=status.HTTP_400_BAD_REQUEST)
            if not (-90 <= p.lat <= 90 and -180 <= p.lng <= 180):
                return Response({"detail": "lat/lng out of range"}, status=status.HTTP_400_BAD_REQUEST)
        p.save(update_fields=["share_location", "lat", "lng", "updated_at"])
        return Response({"share_location": p.share_location, "has_location": p.lat is not None})


class MemberProfileView(APIView):
    """View any member's public profile by username."""

    permission_classes = [IsAuthenticated]

    def get(self, request, username):
        p = Profile.objects.filter(user__username=username).select_related("user").first()
        if not p:
            return Response({"detail": "profile not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_profile_full(p, request))


class MembersView(APIView):
    """Search members by multi-select metrics: regions, genders, signs, sober.

    OR within a metric, AND across metrics — mirrors the client filter.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        def multi(key):
            raw = request.query_params.get(key, "")
            return [x for x in raw.split(",") if x]

        regions = multi("regions")
        genders = multi("genders")
        signs = multi("signs")
        # SubstanceZ multi-select: substance keys the searcher wants sober-friendly.
        # A member passes if, on every selected substance, they are NOT active
        # ("use"/"sometimes"). Undeclared counts as sober-friendly.
        substances = multi("substances")
        active_stances = {"use", "sometimes"}
        sober_only = request.query_params.get("sober") in ("1", "true", "True")

        def num(key):
            try:
                return float(request.query_params.get(key))
            except (TypeError, ValueError):
                return None

        # Range gates. When a min/max is set, members outside it (or with no
        # value for that metric) are excluded — the range "gates exclusive".
        age_min, age_max = num("age_min"), num("age_max")
        attr_min, attr_max = num("attr_min"), num("attr_max")
        max_km = num("max_km")  # distance range: within N km of the searcher

        me = profile_for(request.user)
        origin = (me.lat, me.lng) if (me.share_location and me.lat is not None) else (None, None)

        results = []
        qs = Profile.objects.exclude(user=request.user).exclude(user_id__in=blocked_user_ids(request.user)).select_related("user")[:500]
        for p in qs:
            if regions and not (set(regions) & set(p.regions or [])):
                continue
            if genders and p.gender not in genders:
                continue
            if signs and p.sign not in signs:
                continue
            if sober_only and not p.sober:
                continue
            if substances:
                subs = p.substances or {}
                if any(subs.get(k) in active_stances for k in substances):
                    continue
            if age_min is not None or age_max is not None:
                age = profile_age(p)
                if age is None or (age_min is not None and age < age_min) or (age_max is not None and age > age_max):
                    continue
            if attr_min is not None or attr_max is not None:
                a = attractiveness_median(p.user)
                if a is None or (attr_min is not None and a < attr_min) or (attr_max is not None and a > attr_max):
                    continue
            dist = None
            if origin[0] is not None and p.share_location and p.lat is not None:
                dist = haversine_km(origin[0], origin[1], p.lat, p.lng)
                if max_km is not None and (dist is None or dist > max_km):
                    continue
            elif max_km is not None:
                # Distance filter requested but no shared location on one side → exclude.
                continue
            card = _profile_card(p, request)
            card["distance_km"] = dist
            results.append(card)
        # Nearest first when a distance origin exists.
        if origin[0] is not None:
            results.sort(key=lambda c: (c.get("distance_km") is None, c.get("distance_km") or 0))
        return Response({"members": results[:100], "origin_shared": origin[0] is not None})
