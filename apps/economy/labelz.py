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

**AdvanceZ** (`LabelAdvance`) is a shared RECORD of an advance and what was recouped against it, on a signed
contract. The label writes a line, the artist confirms it, and only confirmed lines count; the balance is
confirmed advances minus confirmed recoups, and a recoup can't exceed what is outstanding. Nothing moves —
no money, no SpinaZ, no automatic cut of anybody's royalties: deducting from earnings is a payment decision
and a legal one, and is not made here. **TeemZ** (`LabelTeamMember`) is the roster: the owner invites adults
in a named role from a closed list, they accept; membership grants no access to contracts or advances.

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

import datetime as dt

from django.db.models import Sum

from .models import (TIER_DEBUG, TIER_PREMIUM, TIER_STATZ, Label, LabelAdvance, LabelContract,
                     LabelTeamMember, is_minor, membership_for, notify)
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


TEAM_ROLES = {"manager": "Manager", "a_and_r": "A&R", "producer": "Producer", "engineer": "Engineer",
              "marketing": "Marketing", "booking": "Booking"}
MAX_TEAM = 50
MAX_CENTS = 100_000_000


def _label_dict(label, user, counts, team=None):
    return {
        "id": label.id, "name": label.name, "bio": label.bio,
        "owner": label.owner.username, "i_own": label.owner_id == user.id,
        "member_count": counts.get(label.id, 0),
        "team": (team or {}).get(label.id, []),
    }


