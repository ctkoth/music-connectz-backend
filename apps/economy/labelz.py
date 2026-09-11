"""LabelZ — public label groups, and the agreements they offer artists.

Like GroupZ, this screen has been in the nav calling a backend that was never
written. Its failure was the worse of the two: `LabelZ.jsx` returns its
spinner before the line that would have printed the error, so the tab was a
spinner forever with nothing said at all.

Three things this module refuses to do, and each is the reason the feature is
safe to ship rather than a decision left for later:

**The terms are frozen at the offer.** `doc_sha256` is taken over the document
the label signed, and the artist signs that same hash. An agreement whose text
can move after somebody put their name to it has not been signed, it has been
initialled — and this is the one surface in the app where a member is asked to
commit to something outside it. `_doc_hash` is over the whole document, not
just the terms, so renaming the title or changing the advance breaks it too.

**No money moves.** `advance_display` is the text both parties agreed, kept so
the document reads complete. It is not cents and it never touches a `Wallet`.
Settling an advance here would make this platform a party to an agreement it
only witnesses, and would need escrow, refunds and a dispute process that do
not exist — so the screen says "advances settle off-platform" and this code is
what makes that true.

**Unknown age fails.** Both sides of a contract must be adults, and a missing
birthday is not "probably fine" — it is the same rule `venuez.age_ok` applies
at a physical door, for the same reason: the consequence is outside the app.

Creating a label is gated, but signing is not. That is the ladder rule from
`CLAUDE.md` — a tier says how much, never whether. A Free artist can be
offered an agreement and can sign it; what Premium buys is running a label of
your own, which is a capability and not a wall in front of the feature.
"""
import hashlib

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (TIER_PREMIUM, TIER_STATZ, Label, LabelContract,
                     membership_for, profile_age, profile_for)
from .personaz import personas_of

User = get_user_model()

# The two personas that open label creation without a subscription. Named here
# once; the screen reads `can_create` rather than re-deciding, for the same
# reason a tier number is never typed into copy.
LABEL_PERSONAS = {"arscout", "manager"}
LABEL_TIERS = {TIER_PREMIUM, TIER_STATZ}

MIN_AGE = 18

# Terms go into a TextField, which Postgres will take at any size — so the
# ceiling has to be here or there isn't one. An agreement is long; a document
# that could be made arbitrarily large is a row that gets serialized into every
# contract list either side loads. 20k characters is a generous recording
# contract and still a bounded write.
MAX_TERMS = 20_000


def can_create(user):
    """Whether this member may found a label, and why not when they may not."""
    tier = getattr(membership_for(user), "tier", "")
    if tier in LABEL_TIERS:
        return True, ""
    keys = {str(p.get("key") or "").lower() for p in personas_of(profile_for(user))}
    if keys & LABEL_PERSONAS:
        return True, ""
    return False, ("Founding a label needs Premium or StatZ, or the A&R Scout "
                   "or Manager persona in ProfileZ. You can still be offered "
                   "an agreement and sign one without any of those.")


def adult(user):
    """(ok, why-not). Unknown age fails — see the module docstring."""
    age = profile_age(profile_for(user))
    if age is None:
        return False, ("Contracts are adults only, and your birthday isn't on "
                       "your profile yet — set it in ProfileZ.")
    if age < MIN_AGE:
        return False, f"Contracts are {MIN_AGE}+."
    return True, ""


def _doc_hash(label_name, artist_name, title, terms, advance):
    """The document, hashed whole.

    Every field a reader would call part of the agreement goes in, separated by
    a character none of them can contain, so two different documents cannot
    collide by running their fields together.
    """
    doc = "\x1f".join([label_name, artist_name, title, terms, advance or ""])
    return hashlib.sha256(doc.encode("utf-8")).hexdigest()


def _label_row(label, me, member_counts):
    return {
        "id": label.id,
        "name": label.name,
        "bio": label.bio,
        "owner": getattr(label.owner, "username", ""),
        "i_own": label.owner_id == me.id,
        # The owner plus everyone holding a signed agreement.
        "member_count": 1 + member_counts.get(label.id, 0),
    }


def _contract_row(c):
    return {
        "id": c.id,
        "title": c.title,
        "label": c.label.name,
        "artist": getattr(c.artist, "username", ""),
        "status": c.status,
        "terms_text": c.terms_text,
        "advance_display": c.advance_display,
        "doc_sha256": c.doc_sha256,
        "owner_signed_name": c.owner_signed_name,
        "artist_signed_name": c.artist_signed_name,
        # Cross-pollination: after creating an offer, the label owner gets a link
        # to watch the artist's response on this contract (or share with the artist).
        "open_in": f"labelz?contract={c.id}",
    }


