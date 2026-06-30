"""GameZ routes — /api/gamez/...

Build games in OCC (Premium+), auto mode + Unreal route (StatZ), AI genre
suggest, and OCC media routing (non-owner -> Intelligence, owner -> export).
Plus SkillZ training so game-building is gamified like SingZ/RapZ.
"""
from django.urls import path

from apps.skillz.urls import training_urlpatterns

from . import views

app_name = "gamez"

urlpatterns = [
    path("gamez/genres/", views.GenresView.as_view(), name="genres"),
    path("gamez/games/", views.GameListCreateView.as_view(), name="games"),
    path("gamez/games/<uuid:pk>/", views.GameDetailView.as_view(), name="game-detail"),
    path("gamez/suggest-genre/", views.SuggestGenreView.as_view(), name="suggest-genre"),
    path("gamez/auto-mode/", views.AutoModeView.as_view(), name="auto-mode"),
    path("gamez/unreal-route/", views.UnrealRouteView.as_view(), name="unreal-route"),
    path("gamez/route-media/", views.RouteMediaView.as_view(), name="route-media"),
    path("gamez/my-media/", views.MyMediaView.as_view(), name="my-media"),
] + training_urlpatterns("gamez")
