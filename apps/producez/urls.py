"""producez — gamified SkillZ training app (no DAW features; those live in DawZ).

Routes come from the shared SkillZ engine: train/tracks, train/drills,
train/daily, train/progress, train/leaderboard, train/attempt.
"""
from apps.skillz.urls import training_urlpatterns

app_name = "producez"
urlpatterns = training_urlpatterns("producez")
