"""K-Oth's royalty on IntelligenceZ pieces used in CollabZ, BattleZ and DistributeZ.

A member attaches a piece to a deal, battle or release they are part of; the
share is frozen then (`IntelligenceUse.royalty_pct`), stated before they
confirm, and taken from THEIR earnings when that thing pays out:

  * a CollabZ release — from their payout, in the deal's currency;
  * a BattleZ settlement — from their winnings, in 🍥;
  * a DistributeZ royalty credit — from the credit, into the owner's royalties.

Nothing is ever taken from somebody who did not attach the piece, and nothing
is taken from a refund or a draw: a royalty is a share of earnings, and those
are not earnings. The owner using his own piece pays himself nothing.
"""
from decimal import Decimal

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (Battle, CollabDeal, CollabParticipant, IntelligenceUse, Release,
                     SentenceWork, Transaction, award_spinaz, wallet_for)

MAX_TOTAL_PCT = Decimal("50")
TARGETS = (IntelligenceUse.TARGET_COLLAB, IntelligenceUse.TARGET_BATTLE, IntelligenceUse.TARGET_RELEASE)
OPEN_DEAL = (CollabDeal.STATUS_DRAFT, CollabDeal.STATUS_FUNDED,
             CollabDeal.STATUS_DELIVERED, CollabDeal.STATUS_DISPUTED)
OPEN_BATTLE = (Battle.STATUS_PENDING, Battle.STATUS_OPEN)


def _owner():
    from .views import platform_owner
    return platform_owner()


def pct_for(user, target_kind, target_id):
    """The member's total share owed on this target, capped."""
    owner = _owner()
    if user is None or owner is None or owner.pk == user.pk:
        return Decimal("0")
    total = sum((u.royalty_pct for u in IntelligenceUse.objects.filter(
        user=user, target_kind=target_kind, target_id=target_id)), Decimal("0"))
    return min(total, MAX_TOTAL_PCT)


def cut_of(user, target_kind, target_id, amount):
    """(cut, pct) — the whole units owed out of `amount`, rounded down."""
    pct = pct_for(user, target_kind, target_id)
    if not amount or not pct:
        return 0, pct
    return int(Decimal(int(amount)) * pct / 100), pct


def record_paid(user, target_kind, target_id, cut, currency):
    """Spread a paid cut across the uses that earned it, by their shares."""
    uses = list(IntelligenceUse.objects.filter(user=user, target_kind=target_kind, target_id=target_id))
    total = sum((u.royalty_pct for u in uses), Decimal("0"))
    if not uses or not total:
        return
    left = cut
    for i, u in enumerate(uses):
        part = left if i == len(uses) - 1 else int(Decimal(cut) * u.royalty_pct / total)
        left -= part
        if currency == "money":
            u.paid_cents += part
        else:
            u.paid_spinaz += part
        u.save(update_fields=["paid_cents", "paid_spinaz"])


def pay_owner_money(cut, note):
    owner = _owner()
    if not owner or not cut:
        return
    w = type(wallet_for(owner)).objects.select_for_update().get(pk=wallet_for(owner).pk)
    w.money_cents += cut
    w.save(update_fields=["money_cents", "updated_at"])
    Transaction.objects.create(user=owner, kind=Transaction.KIND_INTELLIGENCE, amount_cents=cut,
                               dev_tax_cents=0, note=note[:200])


def pay_owner_spinaz(cut, note):
    owner = _owner()
    if owner and cut:
        award_spinaz(owner, cut, note[:200], app_key="intelligencez")


