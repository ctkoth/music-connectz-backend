"""CollabZ escrow deals — the trust primitive.

A paid collab no longer transfers money instantly (pay-and-pray). Instead each
payer's share is HELD by the deal until the payer approves release (or it
auto-releases after ESCROW_AUTO_RELEASE_DAYS so recipients aren't stuck), and is
refundable while a dispute is open. Using CollabZ is free; an optional refundable
SpinAZ good-faith stake deters flakes. Deals settle in real money OR SpinAZ.

All money moves run inside a single transaction with the wallets locked
(select_for_update), so a multi-party settlement can never half-apply.
"""
from datetime import timedelta

from django.conf import settings

from .gates import clean_gates, failing_gate, member_metrics, refusal
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    CollabDeal,
    Post,
    Transaction,
    Wallet,
    can_view_post,
    collab_settlement,
    membership_for,
    notify,
    wallet_for,
)
from .views import is_owner

User = get_user_model()


def _locked_wallet(user):
    """Wallet row locked FOR UPDATE (create first if missing, since you can't
    lock a row that doesn't exist yet)."""
    Wallet.objects.get_or_create(user=user)
    return Wallet.objects.select_for_update().get(user=user)


def deal_dict(deal, me=None):
    return {
        "id": deal.id,
        "title": deal.title,
        "currency": deal.currency,
        "status": deal.status,
        "stake_spinaz": deal.stake_spinaz,
        "gates": deal.gates or {},
        # Where it came from. A deal that can't point back at the post it grew
        # out of is a dead end in the direction people actually travel.
        "source_post": ({
            "id": deal.source_post_id,
            "title": deal.source_post.title,
            "author": deal.source_post.author.username,
            "open_in": "social:post",
            "url": f"/p/{deal.source_post_id}" if deal.source_post.visibility == "public" else "",
        } if deal.source_post_id and deal.source_post else None),
        "initiator": deal.initiator.username,
        "mine": bool(me and deal.initiator_id == me.id),
        "participants": deal.participants,
        "held_cents": deal.held_cents,
        "held_spinaz": deal.held_spinaz,
        "created_at": deal.created_at.isoformat(),
        "delivered_at": deal.delivered_at.isoformat() if deal.delivered_at else None,
        "auto_release_at": deal.auto_release_at.isoformat() if deal.auto_release_at else None,
        "i_am_participant": bool(me and any(p.get("username") == me.username for p in deal.participants)),
        "i_am_payer": bool(me and any(p.get("username") == me.username and int(p.get("pays_cents") or 0) > 0 for p in deal.participants)),
    }


def _entry_for(deal, username):
    return next((p for p in deal.participants if p.get("username") == username), None)


def maybe_auto_release(deal):
    """Lazily release a fully-funded deal whose auto-release window has passed
    and which isn't disputed — so recipients are never stuck waiting on an
    unresponsive payer. Safe to call on any read."""
    if deal.status not in (CollabDeal.STATUS_FUNDED, CollabDeal.STATUS_DELIVERED):
        return deal
    if not deal.auto_release_at or timezone.now() < deal.auto_release_at:
        return deal
    return release_deal(deal, note="auto-release (window elapsed)")


@transaction.atomic
def release_deal(deal, note="collab release"):
    """Pay each recipient their net share from escrow, keep the platform tax
    (whatever's left after payouts), and return every stake. Idempotent-ish:
    guarded on status."""
    deal = CollabDeal.objects.select_for_update().get(pk=deal.pk)
    if deal.status not in (CollabDeal.STATUS_FUNDED, CollabDeal.STATUS_DELIVERED):
        return deal
    paid_out = 0
    for entry in deal.participants:
        user = User.objects.filter(username=entry.get("username")).first()
        if not user:
            continue
        recv = int(entry.get("receives_cents") or 0)
        stake = int(entry.get("stake_paid") or 0)
        w = _locked_wallet(user)
        if deal.currency == CollabDeal.CURRENCY_MONEY:
            if recv:
                w.money_cents += recv
                paid_out += recv
                Transaction.objects.create(user=user, kind=Transaction.KIND_REWARD, amount_cents=recv, dev_tax_cents=0, note=f"CollabZ escrow: {deal.title}"[:200])
        else:
            if recv:
                w.spinaz += recv
        w.spinaz += stake  # good-faith stake returned
        w.save(update_fields=["money_cents", "spinaz", "updated_at"])
    # Platform keeps the residual held money as developer tax on the deal.
    if deal.currency == CollabDeal.CURRENCY_MONEY:
        platform_tax = max(0, deal.held_cents - paid_out)
        if platform_tax:
            Transaction.objects.create(user=deal.initiator, kind=Transaction.KIND_SPEND, amount_cents=0, dev_tax_cents=platform_tax, note=f"CollabZ platform fee: {deal.title}"[:200])
    deal.held_cents = 0
    deal.held_spinaz = 0
    deal.held_stake_spinaz = 0
    deal.status = CollabDeal.STATUS_RELEASED
    deal.auto_release_at = None
    deal.save(update_fields=["held_cents", "held_spinaz", "held_stake_spinaz", "status", "auto_release_at", "updated_at"])
    return deal


