"""GET/POST /api/economy/reach/ — your own "who can reach me" range gates."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .gates import clean_gates
from .models import profile_for


class ReachGatesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"gates": profile_for(request.user).contact_gates or {}})

    def post(self, request):
        p = profile_for(request.user)
        p.contact_gates = clean_gates((request.data or {}).get("gates"))
        p.save(update_fields=["contact_gates"])
        return Response({"gates": p.contact_gates})
