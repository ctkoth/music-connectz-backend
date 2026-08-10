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
    apply_post_rating,
    AttractivenessRating,
    adult_only_reason,
    is_minor,
    profile_is_minor,
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
    post_interaction_block,
    reward_for_rating,
    Post,
    blocked_user_ids,
    Block,
    wallet_for,
)
from .catalog import over_char_limit
from .gates import GATE_KEYS, clean_gates, failing_gate, member_metrics, refusal
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
        "gates": v.gates or {},
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
            gates=clean_gates(d.get("gates")),
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

        # All five ranges, evaluated exactly as search evaluates them, so what
        # a host advertises and what the door enforces cannot diverge.
        if venue.gates:
            me = profile_for(request.user)
            host_p = profile_for(venue.host)
            origin = ((host_p.lat, host_p.lng)
                      if (host_p.share_location and host_p.lat is not None) else (None, None))
            failed = failing_gate(member_metrics(me, origin), venue.gates)
            if failed:
                return Response(refusal(failed, venue.gates), status=status.HTTP_403_FORBIDDEN)

        # Legacy attractiveness gate — rated visitors below the bar are blocked.
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
        # Both ends of the transaction have to be adults. A minor must not rate
        # anyone on looks, and a minor must not BE rated — the second is the one
        # that matters most and the one a rater-only check would miss.
        for who in (request.user, target):
            reason = adult_only_reason(who)
            if reason:
                return Response({"detail": reason, "adult_only": True},
                                status=status.HTTP_403_FORBIDDEN)

        _, created = AttractivenessRating.objects.update_or_create(
            rater=request.user, target=target, defaults={"score": score}
        )
        earned = reward_for_rating(request.user, f"@{target.username}") if created else 0
        m = membership_for(target)
        return Response({
            "earned_energy": earned,
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
        "tagged": f.tagged.username if f.tagged_id else "",
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
        tagged = None
        tname = str(request.data.get("tagged", "")).strip()
        if tname:
            tagged = User.objects.filter(username=tname).first()
        f = Face.objects.create(owner=request.user, image=img, name=str(request.data.get("name", ""))[:80], tagged=tagged)
        if tagged and tagged.id != request.user.id:
            notify(tagged, "like", f"@{request.user.username} tagged you on FaceZ 🙂", actor=request.user, item_id=f"face:{f.id}")
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
        _, created = FaceRating.objects.update_or_create(rater=request.user, face=f, defaults={"score": score})
        earned = reward_for_rating(request.user, "FaceZ") if created else 0
        return Response({"id": f.id, "median": face_median(f), "count": f.ratings.count(),
                         "my_rating": score, "earned_energy": earned})


# ---- SubstanceZ stances.
#
# "Do you use this" is the wrong question — sometimes and often are different
# lives, and a member who is sober BY CHOICE is saying something a blank list
# cannot say. Stored as {key: stance}, which is what the search filter has
# always read; the UI was sending a bare list of keys, so `subs.get(k)` hit a
# list and answered AttributeError — a 500 on Social ConnectZ for anyone who
# had saved SubstanceZ at all.
STANCES = ("sometimes", "often")
# Selections made before frequency existed. Kept distinct rather than guessed
# into a frequency: we know they picked it, we do not know how often.
STANCE_LEGACY = "yes"
ACTIVE_STANCES = {"use", "sometimes", "often", STANCE_LEGACY}


def clean_substances(value):
    """Normalize whatever the client sent into {key: stance}.

    Accepts the current dict form and the legacy list form, so an older client
    keeps working and an already-saved list is repaired on the next write.
    """
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:40]:
            key = str(k)[:40]
            stance = str(v or "").lower()
            if not key:
                continue
            out[key] = stance if stance in STANCES else STANCE_LEGACY
        return out
    if isinstance(value, list):
        return {str(k)[:40]: STANCE_LEGACY for k in value[:40] if str(k)}
    return {}


# ---- Cross-user profiles ----
# Adult-only under Play's Families policy. Kept next to PROFILE_FIELDS so a new
# sensitive field is added one line above the list that decides who may set it.
ADULT_ONLY_PROFILE_FIELDS = ("attracted_to", "asexual")

PROFILE_FIELDS = ("display_name", "bio", "location", "gender", "birthday", "sign",
                  "nationalities", "regions", "substances", "sober",
                  "attracted_to", "asexual", "traits", "personas", "links",
                  "external_followers")


def _avatar_url(p, request):
    try:
        return request.build_absolute_uri(p.avatar.url) if p.avatar else None
    except ValueError:
        return None


def _periods_of(skill):
    """Every stint on a skill, as [(start, end_or_None)].

    Back-compat: the original shape was a single `start` and nothing else, so a
    skill with no `periods` is read as one still-open stint. Nobody's saved data
    changes meaning until they add an end date.
    """
    if not isinstance(skill, dict):
        return []
    periods = skill.get("periods")
    if isinstance(periods, list) and periods:
        out = []
        for pr in periods:
            if isinstance(pr, dict) and pr.get("start"):
                out.append((str(pr["start"]), str(pr.get("end") or "") or None))
        return out
    return [(str(skill["start"]), None)] if skill.get("start") else []


def _as_date(value):
    import datetime
    try:
        y, m, d = (int(x) for x in str(value).split("-"))
        return datetime.date(y, m, d)
    except (ValueError, TypeError):
        return None


def _years_and_days(a, b):
    """Exact whole calendar years from a to b, plus the leftover days.

    Not `(b - a).days / 365.2425` — that under-reports an exact anniversary,
    because nine calendar years can be 3287 days and 3287 / 365.2425 is 8.9995.
    Someone hitting nine years today would have read eight.
    """
    years = b.year - a.year - ((b.month, b.day) < (a.month, a.day))
    try:
        anniversary = a.replace(year=a.year + years)
    except ValueError:          # 29 Feb into a non-leap year
        anniversary = a.replace(year=a.year + years, day=28)
    return years, (b - anniversary).days


def _skill_years(skill):
    """Whole years actually served on a skill — the SUM of its stints.

    This used to be `today - start`, which is elapsed time, not experience. A
    member who played 1999-2013 and stopped was credited 26 years instead of
    14: a number nobody could have earned, printed next to their name.
    """
    import datetime
    today = datetime.date.today()
    years, days = 0, 0
    counted = False
    for start, end in _periods_of(skill):
        a = _as_date(start)
        if not a:
            continue
        b = _as_date(end) or today
        if b > today:
            b = today
        if b <= a:
            continue
        y, d = _years_and_days(a, b)
        years += y
        days += d
        counted = True
    if not counted:
        return None
    return years + days // 365


def skill_activity(skill):
    """(is_active, last_played) — 14 years still going is not 14 years that
    stopped in 2013, and a collaborator is choosing between those two."""
    periods = _periods_of(skill)
    if not periods:
        return False, None
    if any(end is None for _, end in periods):
        return True, None
    return False, max(end for _, end in periods if end)


def profile_skill_rate(p, pick=min):
    """The member's hourly skill rate in cents, across every dated skill.

    `min` by default: a price gate asks "can I afford this person", and the
    honest answer is their cheapest skill, not their dearest.
    """
    rates = []
    for persona in (p.personas or []):
        if not isinstance(persona, dict):
            continue
        for s in (persona.get("skills") or []):
            if isinstance(s, dict) and s.get("rate_cents"):
                try:
                    rates.append(int(s["rate_cents"]))
                except (TypeError, ValueError):
                    pass
    return pick(rates) if rates else None


def profile_max_experience(p):
    """A member's greatest skill experience in years — max over every skill's
    summed stints. None when nothing is dated."""
    best = None
    for persona in (p.personas or []):
        # A persona is either {"key", "name", "skills": [...]} or, from before
        # the skill picker existed, a bare key string. The string form carries
        # no dates and simply doesn't count — but calling .get() on it raised
        # AttributeError, and this runs inside _profile_card, so viewing ANY
        # member who had picked a PersonaZ answered 500.
        if not isinstance(persona, dict):
            continue
        for skill in (persona.get("skills") or []):
            yrs = _skill_years(skill)
            if yrs is not None and (best is None or yrs > best):
                best = yrs
    return best


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
        "experience_years": profile_max_experience(p),
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
        "verified_18plus": p.verified_18plus,
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
            {"id": c.id, "user": c.user.username, "body": c.body, "at": c.created_at.isoformat(),
             "edited_at": c.edited_at.isoformat() if c.edited_at else None, "edit_history": c.edit_history or []}
            for c in SocialComment.objects.filter(item_id=item).select_related("user")[:100]
        ]
        my_r = ItemRating.objects.filter(user=request.user, item_id=item).first()
        return {
            "item": item, "up": ups, "down": downs, "my": mine.value if mine else 0, "comments": comments,
            "rating": item_rating_median(item), "my_rating": my_r.score if my_r else None,
            "rating_count": ItemRating.objects.filter(item_id=item).count(),
            "my_rating_at": my_r.created_at.isoformat() if (my_r and my_r.created_at) else None,
            "my_rating_edited_at": my_r.edited_at.isoformat() if (my_r and my_r.edited_at) else None,
            "my_rating_history": (my_r.edit_history or []) if my_r else [],
        }

    def get(self, request):
        item = (request.query_params.get("item") or "").strip()
        if not item:
            return Response({"detail": "item required"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self._payload(item, request))

    def _rate_skills(self, item, rater, score):
        """A post rating is also a rating of every skill that made the post.

        Only posts: `battle:…`, `playlist:…` and `collab:…` items are rated as
        themselves and have no skill behind them to credit.
        """
        if not item.startswith("post:"):
            return []
        try:
            post = Post.objects.select_related("author").get(pk=int(item.split(":", 1)[1]))
        except (ValueError, Post.DoesNotExist):
            return []
        return apply_post_rating(rater, post, score)

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
            # Was hardcoded [:500], which silently cut a Premium member's 1,500
            # characters and refused a StatZ member the unlimited they paid for.
            body = str((request.data or {}).get("body", "")).strip()
            cap = over_char_limit(body, membership_for(request.user).tier)
            if cap:
                return Response(
                    {"detail": f"That comment is over your {cap:,}-character limit — upgrade in MembershipZ for more room.",
                     "char_limit": cap},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            comment_id = (request.data or {}).get("comment_id")
            if comment_id is not None:
                # Edit your own comment within the tier's edit window.
                from datetime import timedelta
                from django.utils import timezone
                from .catalog import edit_window_for
                c = SocialComment.objects.filter(pk=comment_id, user=request.user).first()
                if not c:
                    return Response({"detail": "comment not found"}, status=status.HTTP_404_NOT_FOUND)
                window = edit_window_for(membership_for(request.user).tier)
                if timezone.now() > c.created_at + timedelta(seconds=window):
                    return Response({"detail": "edit_window_passed", "window_seconds": window}, status=status.HTTP_403_FORBIDDEN)
                if not body:
                    return Response({"detail": "body required"}, status=status.HTTP_400_BAD_REQUEST)
                c.edit_history = (c.edit_history or []) + [{"body": c.body, "at": timezone.now().isoformat()}]
                c.body = body
                c.edited_at = timezone.now()
                c.save(update_fields=["body", "edit_history", "edited_at"])
                return Response(self._payload(item, request))
            if not body:
                return Response({"detail": "body required"}, status=status.HTTP_400_BAD_REQUEST)
            blocked = post_interaction_block(item, request.user, "comment")
            if blocked:
                return Response(blocked, status=status.HTTP_403_FORBIDDEN)
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
                blocked = post_interaction_block(item, request.user, "rate")
                if blocked:
                    return Response(blocked, status=status.HTTP_403_FORBIDDEN)
                existing = ItemRating.objects.filter(user=request.user, item_id=item).first()
                if existing is None:
                    ItemRating.objects.create(user=request.user, item_id=item, score=score)
                    reward_for_rating(request.user, item)
                    self._rate_skills(item, request.user, score)
                    self._notify_target(item, "rate", f"@{request.user.username} rated your post {score}/10 ⭐", request.user)
                else:
                    # Changing your rating is an edit — only within the tier's window.
                    from datetime import timedelta
                    from django.utils import timezone
                    from .catalog import edit_window_for
                    window = edit_window_for(membership_for(request.user).tier)
                    anchor = existing.created_at or existing.updated_at
                    if anchor and timezone.now() > anchor + timedelta(seconds=window):
                        return Response({"detail": "edit_window_passed", "window_seconds": window}, status=status.HTTP_403_FORBIDDEN)
                    if existing.score != score:
                        existing.edit_history = (existing.edit_history or []) + [{"score": existing.score, "at": timezone.now().isoformat()}]
                        existing.score = score
                        existing.edited_at = timezone.now()
                        existing.save(update_fields=["score", "edit_history", "edited_at"])
                        # Changing your mind has to move the skill ratings it
                        # fed too, or the two disagree from then on.
                        self._rate_skills(item, request.user, score)
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
        # The bio is covered by the tier character limit. Nothing checked it
        # before, so on Postgres a Premium member writing their full 1,500
        # characters into a varchar(500) took a DataError and got a 500.
        if "bio" in d:
            cap = over_char_limit(str(d["bio"] or ""), membership_for(request.user).tier)
            if cap:
                return Response(
                    {"detail": f"Your bio is over your {cap:,}-character limit — upgrade in MembershipZ for more room.",
                     "char_limit": cap},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        # Sexual orientation is the other adult-only surface. A minor is not
        # refused the whole profile save over it — that would lose everything
        # else they just typed — the two fields are simply dropped, and the
        # response says so rather than pretending they were stored.
        # Write first, judge after. The wall has to be evaluated against the
        # profile as it WILL be saved: judging the stored row let a member set a
        # teen birthday and an orientation in one request and keep both, because
        # at the top of that request their age was still unknown.
        for f in PROFILE_FIELDS:
            if f in d:
                setattr(p, f, clean_substances(d[f]) if f == "substances" else d[f])
        minor = profile_is_minor(p)
        blocked = [f for f in ADULT_ONLY_PROFILE_FIELDS if minor and f in d]
        if minor:
            # Clear anything set before the wall existed, or before a birthday
            # was filled in. Leaving it stored would mean the disclosure on the
            # Play form is still true for accounts we now say it isn't.
            p.attracted_to, p.asexual = [], False
        # Sober by choice is a claim, not the absence of one. It is mutually
        # exclusive with declaring use — holding both would be incoherent on a
        # filter somebody relies on to find people living the same way.
        if p.sober:
            p.substances = {}
        p.save()
        out = _profile_full(p, request)
        if blocked:
            out["not_saved"] = blocked
            out["not_saved_reason"] = adult_only_reason(request.user)
        return Response(out)


class ProfileAvatarView(APIView):
    """Upload the current user's profile picture (multipart 'avatar')."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    # A profile picture is displayed at 56–80px. Anything past a few MB is a
    # mistake or an abuse, whatever the member's upload tier allows elsewhere.
    MAX_MB = 8

    def post(self, request):
        f = request.FILES.get("avatar")
        if not f:
            return Response({"detail": "avatar file required"}, status=status.HTTP_400_BAD_REQUEST)

        content_type = (getattr(f, "content_type", "") or "").lower()
        if not content_type.startswith("image/"):
            return Response(
                {"detail": "That file isn't an image. Use a JPG, PNG, WebP or GIF."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if f.size > self.MAX_MB * 1024 * 1024:
            return Response(
                {"detail": f"That image is too big — keep a profile picture under {self.MAX_MB}MB."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        p = profile_for(request.user)
        p.avatar = f
        p.save(update_fields=["avatar", "updated_at"])
        return Response(_profile_full(p, request))

    def delete(self, request):
        """Remove the picture and fall back to the default PersonaZ art."""
        p = profile_for(request.user)
        if p.avatar:
            p.avatar.delete(save=False)
            p.avatar = None
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

        # Same wall, second door. This endpoint takes a `dimension` and quietly
        # reaches the same table — a check on the other view alone would have
        # been a lock on the front door with the back one open.
        if dimension != "overall":
            for who in (request.user, target):
                reason = adult_only_reason(who)
                if reason:
                    return Response({"detail": reason, "adult_only": True},
                                    status=status.HTTP_403_FORBIDDEN)

        model = OverallRating if dimension == "overall" else AttractivenessRating
        _, created = model.objects.update_or_create(rater=request.user, target=target, defaults={"score": score})
        earned = reward_for_rating(request.user, f"@{target.username}") if created else 0
        return Response({
            "earned_energy": earned,
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
        # Resolve the USER first. Profile rows are created lazily, so a member
        # who has never opened ProfileZ has none — and looking the profile up
        # directly 404'd them, which made them unopenable from the online list
        # even though the account is perfectly real.
        user = User.objects.filter(username__iexact=username).first()
        if not user:
            return Response({"detail": "profile not found"}, status=status.HTTP_404_NOT_FOUND)
        p = profile_for(user)
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
        sober_only = request.query_params.get("sober") in ("1", "true", "True")

        def num(key):
            try:
                return float(request.query_params.get(key))
            except (TypeError, ValueError):
                return None

        # Range gates. When a min/max is set, members outside it (or with no
        # value for that metric) are excluded — the range "gates exclusive".
        # All five ranges through one spec, so search and a gated post agree
        # about what "outside the range" means. Skill rating and skill price
        # were missing entirely.
        gates = clean_gates({
            "rating": [num("rating_min"), num("rating_max")],
            "price": [num("price_min"), num("price_max")],
            "attract": [num("attr_min"), num("attr_max")],
            "age": [num("age_min"), num("age_max")],
            "km": [None, num("max_km")],
        })
        exp_min, exp_max = num("exp_min"), num("exp_max")  # years-of-experience range

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
                # Rows saved by the old client hold a list, not a dict.
                subs = clean_substances(p.substances)
                if any(subs.get(k) in ACTIVE_STANCES for k in substances):
                    continue
            metrics = member_metrics(p, origin)
            if gates and failing_gate(metrics, gates):
                continue
            if exp_min is not None or exp_max is not None:
                exp = metrics.get("exp")
                if exp is None or (exp_min is not None and exp < exp_min) or (exp_max is not None and exp > exp_max):
                    continue
            # The distance GATE lives in the spec above; this is the number
            # shown on the card. Computed once in member_metrics either way.
            dist = metrics.get("km")
            card = _profile_card(p, request)
            card["distance_km"] = dist
            results.append(card)
        # Nearest first when a distance origin exists. Distance WINS over the
        # Sexy badge's boost on purpose: "who is near me" is a real need, and
        # being rated attractive is not a reason to bury someone closer.
        if origin[0] is not None:
            results.sort(key=lambda c: (c.get("distance_km") is None, c.get("distance_km") or 0))
        else:
            from .models import Badge
            boosted = set(Badge.objects.filter(key="sexy", visible=True)
                          .values_list("user__username", flat=True))
            results.sort(key=lambda c: c.get("username") not in boosted)
        return Response({"members": results[:100], "origin_shared": origin[0] is not None})
