from django.urls import path

from .views import (CatalogView, CharacterZView, MangaDetailView,
                    ArtView, MangaListView, MeetAttendView, MeetConsentView,
                    MeetsView, PagesView, RoomJoinView, RoomsView,
                    RoomSuperviseView, RoyaltyQuoteView)

urlpatterns = [
    path("catalog/", CatalogView.as_view(), name="mangaz-catalog"),
    path("characterz/", CharacterZView.as_view(), name="mangaz-characterz"),
    path("rooms/", RoomsView.as_view(), name="mangaz-rooms"),
    path("rooms/<int:pk>/join/", RoomJoinView.as_view(), name="mangaz-room-join"),
    path("rooms/<int:pk>/supervise/", RoomSuperviseView.as_view(),
         name="mangaz-room-supervise"),
    path("rooms/<int:pk>/meets/", MeetsView.as_view(), name="mangaz-meets"),
    path("meets/<int:pk>/attend/", MeetAttendView.as_view(), name="mangaz-meet-attend"),
    path("meets/<int:pk>/consent/", MeetConsentView.as_view(), name="mangaz-meet-consent"),
    path("works/", MangaListView.as_view(), name="mangaz-works"),
    path("works/<int:pk>/", MangaDetailView.as_view(), name="mangaz-work"),
    path("works/<int:pk>/pages/", PagesView.as_view(), name="mangaz-pages"),
    path("works/<int:pk>/art/", ArtView.as_view(), name="mangaz-art"),
    path("works/<int:pk>/royalty/", RoyaltyQuoteView.as_view(),
         name="mangaz-royalty"),
]
