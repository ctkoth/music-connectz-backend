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
