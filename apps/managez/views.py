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