# ---- what a member may attach a piece to ---------------------------------------
def targets_for(user):
    deal_ids = set(CollabParticipant.objects.filter(user=user).values_list("deal_id", flat=True))
    deals = CollabDeal.objects.filter(status__in=OPEN_DEAL).filter(
        pk__in=deal_ids) | CollabDeal.objects.filter(status__in=OPEN_DEAL, initiator=user)
    battles = (Battle.objects.filter(status__in=OPEN_BATTLE, host=user)
               | Battle.objects.filter(status__in=OPEN_BATTLE, opponent=user)
               | Battle.objects.filter(status__in=OPEN_BATTLE, entries__user=user))
    releases = Release.objects.filter(user=user)
    return ([{"kind": "collab", "id": d.id, "title": d.title or f"Deal #{d.id}", "currency": d.currency}
             for d in deals.distinct().order_by("-id")[:50]]
            + [{"kind": "battle", "id": b.id, "title": b.title, "currency": "spinaz"}
               for b in battles.distinct().order_by("-id")[:50]]
            + [{"kind": "release", "id": r.id, "title": r.title or f"Release #{r.id}", "currency": "money"}
               for r in releases.order_by("-id")[:50]])


def eligible(user, kind, tid):
    return any(t["kind"] == kind and t["id"] == tid for t in targets_for(user))


def _source(user, kind, sid):
    if kind == IntelligenceUse.SOURCE_SENTENCE:
        return SentenceWork.objects.filter(pk=sid, user=user).first()
    return None


def _use_dict(u):
    return {"id": u.id, "source": u.source_kind, "source_id": u.source_id,
            "target_kind": u.target_kind, "target_id": u.target_id,
            "royalty_pct": float(u.royalty_pct), "paid_cents": u.paid_cents,
            "paid_spinaz": u.paid_spinaz, "locked": not _detachable(u)}


def _detachable(u):
    if u.paid_cents or u.paid_spinaz:
        return False
    if u.target_kind == IntelligenceUse.TARGET_COLLAB:
        return CollabDeal.objects.filter(pk=u.target_id, status__in=OPEN_DEAL).exists()
    if u.target_kind == IntelligenceUse.TARGET_BATTLE:
        return Battle.objects.filter(pk=u.target_id, status__in=OPEN_BATTLE).exists()
    return True


class IntelligenceTargetsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"targets": targets_for(request.user), "max_total_pct": float(MAX_TOTAL_PCT)})


class IntelligenceUsesView(APIView):
    """GET ?source=&source_id= — where a piece is used. POST — attach it."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = IntelligenceUse.objects.filter(user=request.user,
                                            source_kind=request.query_params.get("source", ""),
                                            source_id=int(request.query_params.get("source_id") or 0))
        return Response({"uses": [_use_dict(u) for u in qs]})

    @transaction.atomic
    def post(self, request):
        from .sentencez import royalty_pct
        d = request.data or {}
        source = str(d.get("source", ""))
        try:
            sid, tid = int(d.get("source_id")), int(d.get("target_id"))
        except (TypeError, ValueError):
            return Response({"detail": "source_id and target_id required"}, status=status.HTTP_400_BAD_REQUEST)
        kind = str(d.get("target_kind", ""))
        work = _source(request.user, source, sid)
        if not work:
            return Response({"detail": "That piece isn't yours."}, status=status.HTTP_404_NOT_FOUND)
        if kind not in TARGETS or not eligible(request.user, kind, tid):
            return Response({"detail": "You can only use it in an open deal or battle you're in, or a release of yours."},
                            status=status.HTTP_400_BAD_REQUEST)
        text = str(d.get("text", "")) or work.text
        pct = Decimal(str(royalty_pct(work.text, text)))
        use, _ = IntelligenceUse.objects.update_or_create(
            source_kind=source, source_id=sid, target_kind=kind, target_id=tid,
            defaults={"user": request.user, "text": text, "royalty_pct": pct})
        return Response({**_use_dict(use),
                         "total_pct": float(pct_for(request.user, kind, tid))}, status=status.HTTP_201_CREATED)


class IntelligenceUseDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        use = IntelligenceUse.objects.filter(pk=pk, user=request.user).first()
        if not use:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if not _detachable(use):
            return Response({"detail": "It has already paid out, so it stays attached."},
                            status=status.HTTP_409_CONFLICT)
        use.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
