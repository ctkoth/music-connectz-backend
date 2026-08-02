from django.urls import path

from .views import (BattleDetailView, BattlesView, BetsView, CatalogView,
                    EntriesView, VotesView)

urlpatterns = [
    path("catalog/", CatalogView.as_view(), name="battlez-catalog"),
    path("battles/", BattlesView.as_view(), name="battlez-battles"),
    path("battles/<int:pk>/", BattleDetailView.as_view(), name="battlez-battle"),
    path("battles/<int:pk>/entries/", EntriesView.as_view(), name="battlez-entries"),
    path("battles/<int:pk>/bets/", BetsView.as_view(), name="battlez-bets"),
    path("battles/<int:pk>/votes/", VotesView.as_view(), name="battlez-votes"),
]
