"""MangaZ endpoints.

The AI write path is the interesting one. Two ways in, both server-side:

    script     you paste a script, the AI breaks it into pages
    character  the AI writes from a CharacterZ's bio + MBTI + voice

Either way the endpoint sets `source` and records the prompt. The client never
gets to say "this was written by hand" about something a model wrote — that
claim decides a 10% royalty, and a field the payer controls is not a fact.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.economy.models import Face

from apps.economy.models import (membership_for, pay_between,
                                 profile_for, wallet_for)
from apps.economy.nextstep import not_enough
from apps.economy.views import platform_owner
from apps.economy.upgrade import response as upgrade_response

from .ai import AiUnavailable, write_from_character, write_from_script
from .art import (ArtNotAllowed, ArtUnavailable, can_generate,
                  draw_from_character)
from .models import (AI_ROYALTY_RATE, FORMATS, MBTI_TYPES, ROLE_ARTIST,
                     ROLE_SUPERVISOR, SOURCE_CHARACTER, SOURCE_HUMAN,
                     SOURCE_SCRIPT, CharacterZ, GuardianConsent, MangaZ, Meet,
                     MeetAttendee, Page, Room, RoomApproval, RoomMember,
                     PASS_HOURS, SALE_OWN, SALE_PASS, Commission, Sale,
                     Volume, duration_error, is_minor,
                     is_verified_adult)

User = get_user_model()


def _character_dict(c):
    return {"id": c.id, "name": c.name, "mbti": c.mbti, "bio": c.bio,
            "traits": c.traits, "voice": c.voice, "shared": c.shared,
            "face_id": c.face_id, "owner": c.owner.username}


def _room_dict(room, user=None):
    out = {
        "id": room.id, "title": room.title, "owner": room.owner.username,
        "supervisor": room.supervisor.username if room.supervisor_id else None,
        "open_to_all_ages": room.open_to_all_ages,
        "has_minor": room.has_minor(),
        "supervision_error": room.supervision_error(),
        "members": [{"user": m.user.username, "role": m.role}
                    for m in room.members.select_related("user")],
    }
    if user is not None:
        out["you_can_join"] = room.join_error(user) is None
        out["why_not"] = room.join_error(user)
    return out


def _manga_dict(m, full=False):
    out = {"id": m.id, "title": m.title, "owner": m.owner.username,
           "room": m.room_id, "synopsis": m.synopsis,
           "format": m.format_payload(),
           "characters": [c.name for c in m.characters.all()],
           "provenance": m.provenance(), "updated_at": m.updated_at}
    if full:
        out["pages"] = [{"number": p.number, "author": p.author.username,
                         "script": p.script, "art_url": p.art_url,
                         "source": p.source, "ai_assisted": p.ai_assisted,
                         "ai_model": p.ai_model}
                        for p in m.pages.select_related("author")]
    return out


class CatalogView(APIView):
    """GET the MangaZ rules. Public — the age rules should be readable before
    somebody signs their kid up to anything."""

    permission_classes = [AllowAny]

    def get(self, _request):
        return Response({
            "mbti": MBTI_TYPES,
            "formats": [
                {"key": k, "label": label, "icon": icon,
                 "min_seconds": low, "max_seconds": high}
                for k, (label, icon, low, high) in FORMATS.items()
            ],
            "sources": [
                {"key": SOURCE_HUMAN, "label": "Written by hand", "ai": False},
                {"key": SOURCE_SCRIPT, "label": "AI from your script", "ai": True},
                {"key": SOURCE_CHARACTER, "label": "AI from a character sheet",
                 "ai": True},
            ],
            "ai_royalty_rate": AI_ROYALTY_RATE,
            "rules": {
                "supervision": (
                    "A room with anyone under 18 needs a verified adult "
                    "supervisor, and any other adult needs that supervisor's "
                    "approval to join. Verification means verified 18+, not a "
                    "birthday typed into a form."),
                "ai_royalty": (
                    "A MangaZ with any AI-written page pays the developer an "
                    "extra 10% royalty on sales. It's computed from the pages, "
                    "not from a checkbox — you can't be charged for AI you "
                    "didn't use, and you can't untick your way out of it."),
                "provenance": (
                    "Every page records who or what wrote it, and the work "
                    "shows the breakdown."),
            },
        })


class CharacterZView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mine = CharacterZ.objects.filter(owner=request.user)
        shared = CharacterZ.objects.filter(shared=True).exclude(owner=request.user)
        return Response({"mine": [_character_dict(c) for c in mine],
                         "shared": [_character_dict(c) for c in shared]})

    def post(self, request):
        d = request.data or {}
        name = str(d.get("name", "")).strip()
        if not name:
            return Response({"detail": "A character needs a name."},
                            status=status.HTTP_400_BAD_REQUEST)
        face = None
        if d.get("face_id"):
            face = Face.objects.filter(pk=d["face_id"], owner=request.user).first()
            if not face:
                return Response({"detail": "That's not your face."},
                                status=status.HTTP_400_BAD_REQUEST)
        c = CharacterZ(owner=request.user, name=name[:80], face=face,
                       bio=str(d.get("bio", ""))[:4000],
                       mbti=str(d.get("mbti", "")).strip().upper()[:4],
                       traits=[str(t)[:40] for t in (d.get("traits") or [])][:20],
                       voice=str(d.get("voice", ""))[:200],
                       shared=bool(d.get("shared")))
        problem = c.mbti_error()
        if problem:
            return Response({"detail": problem, "mbti": MBTI_TYPES},
                            status=status.HTTP_400_BAD_REQUEST)
        c.save()
        return Response({"character": _character_dict(c)},
                        status=status.HTTP_201_CREATED)


class RoomsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rooms = Room.objects.select_related("owner", "supervisor")[:100]
        return Response({"rooms": [_room_dict(r, request.user) for r in rooms]})

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "A room needs a title."},
                            status=status.HTTP_400_BAD_REQUEST)
        # Whoever makes the room supervises it if they can. A minor can make a
        # room; it just can't be used until a verified adult takes it on.
        supervisor = request.user if is_verified_adult(request.user) else None
        room = Room.objects.create(
            title=title[:160], owner=request.user, supervisor=supervisor,
            open_to_all_ages=bool(d.get("open_to_all_ages", True)))
        RoomMember.objects.create(
            room=room, user=request.user,
            role=ROLE_SUPERVISOR if supervisor else ROLE_ARTIST)
        return Response({"room": _room_dict(room, request.user)},
                        status=status.HTTP_201_CREATED)


class RoomJoinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        room = Room.objects.filter(pk=pk).first()
        if not room:
            return Response({"detail": "No such room."},
                            status=status.HTTP_404_NOT_FOUND)
        refused = room.join_error(request.user)
        if refused:
            return Response({"detail": refused},
                            status=status.HTTP_403_FORBIDDEN)
        RoomMember.objects.get_or_create(
            room=room, user=request.user,
            defaults={"role": str((request.data or {}).get("role") or ROLE_ARTIST)})
        # Joining can be what turns this into a room needing supervision.
        return Response({"room": _room_dict(room, request.user)},
                        status=status.HTTP_201_CREATED)


class RoomSuperviseView(APIView):
    """POST to take on supervision, or to approve/refuse an adult."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        room = Room.objects.filter(pk=pk).first()
        if not room:
            return Response({"detail": "No such room."},
                            status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        username = str(d.get("username", "")).strip()

        if not username:
            # Taking the room on yourself.
            if not is_verified_adult(request.user):
                return Response(
                    {"detail": "Only a verified adult can supervise a room."},
                    status=status.HTTP_403_FORBIDDEN)
            room.supervisor = request.user
            room.save(update_fields=["supervisor"])
            RoomMember.objects.update_or_create(
                room=room, user=request.user,
                defaults={"role": ROLE_SUPERVISOR})
            return Response({"room": _room_dict(room, request.user)})

        # Deciding on somebody else.
        if room.supervisor_id != request.user.id:
            return Response({"detail": "Only the supervisor decides who joins."},
                            status=status.HTTP_403_FORBIDDEN)
        target = User.objects.filter(username=username).first()
        if not target:
            return Response({"detail": "No such member."},
                            status=status.HTTP_404_NOT_FOUND)
        approved = bool(d.get("approved", True))
        RoomApproval.objects.update_or_create(
            room=room, user=target,
            defaults={"approved": approved, "decided_by": request.user})
        if not approved:
            RoomMember.objects.filter(room=room, user=target).delete()
        return Response({"room": _room_dict(room, request.user),
                         "decision": {"user": username, "approved": approved}})


def _room_for(user, pk):
    """The room, if `user` is in it and it's safe to use. Returns (room, error)."""
    room = Room.objects.filter(pk=pk).first()
    if not room:
        return None, ("No such room.", status.HTTP_404_NOT_FOUND)
    if not room.members.filter(user=user).exists():
        return None, ("You're not in this room.", status.HTTP_403_FORBIDDEN)
    unsafe = room.supervision_error()
    if unsafe:
        # Checked on every write, not only on join. A supervisor can leave, or
        # lose verification, and the room must stop working the moment it does.
        return None, (unsafe, status.HTTP_409_CONFLICT)
    return room, None


class MangaListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        works = MangaZ.objects.filter(
            room__members__user=request.user).distinct()[:100]
        return Response({"mangaz": [_manga_dict(m) for m in works]})

    def post(self, request):
        d = request.data or {}
        room, err = _room_for(request.user, d.get("room_id"))
        if err:
            return Response({"detail": err[0]}, status=err[1])
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "A manga needs a title."},
                            status=status.HTTP_400_BAD_REQUEST)
        fmt = str(d.get("format", "manga"))
        if fmt not in FORMATS:
            return Response({"detail": f"Unknown format {fmt!r}.",
                             "formats": sorted(FORMATS)},
                            status=status.HTTP_400_BAD_REQUEST)
        runtime = d.get("runtime_seconds")
        bad = duration_error(fmt, runtime)
        if bad:
            return Response({"detail": bad},
                            status=status.HTTP_400_BAD_REQUEST)
        m = MangaZ.objects.create(title=title[:160], room=room,
                                  owner=request.user, format=fmt,
                                  runtime_seconds=runtime or None,
                                  synopsis=str(d.get("synopsis", ""))[:4000])
        for cid in (d.get("character_ids") or [])[:20]:
            c = CharacterZ.objects.filter(pk=cid).filter(
                models_q(request.user)).first()
            if c:
                m.characters.add(c)
        return Response({"manga": _manga_dict(m, full=True)},
                        status=status.HTTP_201_CREATED)


