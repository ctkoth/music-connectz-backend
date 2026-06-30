"""ManageZ views — ADULT-ONLY (contracts, payouts, deals = money + legal)."""
from django.db.models import Sum
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.agegate import AdultOnly

from .models import (Booking, Client, Contract, Deal, Invoice, Payout,
                     RosterArtist, Task)
from .serializers import (BookingSerializer, ClientSerializer, ContractSerializer,
                          DealSerializer, InvoiceSerializer, PayoutSerializer,
                          RosterArtistSerializer, TaskSerializer)

PERMS = [AdultOnly]


class OwnedListCreate(generics.ListCreateAPIView):
    permission_classes = PERMS

    def get_queryset(self):
        return self.serializer_class.Meta.model.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class OwnedDetail(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = PERMS

    def get_queryset(self):
        return self.serializer_class.Meta.model.objects.filter(owner=self.request.user)


class RosterListCreateView(OwnedListCreate):   serializer_class = RosterArtistSerializer
class RosterDetailView(OwnedDetail):           serializer_class = RosterArtistSerializer
class ClientListCreateView(OwnedListCreate):   serializer_class = ClientSerializer
class ContractListCreateView(OwnedListCreate): serializer_class = ContractSerializer
class BookingListCreateView(OwnedListCreate):  serializer_class = BookingSerializer
class DealListCreateView(OwnedListCreate):     serializer_class = DealSerializer
class InvoiceListCreateView(OwnedListCreate):  serializer_class = InvoiceSerializer
class PayoutListCreateView(OwnedListCreate):   serializer_class = PayoutSerializer
class TaskListCreateView(OwnedListCreate):     serializer_class = TaskSerializer


class DashboardView(APIView):
    permission_classes = PERMS

    def get(self, request):
        u = request.user
        paid = Invoice.objects.filter(owner=u, status="paid").aggregate(s=Sum("amount"))["s"] or 0
        unpaid = Invoice.objects.filter(owner=u, status="unpaid").aggregate(s=Sum("amount"))["s"] or 0
        return Response({
            "app": "managez",
            "counts": {
                "roster": RosterArtist.objects.filter(owner=u).count(),
                "clientz": Client.objects.filter(owner=u).count(),
                "contractz": Contract.objects.filter(owner=u).count(),
                "open_dealz": Deal.objects.filter(owner=u, stage__in=["lead", "negotiating"]).count(),
                "open_taskz": Task.objects.filter(owner=u, done=False).count(),
            },
            "revenue": {"invoiced_paid": float(paid), "invoiced_unpaid": float(unpaid)},
        })


# ── LIVE MANAGER MARKETPLACE VIEWS (adult-gated; fail closed) ───────────────
from apps.common.agegate import is_adult  # noqa: E402
from .models import ManagementOffer, ManagementSeeking, ManagerOpening  # noqa: E402
from .serializers import (ManagementOfferSerializer, ManagementSeekingSerializer,  # noqa: E402
                          ManagerOpeningSerializer)


class _OwnedAdult(generics.ListCreateAPIView):
    permission_classes = [AdultOnly]
    def get_queryset(self): return self.serializer_class.Meta.model.objects.filter(owner=self.request.user)
    def perform_create(self, serializer):
        extra = {}
        if hasattr(self.serializer_class.Meta.model, "owner_adult_verified"):
            extra["owner_adult_verified"] = is_adult(self.request.user)
        serializer.save(owner=self.request.user, **extra)


class _OwnedAdultDetail(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [AdultOnly]
    def get_queryset(self): return self.serializer_class.Meta.model.objects.filter(owner=self.request.user)


class MySeekingView(_OwnedAdult):              serializer_class = ManagementSeekingSerializer
class MySeekingDetailView(_OwnedAdultDetail):  serializer_class = ManagementSeekingSerializer
class MyManagerOpeningView(_OwnedAdult):       serializer_class = ManagerOpeningSerializer
class MyManagerOpeningDetailView(_OwnedAdultDetail): serializer_class = ManagerOpeningSerializer
class MyOfferView(_OwnedAdult):                serializer_class = ManagementOfferSerializer


class BrowseSeekingView(generics.ListAPIView):
    """Managers browse adult artists seeking management. Adult-verified + open only."""
    permission_classes = [AdultOnly]
    serializer_class = ManagementSeekingSerializer
    def get_queryset(self):
        qs = ManagementSeeking.objects.filter(open=True, owner_adult_verified=True)
        g = self.request.query_params.get("genre")
        if g: qs = qs.filter(genre__iexact=g)
        return qs


class BrowseManagerOpeningsView(generics.ListAPIView):
    """Adult artists see which real managers are taking clients."""
    permission_classes = [AdultOnly]
    serializer_class = ManagerOpeningSerializer
    def get_queryset(self):
        return ManagerOpening.objects.filter(open=True, owner_adult_verified=True)
