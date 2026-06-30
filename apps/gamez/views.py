"""GameZ views.

Tier gating:
  • create/list/code games  -> Premium+ (PremiumOnly)
  • AI genre suggest        -> Premium+ (suggestions)
  • auto mode + Unreal route -> StatZ (StatzOnly)
Media routing:
  • non-owner OCC media -> Intelligence app
  • platform owner (staff) -> export
"""
import json
import re

import requests
from django.conf import settings
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.tiergate import PremiumOnly, StatzOnly, tier_of
from apps.skillz.urls import training_urlpatterns  # noqa: F401  (imported by urls)

from .genres import GENRES, heuristic_suggest
from .models import Game, OCCMedia
from .serializers import GameSerializer, OCCMediaSerializer


def is_platform_owner(user):
    return bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))


class GenresView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"genres": GENRES})


class GameListCreateView(generics.ListCreateAPIView):
    """Premium+ can build games in OCC. StatZ may enable auto_mode at creation."""
    permission_classes = [PremiumOnly]
    serializer_class = GameSerializer

    def get_queryset(self):
        return Game.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        tier = tier_of(self.request.user)
        wants_auto = bool(self.request.data.get("auto_mode"))
        auto = wants_auto and tier == "statz"      # auto is StatZ-only
        engine = self.request.data.get("engine", "web")
        if engine == "unreal" and tier != "statz":
            engine = "web"                          # Unreal route is StatZ-only
        serializer.save(owner=self.request.user, tier_at_creation=tier,
                        auto_mode=auto, engine=engine)


class GameDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [PremiumOnly]
    serializer_class = GameSerializer

    def get_queryset(self):
        return Game.objects.filter(owner=self.request.user)


class SuggestGenreView(APIView):
    """Premium+ : AI suggests genre/subgenre from a title/description (+optional code)."""
    permission_classes = [PremiumOnly]

    def post(self, request):
        title = request.data.get("title", "")
        desc = request.data.get("description", "")
        code = request.data.get("code", "")
        text = f"{title}. {desc}"
        key = settings.ANTHROPIC_API_KEY
        if key:
            try:
                catalog = "; ".join(f"{g}: {', '.join(subs)}" for g, subs in GENRES.items())
                prompt = (f"Classify this game into ONE genre and ONE subgenre from this catalog:\n{catalog}\n\n"
                          f"Game: {title}\nDescription: {desc}\n"
                          f"{('Code snippet: ' + code[:1500]) if code else ''}\n\n"
                          f"Reply ONLY JSON: {{\"genre\":\"\",\"subgenre\":\"\",\"confidence\":0-100}}.")
                r = requests.post("https://api.anthropic.com/v1/messages", timeout=30,
                                  headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                           "content-type": "application/json"},
                                  data=json.dumps({"model": "claude-sonnet-4-20250514", "max_tokens": 150,
                                                   "messages": [{"role": "user", "content": prompt}]}))
                txt = "".join(b.get("text", "") for b in r.json().get("content", []))
                m = re.search(r"\{.*\}", txt, re.S)
                if m:
                    data = json.loads(m.group(0))
                    if data.get("genre") in GENRES:
                        return Response({"genre": data["genre"], "subgenre": data.get("subgenre", ""),
                                         "confidence": data.get("confidence", 70), "basis": "ai"})
            except Exception:
                pass
        g, s = heuristic_suggest(text + " " + code)
        return Response({"genre": g, "subgenre": s, "confidence": 50, "basis": "heuristic"})


class AutoModeView(APIView):
    """StatZ only : turn on auto-build for a game and return an auto plan."""
    permission_classes = [StatzOnly]

    def post(self, request):
        try:
            game = Game.objects.get(id=request.data.get("game"), owner=request.user)
        except Game.DoesNotExist:
            return Response({"detail": "game not found"}, status=status.HTTP_404_NOT_FOUND)
        game.auto_mode = True
        game.status = "building"
        game.save(update_fields=["auto_mode", "status", "updated_at"])
        plan = [
            "Scaffold project structure in OCC",
            f"Generate core {game.genre or 'game'} loop ({game.subgenre or 'base'})",
            "Wire input + scoring + Music ConnectZ XP hooks (SkillZ)",
            "Generate placeholder art/audio via Intelligence",
            "Playtest pass + balance",
        ]
        return Response({"auto_mode": True, "game": GameSerializer(game).data, "plan": plan,
                         "note": "StatZ auto-build enabled. OCC will draft these steps."})


class UnrealRouteView(APIView):
    """StatZ only : switch a game to the Unreal Engine route + return a starter kit."""
    permission_classes = [StatzOnly]

    def post(self, request):
        try:
            game = Game.objects.get(id=request.data.get("game"), owner=request.user)
        except Game.DoesNotExist:
            return Response({"detail": "game not found"}, status=status.HTTP_404_NOT_FOUND)
        game.engine = "unreal"
        game.save(update_fields=["engine", "updated_at"])
        return Response({
            "engine": "unreal", "game": GameSerializer(game).data,
            "starter": {
                "project_name": re.sub(r"[^A-Za-z0-9]", "", game.title) or "MCZGame",
                "template": {"Rhythm": "Music", "Shooter": "FirstPerson", "RPG": "ThirdPerson"}.get(game.genre, "Blank"),
                "steps": [
                    "Install Unreal Engine 5 + enable the Python/Blueprint scripting plugins",
                    "Create project from the suggested template",
                    "Pull OCC-generated Blueprint scaffolding (download below)",
                    "Import Intelligence-generated assets",
                    "Package for your target platform",
                ],
                "occ_blueprint_export": f"/api/gamez/{game.id}/unreal-export/",
            },
            "note": "Unreal route enabled (StatZ). OCC drafts Blueprint scaffolding; heavy builds run in UE locally.",
        })


class RouteMediaView(APIView):
    """Route OCC-created media. Non-owner -> Intelligence app. Owner (staff) -> export."""
    permission_classes = [PremiumOnly]

    def post(self, request):
        kind = request.data.get("kind", "image")
        url = request.data.get("url", "")
        game_id = request.data.get("game")
        game = Game.objects.filter(id=game_id, owner=request.user).first() if game_id else None

        if is_platform_owner(request.user):
            media = OCCMedia.objects.create(owner=request.user, game=game, kind=kind, url=url,
                                            routed_to="export")
            if game:
                game.exported = True
                game.save(update_fields=["exported", "updated_at"])
            return Response({"routed_to": "export", "exportable": True,
                             "download_url": url or "", "media": OCCMediaSerializer(media).data})

        # Non-owner: media flows into the Intelligence app (no raw export).
        ref = f"intelligence:{kind}:{OCCMedia.objects.count() + 1}"
        media = OCCMedia.objects.create(owner=request.user, game=game, kind=kind, url=url,
                                        routed_to="intelligence", intelligence_ref=ref)
        return Response({"routed_to": "intelligence", "exportable": False,
                         "intelligence_ref": ref, "media": OCCMediaSerializer(media).data,
                         "note": "Saved to your Intelligence app. Export is available to the platform owner."})


class MyMediaView(generics.ListAPIView):
    permission_classes = [PremiumOnly]
    serializer_class = OCCMediaSerializer

    def get_queryset(self):
        return OCCMedia.objects.filter(owner=self.request.user)
