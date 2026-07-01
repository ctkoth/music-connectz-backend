from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import APP_KEY, FOCUS_CHOICES, DirectZDraft
from .serializers import DirectZDraftSerializer

# Defensive adult-gate: DirectZ is age-gated in the platform's child-safety
# model. Use the existing gate if present; otherwise require authentication.
# (Snapshot-at-activation is enforced by your existing pipeline — not recomputed
# here.) If your gate lives at a different import path, add it to the try list.
try:
    from apps.common.gates import AdultVerifiedOnly as _Gate  # type: ignore
except Exception:  # pragma: no cover
    try:
        from apps.common.tiergate import AdultVerifiedOnly as _Gate  # type: ignore
    except Exception:  # pragma: no cover
        _Gate = IsAuthenticated


class DirectZOverviewView(APIView):
    permission_classes = [_Gate]

    def get(self, request):
        return Response(
            {
                "app_key": APP_KEY,
                "name": "DirectZ",
                "tagline": "Dynamic Scene Creation · Audio-Visual Harmony · Creative Collaborations.",
                "age_gated": True,
                "focuses": [{"key": k, "label": v} for k, v in FOCUS_CHOICES],
                "recent": DirectZDraftSerializer(
                    DirectZDraft.objects.filter(user=request.user)[:10], many=True
                ).data,
            }
        )


class DirectZSubmitView(APIView):
    permission_classes = [_Gate]

    def post(self, request):
        serializer = DirectZDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
