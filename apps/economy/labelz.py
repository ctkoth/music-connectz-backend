"""LabelZ — public label groups and e-signed artist agreements.

The frontend has called `GET/POST /api/labelz/` and `/api/labelz/contracts/`
since it shipped, and neither route existed anywhere in this backend: every
load of the tab 404'd. `management/commands/appz_usage.py` flagged this as
BROKEN rather than quiet for exactly that reason, and left the decision —
cut the tab, or build the route — for Corey's eyes. This is the route.

Nothing here moves a resource. Advances are display text, settled off the
platform, same as the frontend's own line says; there is no SpinaZ or money
transfer anywhere in this file, and `credit_outcomes.py` needs no new entry
because nothing is spent.

A label's roster (`member_count`) is the count of distinct artists with a
SIGNED contract to it — the only thing in this model that means "on the
label." Nothing else writes membership; there is no separate join request.

Contracts are 18+, matching the frontend's own "Contracts: adults only"
pill: offering one and signing one both check `is_minor`.
"""
import hashlib

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (TIER_DEBUG, TIER_PREMIUM, TIER_STATZ, Label, LabelContract,
                     is_minor, membership_for, notify)
from .sentencez import CONTRACT_PERSONAS, persona_keys

User = get_user_model()

ADULT_ONLY = "Contracts on LabelZ are 18+."


def can_create_label(user):
    """Premium/StatZ tier, or the Manager / A&R Scout persona — the same
    personas `sentencez.KINDS`'s legal kinds already gate on, so "who can
    draft a contract" means the same thing in both places."""
    if membership_for(user).tier in (TIER_PREMIUM, TIER_STATZ, TIER_DEBUG):
        return True
    return bool(persona_keys(user) & set(CONTRACT_PERSONAS))


def _label_dict(label, user, counts):
    return {
        "id": label.id, "name": label.name, "bio": label.bio,
        "owner": label.owner.username, "i_own": label.owner_id == user.id,
        "member_count": counts.get(label.id, 0),
    }


def _contract_dict(c):
    return {
        "id": c.id, "label": c.label.name, "label_id": c.label_id,
        "artist": c.artist.username, "title": c.title, "terms_text": c.terms_text,
        "advance_display": c.advance_display, "doc_sha256": c.doc_sha256,
        "owner_signed_name": c.owner_signed_name, "artist_signed_name": c.artist_signed_name,
        "status": c.status, "created_at": c.created_at.isoformat(),
    }