class LabelZView(APIView):
    """`GET /api/labelz/` — every label, plus whether you can found one.
    `POST` — found one."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ok, why = can_create(request.user)
        labels = list(Label.objects.select_related("owner").all()[:200])
        counts = dict(
            Label.objects.filter(id__in=[l.id for l in labels])
            .annotate(n=Count("contracts", filter=Q(contracts__status=LabelContract.STATUS_SIGNED),
                              distinct=True))
            .values_list("id", "n")
        )
        return Response({
            "labels": [_label_row(l, request.user, counts) for l in labels],
            "can_create": ok,
            # Served rather than retyped on the screen — the client's current
            # copy names the tiers itself, which is the drift `CLAUDE.md` warns
            # about, and this is what lets that line be deleted.
            "why_not": why,
        })

    def post(self, request):
        ok, why = can_create(request.user)
        if not ok:
            return Response({"detail": why}, status=status.HTTP_403_FORBIDDEN)
        name = str(request.data.get("name") or "").strip()[:80]
        if not name:
            return Response({"detail": "Give the label a name."},
                            status=status.HTTP_400_BAD_REQUEST)
        if Label.objects.filter(name__iexact=name).exists():
            return Response({"detail": f"There's already a label called “{name}”."},
                            status=status.HTTP_400_BAD_REQUEST)
        label = Label.objects.create(owner=request.user, name=name,
                                     bio=str(request.data.get("bio") or "").strip()[:2000])
        return Response({"id": label.id, "name": label.name},
                        status=status.HTTP_201_CREATED)


class LabelContractsView(APIView):
    """`GET /api/labelz/contracts/` — yours, both sides. `POST` — offer one."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mine = (LabelContract.objects
                .filter(artist=request.user).select_related("label", "artist"))
        owned = (LabelContract.objects
                 .filter(label__owner=request.user).select_related("label", "artist"))
        return Response({
            "as_artist": [_contract_row(c) for c in mine],
            "as_owner": [_contract_row(c) for c in owned],
        })

    def post(self, request):
        ok, why = adult(request.user)
        if not ok:
            return Response({"detail": why}, status=status.HTTP_403_FORBIDDEN)

        try:
            label = Label.objects.select_related("owner").get(
                id=int(request.data.get("label_id") or 0), owner=request.user)
        except (Label.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "That isn't one of your labels."},
                            status=status.HTTP_404_NOT_FOUND)

        handle = str(request.data.get("artist") or "").strip().lstrip("@")
        try:
            artist = User.objects.get(username__iexact=handle)
        except User.DoesNotExist:
            return Response({"detail": f"No member called @{handle}."},
                            status=status.HTTP_400_BAD_REQUEST)
        if artist.id == request.user.id:
            return Response({"detail": "You can't sign an artist agreement with yourself."},
                            status=status.HTTP_400_BAD_REQUEST)

        # The artist's age is checked at the OFFER, not only at the signature,
        # so a minor is never sent an agreement to look at in the first place.
        ok, _ = adult(artist)
        if not ok:
            return Response({"detail": f"@{handle} can't be offered a contract."},
                            status=status.HTTP_400_BAD_REQUEST)

        terms = str(request.data.get("terms_text") or "").strip()
        if not terms:
            return Response({"detail": "An agreement needs its terms written out."},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(terms) > MAX_TERMS:
            # Refused, never truncated. Silently cutting the end off a contract
            # would hash and store a document neither party wrote, and the part
            # dropped is the part nobody reread.
            return Response(
                {"detail": f"Those terms are {len(terms):,} characters — the limit "
                           f"is {MAX_TERMS:,}. Trim it or link the full document."},
                status=status.HTTP_400_BAD_REQUEST)
        signed = str(request.data.get("signed_name") or "").strip()[:120]
        if not signed:
            return Response({"detail": "Type your full legal name to sign the offer."},
                            status=status.HTTP_400_BAD_REQUEST)

        title = str(request.data.get("title") or "Artist Agreement").strip()[:120]
        advance = str(request.data.get("advance_display") or "").strip()[:60]

        c = LabelContract.objects.create(
            label=label, artist=artist, title=title, terms_text=terms,
            advance_display=advance,
            owner_signed_name=signed, owner_signed_at=timezone.now(),
            doc_sha256=_doc_hash(label.name, getattr(artist, "username", ""),
                                 title, terms, advance),
        )
        return Response(_contract_row(c), status=status.HTTP_201_CREATED)


class LabelContractRespondView(APIView):
    """`POST /api/labelz/contracts/<id>/sign|decline/` — the artist answers."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        if action not in ("sign", "decline"):
            return Response({"detail": "Unknown action."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            c = LabelContract.objects.select_related("label", "artist").get(
                id=pk, artist=request.user)
        except LabelContract.DoesNotExist:
            return Response({"detail": "That contract isn't there."},
                            status=status.HTTP_404_NOT_FOUND)
        if c.status != LabelContract.STATUS_OFFERED:
            return Response({"detail": f"That one is already {c.status}."},
                            status=status.HTTP_400_BAD_REQUEST)

        if action == "decline":
            c.status = LabelContract.STATUS_DECLINED
            c.save(update_fields=["status"])
            return Response(_contract_row(c))

        ok, why = adult(request.user)
        if not ok:
            return Response({"detail": why}, status=status.HTTP_403_FORBIDDEN)
        signed = str(request.data.get("signed_name") or "").strip()[:120]
        if not signed:
            return Response({"detail": "Type your full legal name to sign."},
                            status=status.HTTP_400_BAD_REQUEST)

        # What the artist is signing must be the document the label signed. If
        # the two hashes differ the agreement changed underneath the offer, and
        # the right answer is to refuse rather than to record a signature
        # against text nobody agreed to.
        if c.doc_sha256 != _doc_hash(c.label.name, getattr(c.artist, "username", ""),
                                     c.title, c.terms_text, c.advance_display):
            return Response(
                {"detail": "These terms have changed since they were offered. "
                           "Ask the label to send a fresh agreement."},
                status=status.HTTP_409_CONFLICT)

        c.artist_signed_name = signed
        c.artist_signed_at = timezone.now()
        c.status = LabelContract.STATUS_SIGNED
        c.save(update_fields=["artist_signed_name", "artist_signed_at", "status"])
        return Response(_contract_row(c))