@transaction.atomic
def refund_deal(deal, new_status=CollabDeal.STATUS_REFUNDED):
    """Return every funded participant's held payment AND stake to their wallet.
    Used to cancel before delivery or to resolve a dispute for the payer."""
    deal = CollabDeal.objects.select_for_update().get(pk=deal.pk)
    if deal.status in (CollabDeal.STATUS_RELEASED, CollabDeal.STATUS_REFUNDED, CollabDeal.STATUS_CANCELLED):
        return deal
    for entry in deal.participants:
        if not entry.get("funded"):
            continue
        user = User.objects.filter(username=entry.get("username")).first()
        if not user:
            continue
        pays = int(entry.get("pays_cents") or 0)
        stake = int(entry.get("stake_paid") or 0)
        w = _locked_wallet(user)
        if deal.currency == CollabDeal.CURRENCY_MONEY:
            w.money_cents += pays
        else:
            w.spinaz += pays
        w.spinaz += stake
        w.save(update_fields=["money_cents", "spinaz", "updated_at"])
        entry["funded"] = False
    deal.held_cents = 0
    deal.held_spinaz = 0
    deal.held_stake_spinaz = 0
    deal.status = new_status
    deal.auto_release_at = None
    deal.save(update_fields=["held_cents", "held_spinaz", "held_stake_spinaz", "status", "auto_release_at", "participants", "updated_at"])
    return deal