def models_q(user):
    """Characters you may use: your own, or ones shared with everybody."""
    from django.db.models import Q
    return Q(owner=user) | Q(shared=True)


class MangaDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        m = MangaZ.objects.filter(pk=pk,
                                  room__members__user=request.user).first()
        if not m:
            return Response({"detail": "No such manga."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response({"manga": _manga_dict(m, full=True)})


class PagesView(APIView):
    """POST a page. `mode` picks who writes it.

        mode=human      you wrote it, `script` is yours
        mode=script     you pasted a script, the AI lays it out
        mode=character  the AI writes from a character sheet
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        m = MangaZ.objects.filter(pk=pk,
                                  room__members__user=request.user).first()
        if not m:
            return Response({"detail": "No such manga."},
                            status=status.HTTP_404_NOT_FOUND)
        unsafe = m.room.supervision_error()
        if unsafe:
            return Response({"detail": unsafe},
                            status=status.HTTP_409_CONFLICT)

        d = request.data or {}
        mode = str(d.get("mode", SOURCE_HUMAN))
        number = m.pages.count() + 1
        prompt, model_name, text = {}, "", str(d.get("script", ""))

        if mode == SOURCE_SCRIPT:
            if not text.strip():
                return Response({"detail": "Paste a script to lay out."},
                                status=status.HTTP_400_BAD_REQUEST)
            try:
                text, prompt, model_name = write_from_script(request.user, text)
            except AiUnavailable as exc:
                return Response({"detail": str(exc)},
                                status=status.HTTP_503_SERVICE_UNAVAILABLE)
        elif mode == SOURCE_CHARACTER:
            character = CharacterZ.objects.filter(
                pk=d.get("character_id")).filter(models_q(request.user)).first()
            if not character:
                return Response(
                    {"detail": "Pick one of your characters, or a shared one."},
                    status=status.HTTP_400_BAD_REQUEST)
            try:
                text, prompt, model_name = write_from_character(
                    request.user, character, str(d.get("beat", "")))
            except AiUnavailable as exc:
                return Response({"detail": str(exc)},
                                status=status.HTTP_503_SERVICE_UNAVAILABLE)
        elif mode != SOURCE_HUMAN:
            return Response({"detail": f"Unknown mode {mode!r}."},
                            status=status.HTTP_400_BAD_REQUEST)

        page = Page.objects.create(
            manga=m, number=number, author=request.user, script=text,
            art_url=str(d.get("art_url", ""))[:500],
            source=mode, ai_prompt=prompt, ai_model=model_name)
        return Response({"page": {"number": page.number, "script": page.script,
                                  "source": page.source,
                                  "ai_assisted": page.ai_assisted},
                         "provenance": m.provenance()},
                        status=status.HTTP_201_CREATED)


class RoyaltyQuoteView(APIView):
    """GET ?sale_cents=… — what a sale of this work owes, and why.

    Shown before publishing rather than discovered afterwards. A royalty
    somebody finds out about at payout is one they argue about.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        m = MangaZ.objects.filter(pk=pk,
                                  room__members__user=request.user).first()
        if not m:
            return Response({"detail": "No such manga."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            sale = max(0, int(request.query_params.get("sale_cents", 0)))
        except (TypeError, ValueError):
            sale = 0
        return Response({"sale_cents": sale,
                         "ai_royalty_cents": m.ai_royalty_cents(sale),
                         "provenance": m.provenance()})


def _meet_dict(meet):
    return {
        "id": meet.id, "title": meet.title, "place": meet.place,
        "is_public_place": meet.is_public_place, "starts_at": meet.starts_at,
        "organiser": meet.organiser.username, "room": meet.room_id,
        "attendees": [a.user.username for a in meet.attendees.select_related("user")],
        "minors_attending": [u.username for u in meet.minors_attending()],
        "consent_missing": [u.username for u in meet.missing_consent()],
        "ready": meet.readiness_error() is None,
        "why_not": meet.readiness_error(),
    }


class MeetsView(APIView):
    """In-person sessions for a room. Teens and adults in the same place.

    Supported rather than refused: a studio afternoon or a school programme is
    a real thing creative people do, and not supporting it just moves it
    somewhere nothing is recorded. The conditions are in Meet.readiness_error.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        room, err = _room_for(request.user, pk)
        if err:
            return Response({"detail": err[0]}, status=err[1])
        return Response({"meets": [_meet_dict(m) for m in room.meets.all()]})

    def post(self, request, pk):
        room, err = _room_for(request.user, pk)
        if err:
            return Response({"detail": err[0]}, status=err[1])
        d = request.data or {}
        title = str(d.get("title", "")).strip()
        place = str(d.get("place", "")).strip()
        starts_at = d.get("starts_at")
        if not (title and place and starts_at):
            return Response(
                {"detail": "A meet needs a title, a place and a start time."},
                status=status.HTTP_400_BAD_REQUEST)
        meet = Meet.objects.create(
            room=room, title=title[:160], place=place[:300],
            is_public_place=bool(d.get("is_public_place", True)),
            starts_at=starts_at, organiser=request.user)
        MeetAttendee.objects.create(meet=meet, user=request.user)
        return Response({"meet": _meet_dict(meet)},
                        status=status.HTTP_201_CREATED)


class MeetAttendView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        meet = Meet.objects.filter(pk=pk).first()
        if not meet:
            return Response({"detail": "No such meet."},
                            status=status.HTTP_404_NOT_FOUND)
        if not meet.room.members.filter(user=request.user).exists():
            return Response({"detail": "You're not in this room."},
                            status=status.HTTP_403_FORBIDDEN)
        MeetAttendee.objects.get_or_create(meet=meet, user=request.user)
        # Reported, not refused. A minor joining is exactly what creates the
        # consent requirement, and blocking the join would hide the reason —
        # `why_not` names what's still needed so somebody can go and get it.
        return Response({"meet": _meet_dict(meet)},
                        status=status.HTTP_201_CREATED)


class MeetConsentView(APIView):
    """Record a guardian's yes for one minor at one meet.

    Only the supervisor records it, and only for a minor who is attending.
    This is a recorded assertion with a contact on it, not proof — no backend
    can verify a parent, and pretending otherwise would be the dishonest part.
    Per-meet on purpose: blanket consent covering every future session is the
    thing a guardian did not actually agree to.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        meet = Meet.objects.filter(pk=pk).first()
        if not meet:
            return Response({"detail": "No such meet."},
                            status=status.HTTP_404_NOT_FOUND)
        if meet.room.supervisor_id != request.user.id:
            return Response(
                {"detail": "Only the room's supervisor records guardian consent."},
                status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        target = User.objects.filter(username=str(d.get("username", ""))).first()
        if not target or not meet.attendees.filter(user=target).exists():
            return Response({"detail": "That member isn't attending this meet."},
                            status=status.HTTP_400_BAD_REQUEST)
        name = str(d.get("guardian_name", "")).strip()
        contact = str(d.get("guardian_contact", "")).strip()
        if not (name and contact):
            return Response(
                {"detail": "Record the guardian's name and a contact for them."},
                status=status.HTTP_400_BAD_REQUEST)
        GuardianConsent.objects.update_or_create(
            meet=meet, minor=target,
            defaults={"guardian_name": name[:120],
                      "guardian_contact": contact[:200],
                      "granted": bool(d.get("granted", True)),
                      "recorded_by": request.user})
        return Response({"meet": _meet_dict(meet)})


class ArtView(APIView):
    """POST — draw a page's art from a CharacterZ. Premium and StatZ only.

    The Premium hook. Everything else in MangaZ stays free: the tabs, the
    icons, the rooms, the collabs, the writing. What you pay for is being able
    to MAKE something — which is what people keep paying for, unlike a nicer
    button, which they resent.

    Generated art counts as AI, so the 10% royalty applies. Recorded on
    `art_source` separately from the writing, because a page can be written by
    hand and drawn by the model, and collapsing the two would either miss a
    royalty or charge one nobody owes.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        """What this member can do here, before they try and get refused."""
        m = MangaZ.objects.filter(pk=pk,
                                  room__members__user=request.user).first()
        if not m:
            return Response({"detail": "No such manga."},
                            status=status.HTTP_404_NOT_FOUND)
        allowed = can_generate(request.user)
        return Response({
            "can_generate": allowed,
            "tier": membership_for(request.user).tier,
            "why_not": None if allowed else (
                "Generating art from your CharacterZ is a Premium feature."),
            "free_anyway": ["reading", "writing", "rooms", "collabs",
                            "in-person meets", "publishing"],
            "note": ("Art made this way counts as AI, so the 10% developer "
                     "royalty applies to sales of the work."),
        })

    @transaction.atomic
    def post(self, request, pk):
        m = MangaZ.objects.filter(pk=pk,
                                  room__members__user=request.user).first()
        if not m:
            return Response({"detail": "No such manga."},
                            status=status.HTTP_404_NOT_FOUND)
        unsafe = m.room.supervision_error()
        if unsafe:
            return Response({"detail": unsafe},
                            status=status.HTTP_409_CONFLICT)

        d = request.data or {}
        character = CharacterZ.objects.filter(
            pk=d.get("character_id")).filter(models_q(request.user)).first()
        if not character:
            return Response(
                {"detail": "Pick one of your characters, or a shared one."},
                status=status.HTTP_400_BAD_REQUEST)

        try:
            image, record, model_name = draw_from_character(
                request.user, character, str(d.get("brief", "")))
        except ArtNotAllowed as exc:
            # A dead-end 402 is a wasted upgrade — say what it costs and where.
            return Response({"detail": str(exc), "upgrade": upgrade_response(
                request.user, feature="MangaZ art")},
                status=status.HTTP_402_PAYMENT_REQUIRED)
        except ArtUnavailable as exc:
            return Response({"detail": str(exc)},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        page_number = d.get("page")
        page = m.pages.filter(number=page_number).first() if page_number else None
        if page is None:
            page = Page.objects.create(manga=m, number=m.pages.count() + 1,
                                       author=request.user,
                                       source=SOURCE_HUMAN)
        page.art_url = image
        page.art_source = SOURCE_CHARACTER
        page.ai_prompt = {**(page.ai_prompt or {}), "art": record}
        page.ai_model = model_name
        page.save(update_fields=["art_url", "art_source", "ai_prompt",
                                 "ai_model"])
        return Response({"page": {"number": page.number,
                                  "art_source": page.art_source,
                                  "ai_assisted": page.ai_assisted},
                         "image": image,
                         "prompt": record,
                         "provenance": m.provenance()},
                        status=status.HTTP_201_CREATED)


def _volume_dict(v, user=None):
    out = {
        "id": v.id, "number": v.number, "title": v.title,
        "manga": v.manga_id, "manga_title": v.manga.title,
        "pages": v.page_count(),
        "first_page": v.first_page, "last_page": v.last_page,
        "price_cents": v.price_cents,
        "pass_price_cents": v.pass_price_cents, "pass_hours": v.pass_hours,
        "published": v.published,
        "suggested_price_cents": v.suggested_price_cents(),
        "suggested_pass_cents": v.suggested_pass_cents(),
        "contributors": {u.username: n for u, n in v.contributors().items()},
        "ai_royalty_rate": AI_ROYALTY_RATE if v.manga.used_ai() else 0.0,
    }
    if user is not None:
        sale = v.sales.filter(buyer=user).order_by("-created_at").first()
        out["you_own"] = bool(sale and sale.kind == SALE_OWN)
        out["your_pass_active"] = bool(sale and sale.kind == SALE_PASS
                                       and sale.active())
    return out


class VolumesView(APIView):
    """List and cut volumes. A MangaZ nobody can buy is a hobby."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        m = MangaZ.objects.filter(pk=pk).first()
        if not m:
            return Response({"detail": "No such manga."},
                            status=status.HTTP_404_NOT_FOUND)
        # Published volumes are readable by anyone; drafts only by the room.
        in_room = m.room.members.filter(user=request.user).exists()
        qs = m.volumes.all() if in_room else m.volumes.filter(published=True)
        return Response({"volumes": [_volume_dict(v, request.user) for v in qs]})

    def post(self, request, pk):
        m = MangaZ.objects.filter(pk=pk, owner=request.user).first()
        if not m:
            return Response({"detail": "Only the owner cuts volumes."},
                            status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}

        def num(key, default=0):
            try:
                return max(0, int(d.get(key, default) or 0))
            except (TypeError, ValueError):
                return default

        v = Volume(
            manga=m, number=num("number", m.volumes.count() + 1) or 1,
            title=str(d.get("title", ""))[:160],
            first_page=num("first_page", 1) or 1,
            last_page=num("last_page", m.pages.count()) or 1,
            price_cents=num("price_cents"),
            pass_price_cents=num("pass_price_cents"),
            pass_hours=num("pass_hours", PASS_HOURS) or PASS_HOURS,
            published=bool(d.get("published")))
        # Priced by hand or not at all — fall back to their own hourly rate so
        # a creator who doesn't want to think about pricing still ships.
        if not v.price_cents and not v.pass_price_cents:
            v.price_cents = v.suggested_price_cents()
            v.pass_price_cents = v.suggested_pass_cents()
        problem = v.publish_error() if v.published else None
        if problem:
            return Response({"detail": problem},
                            status=status.HTTP_400_BAD_REQUEST)
        v.save()
        return Response({"volume": _volume_dict(v, request.user)},
                        status=status.HTTP_201_CREATED)


class BuyVolumeView(APIView):
    """Buy a volume outright, or take a reading pass.

    The money splits between everyone who made pages in it, by page count.
    The data already knows who made what, and a split nobody has to negotiate
    is a split nobody argues about.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        v = Volume.objects.select_related("manga", "manga__owner").filter(
            pk=pk, published=True).first()
        if not v:
            return Response({"detail": "No such volume on sale."},
                            status=status.HTTP_404_NOT_FOUND)
        kind = str((request.data or {}).get("kind", SALE_OWN))
        if kind not in (SALE_OWN, SALE_PASS):
            return Response({"detail": "kind must be 'own' or 'pass'."},
                            status=status.HTTP_400_BAD_REQUEST)
        if v.manga.owner_id == request.user.id:
            return Response({"detail": "It's already yours."},
                            status=status.HTTP_400_BAD_REQUEST)

        price = v.price_cents if kind == SALE_OWN else v.pass_price_cents
        if not price:
            return Response({"detail": f"That volume isn't sold as a {kind}."},
                            status=status.HTTP_400_BAD_REQUEST)
        if v.sales.filter(buyer=request.user, kind=SALE_OWN).exists():
            return Response({"detail": "You already own this one."},
                            status=status.HTTP_409_CONFLICT)

        wallet = wallet_for(request.user)
        if wallet.money_cents < price:
            return Response(
                not_enough(request.user, need_cents=price,
                           feature=f"{v.manga.title} vol. {v.number}",
                           detail=f"{v.manga.title} vol. {v.number} costs "
                                  f"${price / 100:.2f} — you're "
                                  f"${(price - wallet.money_cents) / 100:.2f} short."),
                status=status.HTTP_402_PAYMENT_REQUIRED)

        # The AI royalty comes off the top, before the split. The people who
        # made the pages divide what's left, so nobody's share silently pays
        # somebody else's model bill.
        royalty = v.manga.ai_royalty_cents(price)
        owner = platform_owner()
        dev_total = 0
        for member_user, cut in v.split_cents(price - royalty).items():
            if cut <= 0:
                continue
            dev, _net = pay_between(request.user, member_user, cut,
                                    note=f"MangaZ: {v.manga.title} v{v.number}")
            dev_total += dev
        if royalty and owner:
            pay_between(request.user, owner, royalty,
                        note=f"MangaZ AI royalty: {v.manga.title} v{v.number}")

        expires = None
        if kind == SALE_PASS:
            from django.utils import timezone
            expires = timezone.now() + timedelta(hours=v.pass_hours)
        sale = Sale.objects.create(volume=v, buyer=request.user, kind=kind,
                                   price_cents=price, dev_tax_cents=dev_total,
                                   ai_royalty_cents=royalty,
                                   expires_at=expires)
        return Response({
            "sale": {"kind": sale.kind, "price_cents": sale.price_cents,
                     "ai_royalty_cents": sale.ai_royalty_cents,
                     "expires_at": sale.expires_at, "active": sale.active()},
            "volume": _volume_dict(v, request.user),
            "wallet": wallet_for(request.user).money_cents,
        }, status=status.HTTP_201_CREATED)


class CommissionView(APIView):
    """Hire the designer by the hour, at their own skill price.

    This is where "by the hour" belongs — somebody buying their TIME, which is
    what skill_price_cents measures. The total is shown before anyone pays.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Quote first. Nobody should discover a bill after the fact."""
        designer = User.objects.filter(
            username=request.query_params.get("designer", "")).first()
        if not designer:
            return Response({"detail": "No such designer."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            hours = max(1, int(request.query_params.get("hours", 1)))
        except (TypeError, ValueError):
            hours = 1
        rate = profile_for(designer).skill_price_cents or 0
        return Response({"designer": designer.username, "hours": hours,
                         "rate_cents": rate, "total_cents": rate * hours,
                         "note": "Their hourly skill price. Agreed before you pay."})

    @transaction.atomic
    def post(self, request):
        d = request.data or {}
        designer = User.objects.filter(username=str(d.get("designer", ""))).first()
        if not designer or designer.id == request.user.id:
            return Response({"detail": "Pick a designer other than yourself."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            hours = max(1, int(d.get("hours", 1)))
        except (TypeError, ValueError):
            hours = 1
        rate = profile_for(designer).skill_price_cents or 0
        if not rate:
            return Response(
                {"detail": f"{designer.username} hasn't set an hourly skill "
                           f"price yet, so there's nothing to quote."},
                status=status.HTTP_409_CONFLICT)
        total = rate * hours
        if wallet_for(request.user).money_cents < total:
            return Response(
                not_enough(request.user, need_cents=total,
                           feature=f"{hours}h with {designer.username}"),
                status=status.HTTP_402_PAYMENT_REQUIRED)
        pay_between(request.user, designer, total,
                    note=f"MangaZ commission: {hours}h")
        c = Commission.objects.create(
            designer=designer, client=request.user,
            brief=str(d.get("brief", ""))[:4000], hours=hours,
            rate_cents=rate, paid=True)
        return Response({"commission": {
            "id": c.id, "designer": designer.username, "hours": c.hours,
            "rate_cents": c.rate_cents, "total_cents": c.total_cents(),
        }}, status=status.HTTP_201_CREATED)
