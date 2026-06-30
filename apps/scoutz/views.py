"""ScoutZ views — Premium AND adult-verified (both must pass)."""
from django.db.models import Count
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.agegate import AdultOnly
from apps.common.tiergate import PremiumOnly

from .models import Prospect, ScoutingReport, Task
from .serializers import ProspectSerializer, ScoutingReportSerializer, TaskSerializer

PERMS = [AdultOnly, PremiumOnly]   # DRF ANDs these — both required


class OwnedListCreate(generics.ListCreateAPIView):
    permission_classes = PERMS
    def get_queryset(self): return self.serializer_class.Meta.model.objects.filter(owner=self.request.user)
    def perform_create(self, serializer): serializer.save(owner=self.request.user)

class OwnedDetail(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = PERMS
    def get_queryset(self): return self.serializer_class.Meta.model.objects.filter(owner=self.request.user)

class ProspectListCreateView(OwnedListCreate): serializer_class = ProspectSerializer
class ProspectDetailView(OwnedDetail):         serializer_class = ProspectSerializer
class ReportListCreateView(OwnedListCreate):   serializer_class = ScoutingReportSerializer
class TaskListCreateView(OwnedListCreate):     serializer_class = TaskSerializer


class DashboardView(APIView):
    permission_classes = PERMS
    def get(self, request):
        u = request.user
        by_stage = dict(Prospect.objects.filter(owner=u).values_list("stage").annotate(n=Count("id")))
        return Response({"app": "scoutz", "by_stage": by_stage,
                         "prospectz": Prospect.objects.filter(owner=u).count(),
                         "reportz": ScoutingReport.objects.filter(owner=u).count()})


# ── LIVE A&R MARKETPLACE VIEWS (adult-gated both sides; fail closed) ─────────
from apps.common.agegate import is_adult  # noqa: E402
from apps.common.tiergate import PremiumOnly as _Premium  # noqa: E402
from .models import ScoutInterest, ScoutOpening, TalentListing  # noqa: E402
from .serializers import (ScoutInterestSerializer, ScoutOpeningSerializer,  # noqa: E402
                          TalentListingSerializer)


class _OwnedAdult(generics.ListCreateAPIView):
    """Owner-scoped CRUD for adults; snapshots adult-verified on create."""
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


# Artist side — manage your own discoverable listing
class MyTalentListingView(_OwnedAdult):       serializer_class = TalentListingSerializer
class MyTalentListingDetailView(_OwnedAdultDetail): serializer_class = TalentListingSerializer

# Scout side — manage your own openings + interests
class MyScoutOpeningView(_OwnedAdult):
    serializer_class = ScoutOpeningSerializer
    permission_classes = [AdultOnly, _Premium]
class MyScoutOpeningDetailView(_OwnedAdultDetail):
    serializer_class = ScoutOpeningSerializer
    permission_classes = [AdultOnly, _Premium]
class MyInterestView(_OwnedAdult):
    serializer_class = ScoutInterestSerializer
    permission_classes = [AdultOnly, _Premium]


class BrowseTalentView(generics.ListAPIView):
    """Scouts browse discoverable artists. ONLY adult-verified, open listings."""
    permission_classes = [AdultOnly, _Premium]
    serializer_class = TalentListingSerializer
    def get_queryset(self):
        qs = TalentListing.objects.filter(open=True, owner_adult_verified=True)
        g = self.request.query_params.get("genre")
        seek = self.request.query_params.get("looking_for")
        if g: qs = qs.filter(genre__iexact=g)
        if seek: qs = qs.filter(looking_for=seek)
        return qs


class BrowseOpeningsView(generics.ListAPIView):
    """Adult artists see what real A&R/scouts are actively looking for."""
    permission_classes = [AdultOnly]
    serializer_class = ScoutOpeningSerializer
    def get_queryset(self):
        return ScoutOpening.objects.filter(open=True, owner_adult_verified=True)