class CollabDealsView(APIView):
    """GET my deals (as initiator or participant); POST creates a draft deal."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        me = request.user
        deals = CollabDeal.objects.filter(initiator=me)[:100]
        # Also include deals where I'm a participant (JSON scan, bounded).
        seen = {d.id for d in deals}
        extra = [
            d for d in CollabDeal.objects.exclude(id__in=seen).order_by("-created_at")[:300]
            if any(p.get("username") == me.username for p in d.participants)
        ][:100]
        out = [deal_dict(maybe_auto_release(d), me) for d in list(deals) + extra]
        return Response({"deals": out})

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()[:160]
        currency = str(d.get("currency", "money")).lower()

        # PostZ → CollabZ. A post is a showcase; this is the move from "I heard
        # it" to "let's make something". The post seeds the title and puts its
        # author in the room, so the handoff is one call rather than a form the
        # member has to retype from the thing they were just looking at.
        source_post = None
        if d.get("from_post"):
            source_post = Post.objects.select_related("author").filter(pk=d["from_post"]).first()
            if not source_post:
                return Response({"detail": "That post doesn't exist."},
                                status=status.HTTP_400_BAD_REQUEST)
            if not can_view_post(source_post, request.user):
                return Response({"detail": "You can't start a collab from a post you can't view."},
                                status=status.HTTP_403_FORBIDDEN)
            if not title:
                title = f"Collab on '{source_post.title}'"[:160]
        if currency not in (CollabDeal.CURRENCY_MONEY, CollabDeal.CURRENCY_SPINAZ):
            return Response({"detail": "currency must be money|spinaz"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            stake = max(0, int(d.get("stake_spinaz", settings.COLLAB_DEFAULT_STAKE_SPINAZ) or 0))
        except (TypeError, ValueError):
            stake = 0
        raw = list(d.get("participants") or [])
        # Seeded from a post: the author is in the room by definition, and the
        # initiator too — otherwise "start a collab on this" would refuse for
        # want of the two people it obviously means.
        if source_post:
            named = {str((x or {}).get("username", "")).lower() for x in raw}
            for who in (source_post.author.username, request.user.username):
                if who.lower() not in named:
                    raw.append({"username": who, "worth_cents": 0})
                    named.add(who.lower())
        # Resolve every participant to a real member — escrow needs real wallets.
        parts = []
        for p in raw:
            uname = str((p or {}).get("username", "")).strip()
            user = User.objects.filter(username__iexact=uname).first()
            if not user:
                return Response({"detail": f"unknown member '{uname}'"}, status=status.HTTP_400_BAD_REQUEST)
            try:
                worth = max(0, int(round(float((p or {}).get("worth_cents", 0)))))
            except (TypeError, ValueError):
                worth = 0
            parts.append({"username": user.username, "tier": membership_for(user).tier, "worth_cents": worth})
        if len(parts) < 2:
            return Response({"detail": "a deal needs at least 2 members"}, status=status.HTTP_400_BAD_REQUEST)
        if not any(p["username"] == request.user.username for p in parts):
            return Response({"detail": "you must be one of the collaborators"}, status=status.HTTP_400_BAD_REQUEST)

        settled = collab_settlement(parts, currency=currency)
        for entry in settled:
            entry["funded"] = False
            entry["stake_paid"] = 0
        deal = CollabDeal.objects.create(
            initiator=request.user, title=title, currency=currency,
            stake_spinaz=stake, participants=settled, status=CollabDeal.STATUS_DRAFT,
            gates=clean_gates(d.get("gates")), source_post=source_post,
        )
        if source_post and source_post.author_id != request.user.id:
            notify(source_post.author, "system",
                   f"@{request.user.username} started a CollabZ deal on '{source_post.title}' 🤝",
                   actor=request.user, item_id=f"post:{source_post.id}")
        return Response(deal_dict(deal, request.user), status=status.HTTP_201_CREATED)


class CollabDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        deal = CollabDeal.objects.filter(pk=pk).first()
        if not deal:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        deal = maybe_auto_release(deal)
        return Response(deal_dict(deal, request.user))


class CollabFundView(APIView):
    """The calling participant funds their share (+ optional stake) into escrow."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        with transaction.atomic():
            deal = CollabDeal.objects.select_for_update().filter(pk=pk).first()
            if not deal:
                return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
            if deal.status not in (CollabDeal.STATUS_DRAFT, CollabDeal.STATUS_FUNDED):
                return Response({"detail": f"can't fund a {deal.status} deal"}, status=status.HTTP_409_CONFLICT)
            entry = _entry_for(deal, request.user.username)
            if not entry:
                return Response({"detail": "you're not on this deal"}, status=status.HTTP_403_FORBIDDEN)
            if entry.get("funded"):
                return Response(deal_dict(deal, request.user))  # idempotent
            pays = int(entry.get("pays_cents") or 0)
            stake = int(deal.stake_spinaz or 0)
            w = _locked_wallet(request.user)
            if deal.currency == CollabDeal.CURRENCY_MONEY:
                if w.money_cents < pays:
                    return Response({"detail": "Not enough balance to fund your share.", "need_cents": pays}, status=status.HTTP_402_PAYMENT_REQUIRED)
                if w.spinaz < stake:
                    return Response({"detail": "Not enough SpinaZ 🍥 for the stake.", "need_spinaz": stake}, status=status.HTTP_402_PAYMENT_REQUIRED)
                w.money_cents -= pays
                w.spinaz -= stake
                deal.held_cents += pays
                if pays:
                    Transaction.objects.create(user=request.user, kind=Transaction.KIND_SPEND, amount_cents=-pays, dev_tax_cents=0, note=f"CollabZ escrow hold: {deal.title}"[:200])
            else:
                if w.spinaz < pays + stake:
                    return Response({"detail": "Not enough SpinaZ 🍥 to fund your share + stake.", "need_spinaz": pays + stake}, status=status.HTTP_402_PAYMENT_REQUIRED)
                w.spinaz -= (pays + stake)
                deal.held_spinaz += pays
            w.save(update_fields=["money_cents", "spinaz", "updated_at"])
            deal.held_stake_spinaz += stake
            entry["funded"] = True
            entry["stake_paid"] = stake
            if deal.all_funded():
                deal.status = CollabDeal.STATUS_FUNDED
                deal.auto_release_at = timezone.now() + timedelta(days=settings.ESCROW_AUTO_RELEASE_DAYS)
            deal.save(update_fields=["held_cents", "held_spinaz", "held_stake_spinaz", "participants", "status", "auto_release_at", "updated_at"])
            return Response(deal_dict(deal, request.user))


