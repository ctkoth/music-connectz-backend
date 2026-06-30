"""ManageZ routes — /api/managez/...  ADULT-ONLY.

Back office (roster/contracts/payouts) + LIVE manager marketplace (real artists
seeking management ↔ real managers taking clients) + SkillZ training (gamified).
"""
from django.urls import path

from apps.skillz.urls import training_urlpatterns

from . import views

app_name = "managez"

urlpatterns = [
    path("managez/dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("managez/rosterz/", views.RosterListCreateView.as_view(), name="rosterz-list"),
    path("managez/rosterz/<uuid:pk>/", views.RosterDetailView.as_view(), name="rosterz-detail"),
    path("managez/clientz/", views.ClientListCreateView.as_view(), name="clientz-list"),
    path("managez/contractz/", views.ContractListCreateView.as_view(), name="contractz-list"),
    path("managez/bookingz/", views.BookingListCreateView.as_view(), name="bookingz-list"),
    path("managez/dealz/", views.DealListCreateView.as_view(), name="dealz-list"),
    path("managez/invoicez/", views.InvoiceListCreateView.as_view(), name="invoicez-list"),
    path("managez/payoutz/", views.PayoutListCreateView.as_view(), name="payoutz-list"),
    path("managez/taskz/", views.TaskListCreateView.as_view(), name="taskz-list"),

    # LIVE manager marketplace — artist side
    path("managez/my-seeking/", views.MySeekingView.as_view(), name="my-seeking"),
    path("managez/my-seeking/<uuid:pk>/", views.MySeekingDetailView.as_view(), name="my-seeking-detail"),
    path("managez/openingz/", views.BrowseManagerOpeningsView.as_view(), name="browse-openingz"),

    # LIVE manager marketplace — manager side
    path("managez/seekingz/", views.BrowseSeekingView.as_view(), name="browse-seekingz"),
    path("managez/my-openingz/", views.MyManagerOpeningView.as_view(), name="my-openingz"),
    path("managez/my-openingz/<uuid:pk>/", views.MyManagerOpeningDetailView.as_view(), name="my-openingz-detail"),
    path("managez/offerz/", views.MyOfferView.as_view(), name="offerz"),
] + training_urlpatterns("managez")
