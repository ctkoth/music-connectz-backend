"""Trial endpoints: see it, start it."""
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import trials


class TrialView(APIView):
    """GET the countdown; POST to start today's trial."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(trials.status(request.user))

    def post(self, request):
        tier = (request.data or {}).get("tier")
        trial, error = trials.start(request.user, tier)
        if not trial:
            # 409 rather than 402: the trial isn't a payment problem, it's a
            # "not right now" — usually because today's is already spent.
            return Response({"detail": error, **trials.status(request.user)},
                            status=http.HTTP_409_CONFLICT)
        return Response(trials.status(request.user), status=http.HTTP_201_CREATED)
