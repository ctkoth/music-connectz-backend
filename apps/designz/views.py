"""DesignZ views. Youth-safe (creative tool), so gated with YouthSafe.

Pattern to copy for the other creator apps:
  - one ListCreate + RetrieveUpdateDestroy per real resource, scoped to owner
  - a DashboardView aggregating counts
  - TabView for any sub-tab not yet fleshed out (still responds 200)
"""
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.agegate import YouthSafe

from .models import Asset, BrandKit, Comment, Palette, Project, Template, Version
from .serializers import (AssetSerializer, BrandKitSerializer, CommentSerializer,
                          PaletteSerializer, ProjectSerializer, TemplateSerializer,
                          VersionSerializer)

APP_KEY = "designz"
PERMS = [YouthSafe]


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


# ── Projects ────────────────────────────────────────────────────────────────
class ProjectListCreateView(OwnedListCreate):
    serializer_class = ProjectSerializer


class ProjectDetailView(OwnedDetail):
    serializer_class = ProjectSerializer


# ── Assets ──────────────────────────────────────────────────────────────────
class AssetListCreateView(OwnedListCreate):
    serializer_class = AssetSerializer

    def get_queryset(self):
        qs = Asset.objects.filter(owner=self.request.user)
        pid = self.request.query_params.get("project")
        return qs.filter(project_id=pid) if pid else qs


class AssetDetailView(OwnedDetail):
    serializer_class = AssetSerializer


# ── Templates (public library + your own) ────────────────────────────────────
class TemplateListCreateView(generics.ListCreateAPIView):
    serializer_class = TemplateSerializer
    permission_classes = PERMS

    def get_queryset(self):
        from django.db.models import Q
        return Template.objects.filter(Q(is_public=True) | Q(owner=self.request.user))

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


# ── Brand kits / palettes ─────────────────────────────────────────────────────
class BrandKitListCreateView(OwnedListCreate):
    serializer_class = BrandKitSerializer


class PaletteListCreateView(OwnedListCreate):
    serializer_class = PaletteSerializer


# ── Comments / versions (nested by ?project=) ─────────────────────────────────
class CommentListCreateView(generics.ListCreateAPIView):
    serializer_class = CommentSerializer
    permission_classes = PERMS

    def get_queryset(self):
        qs = Comment.objects.filter(project__owner=self.request.user)
        pid = self.request.query_params.get("project")
        return qs.filter(project_id=pid) if pid else qs

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class VersionListCreateView(generics.ListCreateAPIView):
    serializer_class = VersionSerializer
    permission_classes = PERMS

    def get_queryset(self):
        qs = Version.objects.filter(project__owner=self.request.user)
        pid = self.request.query_params.get("project")
        return qs.filter(project_id=pid) if pid else qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


# ── Dashboard (real aggregate) ────────────────────────────────────────────────
class DashboardView(APIView):
    permission_classes = PERMS

    def get(self, request):
        u = request.user
        recent = Project.objects.filter(owner=u)[:5]
        return Response({
            "app": APP_KEY,
            "counts": {
                "projectz": Project.objects.filter(owner=u).count(),
                "assetz": Asset.objects.filter(owner=u).count(),
                "brandkitz": BrandKit.objects.filter(owner=u).count(),
                "palettez": Palette.objects.filter(owner=u).count(),
            },
            "recent_projectz": ProjectSerializer(recent, many=True).data,
        })


# ── Stub for sub-tabs not yet built (still live) ──────────────────────────────
class TabView(APIView):
    permission_classes = PERMS
    tab = "tab"

    def get(self, request):
        return Response({"app": APP_KEY, "tab": self.tab, "status": "scaffold", "items": []})


# ── Challenge submission: edit in ImageZ OR import anything → score it ───────
from rest_framework import status as _status  # noqa: E402
from apps.skillz.models import Drill  # noqa: E402
from apps.skillz.scoring import record_attempt  # noqa: E402
from .models import ChallengeSubmission  # noqa: E402
from .scoring import score_submission  # noqa: E402


class SubmitChallengeView(APIView):
    """POST a challenge answer made in ImageZ or imported from anywhere.

    Body: { drill, source: "imagez"|"import"|"asset", artifact_url,
            asset_id?, notes?, score? }
    - Records a DesignZ ChallengeSubmission (the artifact),
    - Scores it (client score > AI rating > baseline credit),
    - Funnels through SkillZ so it earns XP / badges / leaderboard like a drill.
    """
    permission_classes = PERMS

    def post(self, request):
        drill_id = request.data.get("drill")
        try:
            drill = Drill.objects.get(id=drill_id, track__app_key=APP_KEY)
        except Drill.DoesNotExist:
            return Response({"detail": "challenge not found"}, status=_status.HTTP_404_NOT_FOUND)

        source = request.data.get("source", "imagez")
        artifact_url = request.data.get("artifact_url", "")
        notes = request.data.get("notes", "")
        asset = None
        asset_id = request.data.get("asset_id")
        if asset_id:
            asset = Asset.objects.filter(id=asset_id, owner=request.user).first()
            if asset and not artifact_url:
                artifact_url = asset.file_url

        score, basis = score_submission(drill.prompt or drill.title, artifact_url,
                                        request.data.get("score"))
        result = record_attempt(request.user, drill, score)

        sub = ChallengeSubmission.objects.create(
            owner=request.user, drill_id=drill.id, track_key=drill.track.key,
            source=source, artifact_url=artifact_url, asset=asset, notes=notes,
            score=score, passed=result["passed"], xp_earned=result["xp_earned"])

        return Response({
            "submission_id": str(sub.id),
            "score": score, "score_basis": basis,
            **result,
        }, status=_status.HTTP_201_CREATED)


class SubmissionListView(generics.ListAPIView):
    permission_classes = PERMS
    def get(self, request, *args, **kwargs):
        rows = ChallengeSubmission.objects.filter(owner=request.user)
        drill = request.query_params.get("drill")
        if drill:
            rows = rows.filter(drill_id=drill)
        return Response([{
            "id": str(s.id), "drill": str(s.drill_id), "track_key": s.track_key,
            "source": s.source, "artifact_url": s.artifact_url, "notes": s.notes,
            "score": s.score, "passed": s.passed, "xp_earned": s.xp_earned,
            "created_at": s.created_at,
        } for s in rows])