class CollabDeliverView(APIView):
    """A participant marks the work delivered (confirms the approval clock)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        deal = CollabDeal.objects.filter(pk=pk).first()
        if not deal:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        if not _entry_for(deal, request.user.username):
            return Response({"detail": "you're not on this deal"}, status=status.HTTP_403_FORBIDDEN)
        if deal.status != CollabDeal.STATUS_FUNDED:
            return Response({"detail": f"can't deliver a {deal.status} deal"}, status=status.HTTP_409_CONFLICT)
        deal.status = CollabDeal.STATUS_DELIVERED
        deal.delivered_at = timezone.now()
        deal.save(update_fields=["status", "delivered_at", "updated_at"])
        return Response(deal_dict(deal, request.user))


class CollabReleaseView(APIView):
    """Payer (or owner) approves → escrow releases to recipients, stakes returned."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        deal = CollabDeal.objects.filter(pk=pk).first()
        if not deal:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        entry = _entry_for(deal, request.user.username)
        is_payer = bool(entry and int(entry.get("pays_cents") or 0) > 0)
        if not (is_payer or is_owner(request.user)):
            return Response({"detail": "only a paying collaborator can release the funds"}, status=status.HTTP_403_FORBIDDEN)
        if deal.status not in (CollabDeal.STATUS_FUNDED, CollabDeal.STATUS_DELIVERED):
            return Response({"detail": f"can't release a {deal.status} deal"}, status=status.HTTP_409_CONFLICT)
        deal = release_deal(deal)
        return Response(deal_dict(deal, request.user))


class CollabDisputeView(APIView):
    """Any participant opens a dispute within the window — freezes auto-release."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        deal = CollabDeal.objects.filter(pk=pk).first()
        if not deal:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        if not _entry_for(deal, request.user.username):
            return Response({"detail": "you're not on this deal"}, status=status.HTTP_403_FORBIDDEN)
        if deal.status not in (CollabDeal.STATUS_FUNDED, CollabDeal.STATUS_DELIVERED):
            return Response({"detail": f"can't dispute a {deal.status} deal"}, status=status.HTTP_409_CONFLICT)
        deal.status = CollabDeal.STATUS_DISPUTED
        deal.auto_release_at = None
        deal.save(update_fields=["status", "auto_release_at", "updated_at"])
        return Response(deal_dict(deal, request.user))


class CollabRefundView(APIView):
    """Cancel-before-delivery by a payer, or owner-mediated dispute resolution →
    return held money + stakes to the payers."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        deal = CollabDeal.objects.filter(pk=pk).first()
        if not deal:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        entry = _entry_for(deal, request.user.username)
        is_payer = bool(entry and int(entry.get("pays_cents") or 0) > 0)
        owner = is_owner(request.user)
        if not (is_payer or owner):
            return Response({"detail": "only a paying collaborator or the platform can refund"}, status=status.HTTP_403_FORBIDDEN)
        # A payer can self-serve a refund only before delivery or during a dispute;
        # once delivered, resolution is owner-mediated.
        if not owner and deal.status == CollabDeal.STATUS_DELIVERED:
            return Response({"detail": "work is delivered — open a dispute; the platform will mediate"}, status=status.HTTP_409_CONFLICT)
        if deal.status not in (CollabDeal.STATUS_DRAFT, CollabDeal.STATUS_FUNDED, CollabDeal.STATUS_DELIVERED, CollabDeal.STATUS_DISPUTED):
            return Response({"detail": f"can't refund a {deal.status} deal"}, status=status.HTTP_409_CONFLICT)
        new_status = CollabDeal.STATUS_CANCELLED if deal.status in (CollabDeal.STATUS_DRAFT, CollabDeal.STATUS_FUNDED) and not deal.delivered_at else CollabDeal.STATUS_REFUNDED
        deal = refund_deal(deal, new_status=new_status)
        return Response(deal_dict(deal, request.user))


class PostCollabsView(APIView):
    """GET /api/economy/postz/<pk>/collabs/ — the deals this post started.

    The other direction of the same seam. A post card can say "3 collabs came
    from this"; this is how you open them, so the count is a door rather than a
    statistic.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        post = Post.objects.filter(pk=pk).first()
        if not post or not can_view_post(post, request.user):
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        deals = (CollabDeal.objects
                 .filter(source_post=post)
                 .select_related("initiator", "source_post", "source_post__author")
                 .order_by("-created_at")[:100])
        me = request.user
        # A draft deal is somebody's private working-out. Only the people in it
        # need to see it; everyone else sees the ones that actually happened.
        visible = [d for d in deals
                   if d.status != CollabDeal.STATUS_DRAFT
                   or d.initiator_id == me.id
                   or any(p.get("username") == me.username for p in d.participants)]
        return Response({
            "post": post.title,
            "post_id": post.id,
            "deals": [deal_dict(d, me) for d in visible],
        })
