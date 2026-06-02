"""DawZ — list proposals + one-vote-per-user build voting. Youth-safe."""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.agegate import YouthSafe

from .models import DawProposal, DawVote
from .serializers import DawProposalSerializer

PERMS = [YouthSafe]


def _voted_daw_id(user):
    v = DawVote.objects.filter(user=user).first()
    return v.daw_id if v else None


class ProposalsView(APIView):
    permission_classes = PERMS

    def get(self, request):
        proposals = DawProposal.objects.all()
        ser = DawProposalSerializer(proposals, many=True,
                                    context={"voted_daw_id": _voted_daw_id(request.user)})
        return Response({"daws": ser.data, "your_vote": _voted_daw_id(request.user)})


class VoteView(APIView):
    permission_classes = PERMS

    def get(self, request):
        return Response({"your_vote": _voted_daw_id(request.user)})

    def post(self, request):
        key = request.data.get("daw")
        try:
            daw = DawProposal.objects.get(key=key)
        except DawProposal.DoesNotExist:
            return Response({"detail": "unknown daw"}, status=status.HTTP_404_NOT_FOUND)
        # OneToOne(user) => this moves the user's single vote (no double-voting).
        DawVote.objects.update_or_create(user=request.user, defaults={"daw": daw})
        return Response({"your_vote": daw.id, "daw": daw.key,
                         "vote_count": daw.votes.count()}, status=status.HTTP_200_OK)

    def delete(self, request):
        DawVote.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
