"""Account self-service: export my data + delete my account.

App-store required when you offer login (Apple 5.1.1(v), Google account-deletion
policy) and satisfies GDPR/CCPA access + erasure requests.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Follow,
    ItemRating,
    Post,
    SocialComment,
    membership_for,
    profile_for,
    wallet_for,
)


class AccountExportView(APIView):
    """GET → a JSON export of everything this account holds."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        p = profile_for(u)
        w = wallet_for(u)
        m = membership_for(u)
        following = list(Follow.objects.filter(follower=u).values_list("following__username", flat=True))
        followers = list(Follow.objects.filter(following=u).values_list("follower__username", flat=True))
        return Response({
            "account": {"username": u.username, "email": u.email, "joined": u.date_joined.isoformat()},
            "membership": {"tier": m.tier, "lifetime": m.lifetime, "founding": m.founding},
            "wallet": {"money": w.money, "energy": w.energy, "spinaz": w.spinaz, "royalties": w.royalties},
            "profile": {
                "display_name": p.display_name, "bio": p.bio, "location": p.location,
                "gender": p.gender, "birthday": p.birthday, "sign": p.sign,
                "nationalities": p.nationalities, "traits": p.traits, "personas": p.personas,
                "links": p.links, "external_followers": p.external_followers,
            },
            "social": {"following": following, "followers": followers},
            "posts": list(Post.objects.filter(author=u).values("id", "title", "visibility", "created_at")),
            "ratings_given": list(ItemRating.objects.filter(user=u).values("item_id", "score")),
            "comments": list(SocialComment.objects.filter(user=u).values("item_id", "body", "created_at")),
        })


class AccountDeleteView(APIView):
    """POST {confirm: "DELETE"} → permanently delete the account + its data.

    Cascades wipe profile, wallet, membership, posts, follows, ratings, comments,
    notifications, etc. Requires the exact confirmation string to avoid accidents.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if str((request.data or {}).get("confirm", "")) != "DELETE":
            return Response({"detail": 'Send {"confirm": "DELETE"} to confirm.'}, status=status.HTTP_400_BAD_REQUEST)
        u = request.user
        username = u.username
        u.delete()  # FK cascades remove all owned rows
        return Response({"deleted": True, "username": username})