class LabelListCreateView(APIView):
    """GET every label, with who owns it and how many artists are signed —
    public, same as the frontend's own "Public label groups" line says.
    POST starts one: Premium/StatZ tier, or the Manager / A&R Scout persona."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        labels = list(Label.objects.select_related("owner").all()[:200])
        counts = {}
        # .order_by() clears LabelContract's default `-created_at` ordering —
        # left in place, Django pulls created_at into the SELECT to satisfy
        # it, which defeats DISTINCT on exactly the two columns asked for.
        for row in (LabelContract.objects.filter(
                label_id__in=[l.id for l in labels], status=LabelContract.STATUS_SIGNED)
                .order_by().values_list("label_id", "artist_id").distinct()):
            counts[row[0]] = counts.get(row[0], 0) + 1
        return Response({
            "labels": [_label_dict(l, request.user, counts) for l in labels],
            "can_create": can_create_label(request.user),
        })

    def post(self, request):
        if not can_create_label(request.user):
            return Response({"detail": "Creating a label needs Premium/StatZ tier or the "
                                       "Manager / A&R Scout persona."},
                            status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        name = str(d.get("name", "")).strip()[:120]
        if not name:
            return Response({"detail": "A label needs a name."}, status=status.HTTP_400_BAD_REQUEST)
        label = Label.objects.create(owner=request.user, name=name,
                                     bio=str(d.get("bio", "")).strip()[:4000])
        return Response(_label_dict(label, request.user, {}), status=status.HTTP_201_CREATED)


class LabelDetailView(APIView):
    """PATCH the name/bio of a label you own. Never the roster or a contract
    — a signed agreement's terms stay exactly what was signed."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        label = Label.objects.filter(pk=pk, owner=request.user).first()
        if not label:
            return Response({"detail": "Label not found."}, status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        fields = []
        if "name" in d:
            name = str(d["name"]).strip()[:120]
            if not name:
                return Response({"detail": "A label needs a name."}, status=status.HTTP_400_BAD_REQUEST)
            label.name = name
            fields.append("name")
        if "bio" in d:
            label.bio = str(d["bio"]).strip()[:4000]
            fields.append("bio")
        if fields:
            fields.append("updated_at")
            label.save(update_fields=fields)
        return Response(_label_dict(label, request.user, {}))


class LabelContractsView(APIView):
    """GET the contracts naming you, split by which side you're on — a
    label's roster is `as_owner`'s SIGNED rows, an artist's deals are
    `as_artist`. POST offers one: only from a label you own, to a real
    member, and you sign it by typing your name in the same request —
    the frontend's "Sign & offer" button is one action, not two."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        as_artist = LabelContract.objects.filter(artist=request.user).select_related("label", "artist")
        as_owner = LabelContract.objects.filter(label__owner=request.user).select_related("label", "artist")
        return Response({
            "as_artist": [_contract_dict(c) for c in as_artist],
            "as_owner": [_contract_dict(c) for c in as_owner],
        })

    def post(self, request):
        if is_minor(request.user):
            return Response({"detail": ADULT_ONLY}, status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        label = Label.objects.filter(pk=d.get("label_id"), owner=request.user).first()
        if not label:
            return Response({"detail": "Pick one of your own labels to offer from."},
                            status=status.HTTP_400_BAD_REQUEST)
        artist = User.objects.filter(username__iexact=str(d.get("artist", "")).strip()).first()
        if not artist:
            return Response({"detail": "That artist's username wasn't found."},
                            status=status.HTTP_404_NOT_FOUND)
        if artist.id == request.user.id:
            return Response({"detail": "You can't offer a contract to yourself."},
                            status=status.HTTP_400_BAD_REQUEST)
        terms_text = str(d.get("terms_text", "")).strip()
        if not terms_text:
            return Response({"detail": "The agreement needs its terms written out."},
                            status=status.HTTP_400_BAD_REQUEST)
        owner_signed_name = str(d.get("signed_name", "")).strip()[:200]
        if not owner_signed_name:
            return Response({"detail": "Type your full legal name to sign the offer."},
                            status=status.HTTP_400_BAD_REQUEST)
        title = str(d.get("title", "")).strip()[:200] or "Artist Agreement"
        advance_display = str(d.get("advance_display", "")).strip()[:80]

        doc = "\n".join([label.name, artist.username, title, terms_text, advance_display])
        contract = LabelContract.objects.create(
            label=label, artist=artist, title=title, terms_text=terms_text,
            advance_display=advance_display, owner_signed_name=owner_signed_name,
            doc_sha256=hashlib.sha256(doc.encode()).hexdigest(),
        )
        notify(artist, "labelz",
              f"📜 {label.name} offered you an agreement — {title}.", actor=request.user)
        return Response(_contract_dict(contract), status=status.HTTP_201_CREATED)


class LabelContractActionView(APIView):
    """POST .../sign/ or .../decline/ — the artist's own answer to an offer.
    Only the named artist may act, and only while it is still `offered`: a
    signed or declined contract is a closed record, not an editable one."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        if action not in ("sign", "decline"):
            return Response({"detail": "Unknown action."}, status=status.HTTP_404_NOT_FOUND)
        contract = LabelContract.objects.filter(pk=pk, artist=request.user).select_related("label").first()
        if not contract:
            return Response({"detail": "Contract not found."}, status=status.HTTP_404_NOT_FOUND)
        if contract.status != LabelContract.STATUS_OFFERED:
            return Response({"detail": f"That offer is already {contract.status}."},
                            status=status.HTTP_409_CONFLICT)
        if action == "decline":
            contract.status = LabelContract.STATUS_DECLINED
            contract.declined_at = timezone.now()
            contract.save(update_fields=["status", "declined_at"])
            notify(contract.label.owner, "labelz",
                  f"{request.user.username} declined the {contract.title} offer.", actor=request.user)
            return Response(_contract_dict(contract))

        if is_minor(request.user):
            return Response({"detail": ADULT_ONLY}, status=status.HTTP_403_FORBIDDEN)
        signed_name = str((request.data or {}).get("signed_name", "")).strip()[:200]
        if not signed_name:
            return Response({"detail": "Type your full legal name to sign."},
                            status=status.HTTP_400_BAD_REQUEST)
        contract.artist_signed_name = signed_name
        contract.status = LabelContract.STATUS_SIGNED
        contract.signed_at = timezone.now()
        contract.save(update_fields=["artist_signed_name", "status", "signed_at"])
        notify(contract.label.owner, "labelz",
              f"✅ {request.user.username} signed {contract.title}.", actor=request.user)
        return Response(_contract_dict(contract))
