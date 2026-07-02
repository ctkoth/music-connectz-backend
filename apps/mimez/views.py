from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import APP_KEY, KIND_CHOICES, MimeZSubmission
from .serializers import MimeZSubmissionSerializer


class MimeZOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "app_key": APP_KEY,
                "name": "MimeZ",
                "tagline": "Mime lipsyncs, selfies, and dance training.",
                "teen_safe": True,
                "kinds": [{"key": k, "label": v} for k, v in KIND_CHOICES],
                "recent": MimeZSubmissionSerializer(
                    MimeZSubmission.objects.filter(user=request.user)[:10], many=True
                ).data,
            }
        )


class MimeZSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MimeZSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