def _team_by_label(label_ids):
    """Accepted team members for many labels in ONE query — the public list shows them."""
    out = {}
    for m in LabelTeamMember.objects.filter(label_id__in=label_ids, status=LabelTeamMember.STATUS_ACCEPTED).select_related("user"):
        out.setdefault(m.label_id, []).append({"username": m.user.username, "role": m.role, "role_label": TEAM_ROLES.get(m.role, m.role)})
    return out


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
        team = _team_by_label([l.id for l in labels])
        return Response({
            "labels": [_label_dict(l, request.user, counts, team) for l in labels],
            "team_roles": [{"key": k, "label": v} for k, v in TEAM_ROLES.items()],
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


# ---------------------------------------------------------------- AdvanceZ

def _advance_state(contract):
    lines = list(contract.advance_lines.all())
    conf = [l for l in lines if l.confirmed_at]
    adv = sum(l.amount_cents for l in conf if l.kind == LabelAdvance.KIND_ADVANCE)
    rec = sum(l.amount_cents for l in conf if l.kind == LabelAdvance.KIND_RECOUP)
    return {
        "contract_id": contract.id, "label": contract.label.name, "artist": contract.artist.username,
        "advanced_cents": adv, "recouped_cents": rec, "outstanding_cents": adv - rec,
        "waiting_cents": sum(l.amount_cents for l in lines if not l.confirmed_at),
        "lines": [{"id": l.id, "kind": l.kind, "amount_cents": l.amount_cents, "on": l.on.isoformat(),
                   "note": l.note, "confirmed": bool(l.confirmed_at)} for l in lines],
        "note": "A shared record of an advance and what was recouped. Nothing is paid or taken from anyone's earnings "
                "here; the money is settled between the two of you, off the platform. Only lines the artist has "
                "confirmed count.",
    }


def _party_contract(user, pk):
    c = LabelContract.objects.filter(pk=pk).select_related("label", "artist", "label__owner").first()
    if not c or user.id not in (c.artist_id, c.label.owner_id):
        return None
    return c


class AdvanceView(APIView):
    """GET the record on a contract (owner or artist). POST a line (owner only, signed contracts only)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        c = _party_contract(request.user, pk)
        if not c:
            return Response({"detail": "Contract not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({**_advance_state(c), "i_own": c.label.owner_id == request.user.id})

    def post(self, request, pk):
        c = _party_contract(request.user, pk)
        if not c or c.label.owner_id != request.user.id:
            return Response({"detail": "Contract not found."}, status=status.HTTP_404_NOT_FOUND)
        if c.status != LabelContract.STATUS_SIGNED:
            return Response({"detail": "An advance is recorded on a signed contract."}, status=status.HTTP_409_CONFLICT)
        d = request.data or {}
        kind = d.get("kind")
        if kind not in (LabelAdvance.KIND_ADVANCE, LabelAdvance.KIND_RECOUP):
            return Response({"detail": "Say whether this is an advance or a recoup."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            cents = int(round(float(d.get("amount")) * 100))
        except (TypeError, ValueError):
            cents = 0
        if not 0 < cents <= MAX_CENTS:
            return Response({"detail": "Enter an amount above zero."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            day = dt.date.fromisoformat(str(d.get("on") or dt.date.today().isoformat()))
        except ValueError:
            return Response({"detail": "That date isn't valid."}, status=status.HTTP_400_BAD_REQUEST)
        if kind == LabelAdvance.KIND_RECOUP:
            owed = _advance_state(c)["outstanding_cents"]
            pending = sum(l.amount_cents for l in c.advance_lines.filter(kind=LabelAdvance.KIND_RECOUP, confirmed_at__isnull=True))
            if cents + pending > owed:
                return Response({"detail": "That is more than is outstanding on confirmed advances."}, status=status.HTTP_400_BAD_REQUEST)
        LabelAdvance.objects.create(contract=c, kind=kind, amount_cents=cents, on=day, note=str(d.get("note", "")).strip()[:160])
        notify(c.artist, "labelz", f"💵 {c.label.name} recorded a {kind} on {c.title} — confirm it if it is right.", actor=request.user)
        return Response({**_advance_state(c), "i_own": True}, status=status.HTTP_201_CREATED)


class AdvanceLineView(APIView):
    """POST .../confirm/ — the artist confirms a line. DELETE — the owner withdraws a line the artist hasn't confirmed."""
    permission_classes = [IsAuthenticated]

    def _line(self, request, pk):
        l = LabelAdvance.objects.filter(pk=pk).select_related("contract__label", "contract__artist").first()
        return l if l and request.user.id in (l.contract.artist_id, l.contract.label.owner_id) else None

    def post(self, request, pk):
        l = self._line(request, pk)
        if not l or l.contract.artist_id != request.user.id:
            return Response({"detail": "Line not found."}, status=status.HTTP_404_NOT_FOUND)
        if not l.confirmed_at:
            l.confirmed_at = timezone.now(); l.save(update_fields=["confirmed_at"])
            notify(l.contract.label.owner, "labelz", f"{request.user.username} confirmed a {l.kind} on {l.contract.title}.", actor=request.user)
        return Response({**_advance_state(l.contract), "i_own": False})

    def delete(self, request, pk):
        l = self._line(request, pk)
        if not l or l.contract.label.owner_id != request.user.id:
            return Response({"detail": "Line not found."}, status=status.HTTP_404_NOT_FOUND)
        if l.confirmed_at:
            return Response({"detail": "The artist has confirmed this line, so it stays. Record a correcting line instead."}, status=status.HTTP_409_CONFLICT)
        c = l.contract; l.delete()
        return Response({**_advance_state(c), "i_own": True})


# ---------------------------------------------------------------- TeemZ

def _team_row(m):
    return {"id": m.id, "label_id": m.label_id, "label": m.label.name, "username": m.user.username,
            "role": m.role, "role_label": TEAM_ROLES.get(m.role, m.role), "status": m.status}


class TeamView(APIView):
    """GET the roster of a label you own (all statuses). POST invites an adult member in a role from `TEAM_ROLES`."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        label = Label.objects.filter(pk=pk, owner=request.user).first()
        if not label:
            return Response({"detail": "Label not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"team": [_team_row(m) for m in label.team.select_related("user", "label")],
                         "roles": [{"key": k, "label": v} for k, v in TEAM_ROLES.items()]})

    def post(self, request, pk):
        label = Label.objects.filter(pk=pk, owner=request.user).first()
        if not label:
            return Response({"detail": "Label not found."}, status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        role = d.get("role")
        if role not in TEAM_ROLES:
            return Response({"detail": "Pick a role from the list."}, status=status.HTTP_400_BAD_REQUEST)
        who = User.objects.filter(username__iexact=str(d.get("username", "")).strip()).first()
        if not who:
            return Response({"detail": "That username wasn't found."}, status=status.HTTP_404_NOT_FOUND)
        if who.id == request.user.id:
            return Response({"detail": "You own this label already."}, status=status.HTTP_400_BAD_REQUEST)
        if is_minor(who) or is_minor(request.user):
            return Response({"detail": "Label teams are 18+."}, status=status.HTTP_403_FORBIDDEN)
        if label.team.count() >= MAX_TEAM:
            return Response({"detail": f"A label team holds up to {MAX_TEAM}."}, status=status.HTTP_400_BAD_REQUEST)
        m, made = LabelTeamMember.objects.get_or_create(label=label, user=who, defaults={"role": role})
        if not made:
            if m.status == LabelTeamMember.STATUS_INVITED:
                return Response({"detail": "They've been invited already."}, status=status.HTTP_409_CONFLICT)
            m.role, m.status = role, LabelTeamMember.STATUS_INVITED
            m.save(update_fields=["role", "status"])
        notify(who, "labelz", f"🤝 {label.name} invited you to its team as {TEAM_ROLES[role]}.", actor=request.user)
        return Response(_team_row(m), status=status.HTTP_201_CREATED)


class TeamMineView(APIView):
    """GET the invitations and teams you are on."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = LabelTeamMember.objects.filter(user=request.user).exclude(status=LabelTeamMember.STATUS_DECLINED).select_related("label", "user")
        return Response({"mine": [_team_row(m) for m in rows]})


class TeamActionView(APIView):
    """POST .../accept|decline/ (the invitee). DELETE — the owner removes someone, or you leave a team you are on."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        if action not in ("accept", "decline"):
            return Response({"detail": "Unknown action."}, status=status.HTTP_404_NOT_FOUND)
        m = LabelTeamMember.objects.filter(pk=pk, user=request.user, status=LabelTeamMember.STATUS_INVITED).select_related("label", "user").first()
        if not m:
            return Response({"detail": "Invitation not found."}, status=status.HTTP_404_NOT_FOUND)
        if action == "accept" and is_minor(request.user):
            return Response({"detail": "Label teams are 18+."}, status=status.HTTP_403_FORBIDDEN)
        m.status = LabelTeamMember.STATUS_ACCEPTED if action == "accept" else LabelTeamMember.STATUS_DECLINED
        m.save(update_fields=["status"])
        notify(m.label.owner, "labelz", f"{request.user.username} {action}ed the {TEAM_ROLES.get(m.role, m.role)} role on {m.label.name}.", actor=request.user)
        return Response(_team_row(m))

    def delete(self, request, pk):
        m = LabelTeamMember.objects.filter(pk=pk).select_related("label", "user").first()
        if not m or request.user.id not in (m.user_id, m.label.owner_id):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        m.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
