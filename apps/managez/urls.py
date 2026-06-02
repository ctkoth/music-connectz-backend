"""ManageZ routes — /api/managez/...  ADULT-ONLY. Z-ified plural segments."""
from django.urls import path

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
]
