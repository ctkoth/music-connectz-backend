from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import registry


class TabzView(APIView):
    """GET the whole tab + modal map. Public — it's navigation, not member data.

    The frontend renders tabs from this instead of hardcoding them, so a tab
    added here appears everywhere at once and its URL can't drift from its name.
    """

    permission_classes = [AllowAny]

    def get(self, _request):
        return Response(registry.payload())


class TabDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, _request, key):
        found = registry.find(key)
        if not found:
            return Response({"detail": "No such tab."}, status=404)
        return Response({"tab": found})


class TabzAuditView(APIView):
    """GET what the spec still owes: missing icons, duplicate URLs, open notes."""

    permission_classes = [AllowAny]

    def get(self, _request):
        return Response({"tabz": registry.audit(),
                         "occ": registry.audit(registry.OCC_TABS)})
