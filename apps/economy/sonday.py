"""Sonday — a board for the work in flight: columns, cards, and who may touch them.

Producers and artists organise work on boards with columns (Drafts, In
Progress, Review, Released) and cards that move between them. A card can point
at the thing it is about — a post, a take, a deal — and carries `open_in` so a
card is a door, not a note about a door.

This shipped with no screen, and with one hole that made a screen unsafe to
build on: the card endpoints checked nothing but `move`. Any signed-in member
could read, rewrite and hard-delete a card on somebody else's PRIVATE board by
id — 200, 200, 204. Every write here now goes through `role_on()`, once, and a
card is only ever reached through a board the caller can see.

Three more things it does differently from what shipped:

* **Free gets a board.** It was Premium-only, which is a limit that says
  "whether" — the one shape the tier rules forbid. Free has `FREE_BOARDS` (1);
  Premium and StatZ have as many as they like. The count is served before the
  New board button, not discovered by pressing it.
* **Deleting is soft, and says so.** A board or card is stamped `deleted_at`
  rather than dropped — the activity log hangs off the card, and a hard delete
  through the generic viewset took the history with it.
* **Invites take a username**, which is what a person actually knows about
  another person. An id still works.
"""
import re

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from apps.economy.catalog import over_char_limit
from apps.economy.models import (
    TIER_FREE,
    SondayActivity,
    SondayBoard,
    SondayCard,
    SondayColumn,
    SondayPermission,
    membership_for,
    notify,
)

User = get_user_model()

FREE_BOARDS = 1
DEFAULT_COLUMNS = [
    ("draft", "Drafts"),
    ("inprogress", "In Progress"),
    ("review", "Review"),
    ("done", "Released"),
]
COLORS = {"", "red", "orange", "yellow", "green", "cyan", "blue", "purple", "pink"}
_APP_KEY = re.compile(r"^[a-z0-9_]{1,50}$")
ACTIVITY_SHOWN = 10

OWNER, EDITOR, VIEWER = SondayPermission.ROLE_OWNER, SondayPermission.ROLE_EDITOR, SondayPermission.ROLE_VIEWER


# ---- access ----------------------------------------------------------------

def role_on(board, user, perms=None):
    """owner / editor / viewer / None. The ONE answer every endpoint asks.

    `perms` is an optional {board_id: role} map so a list of boards does not
    pay a query per board.
    """
    if board is None or board.deleted_at is not None:
        return None
    if board.user_id == user.id:
        return OWNER
    role = (perms.get(board.id) if perms is not None else
            SondayPermission.objects.filter(board_id=board.id, user_id=user.id)
            .values_list("role", flat=True).first())
    if role in (EDITOR, OWNER):
        return EDITOR
    if role == VIEWER or board.is_public:
        return VIEWER
    return None


def can_edit(role):
    return role in (OWNER, EDITOR)


def quota_for(user):
    """How many boards this member may own, how many they do, how many are left."""
    tier = membership_for(user).tier
    used = SondayBoard.objects.filter(user=user, deleted_at__isnull=True).count()
    if tier != TIER_FREE:
        return {"tier": tier, "per_tier": None, "used": used, "left": None}
    return {"tier": tier, "per_tier": FREE_BOARDS, "used": used, "left": max(0, FREE_BOARDS - used)}


def _deny(msg="Board not found", code=status.HTTP_404_NOT_FOUND):
    # A board you may not see answers exactly like one that does not exist,
    # so the id range cannot be walked for which private boards are real.
    return Response({"detail": msg}, status=code)


def _board(board_id, user):
    board = SondayBoard.objects.filter(pk=board_id, deleted_at__isnull=True).first()
    return board, role_on(board, user)


def _card(card_id, user):
    card = (SondayCard.objects.select_related("board", "column")
            .filter(pk=card_id, deleted_at__isnull=True).first())
    if card is None:
        return None, None
    return card, role_on(card.board, user)


# ---- shapes ----------------------------------------------------------------

def open_in(card):
    """Where this card goes when it is pressed.

    A path ("/p/12") opens as a page; anything else is a tab plus the
    data-tour anchor inside it, for goToSpot. No link is no door, not a guess.
    """
    app, target = card.linked_app_key or "", card.linked_target or ""
    if target.startswith("/"):
        return {"url": target}
    if app:
        return {"tab": app, "target": target}
    return None


def card_dict(card, activities=None):
    acts = activities if activities is not None else list(card.activities.all()[:ACTIVITY_SHOWN])
    return {
        "id": card.id, "board": card.board_id, "column": card.column_id,
        "title": card.title, "description": card.description,
        "position": card.position, "color": card.color or "",
        "due_date": card.due_date.isoformat() if card.due_date else None,
        "linked_app_key": card.linked_app_key, "linked_target": card.linked_target,
        "open_in": open_in(card),
        "created_by_display": card.created_by.username if card.created_by_id else None,
        "created_at": card.created_at, "updated_at": card.updated_at,
        "activities": [{
            "id": a.id, "user_display": a.user.username if a.user_id else None,
            "action": a.action, "from_column": a.from_column, "to_column": a.to_column,
            "created_at": a.created_at,
        } for a in acts[:ACTIVITY_SHOWN]],
    }


def column_dict(c):
    return {"id": c.id, "key": c.key, "label": c.label, "position": c.position,
            "is_default": c.is_default, "created_at": c.created_at}


def board_dict(board, role, full=True):
    out = {
        "id": board.id, "user_display": board.user.username, "name": board.name,
        "description": board.description, "is_public": board.is_public,
        "created_at": board.created_at, "updated_at": board.updated_at,
        "my_role": role,
    }
    if full:
        cards = (board.cards.filter(deleted_at__isnull=True)
                 .select_related("created_by")
                 .prefetch_related(Prefetch(
                     "activities",
                     queryset=SondayActivity.objects.select_related("user").order_by("-created_at"))))
        out["columns"] = [column_dict(c) for c in board.columns.all()]
        out["cards"] = [card_dict(c, list(c.activities.all())) for c in cards]
    return out


def _clean_card_fields(data, tier):
    """The editable card fields, cleaned, or (None, error)."""
    out = {}
    if "title" in data:
        title = str(data.get("title") or "").strip()
        if not title:
            return None, "A card needs a title."
        out["title"] = title[:500]
    if "description" in data:
        desc = str(data.get("description") or "")
        cap = over_char_limit(desc, tier)
        if cap:
            return None, f"That description is over your {cap:,}-character limit."
        out["description"] = desc
    if "color" in data:
        color = str(data.get("color") or "").strip().lower()
        if color not in COLORS:
            return None, f"color must be one of: {', '.join(sorted(c for c in COLORS if c))}"
        out["color"] = color or None
    if "due_date" in data:
        raw = data.get("due_date")
        if raw in (None, ""):
            out["due_date"] = None
        else:
            d = parse_date(str(raw))
            if not d:
                return None, "due_date must be YYYY-MM-DD."
            out["due_date"] = d
    if "linked_app_key" in data:
        app = str(data.get("linked_app_key") or "").strip().lower()
        if app and not _APP_KEY.match(app):
            return None, "linked_app_key must be an app key like 'postz'."
        out["linked_app_key"] = app or None
    if "linked_target" in data:
        out["linked_target"] = (str(data.get("linked_target") or "").strip()[:500]) or None
    if "position" in data:
        try:
            out["position"] = int(data.get("position"))
        except (TypeError, ValueError):
            return None, "position must be a number."
    return out, None


# ---- boards ----------------------------------------------------------------

class SondayBoardViewSet(ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        me = request.user
        boards = list(SondayBoard.objects.filter(
            Q(user=me) | Q(permissions__user=me) | Q(is_public=True),
            deleted_at__isnull=True).select_related("user").distinct())
        perms = dict(SondayPermission.objects.filter(user=me, board__in=boards)
                     .values_list("board_id", "role"))
        out = []
        for b in boards:
            role = role_on(b, me, perms)
            if role:
                out.append(board_dict(b, role, full=False))
        return Response(out)

    def create(self, request):
        q = quota_for(request.user)
        if q["left"] is not None and q["left"] <= 0:
            return Response({
                "detail": f"Free keeps {FREE_BOARDS} board — Premium keeps as many as you like.",
                "quota": q,
            }, status=status.HTTP_403_FORBIDDEN)
        name = str(request.data.get("name") or "").strip()[:255] or "Untitled Board"
        desc = str(request.data.get("description") or "")
        cap = over_char_limit(desc, q["tier"])
        if cap:
            return Response({"detail": f"That description is over your {cap:,}-character limit."},
                            status=status.HTTP_400_BAD_REQUEST)
        board = SondayBoard.objects.create(user=request.user, name=name, description=desc)
        for pos, (key, label) in enumerate(DEFAULT_COLUMNS):
            SondayColumn.objects.create(board=board, key=key, label=label, position=pos, is_default=True)
        return Response(board_dict(board, OWNER), status=status.HTTP_201_CREATED)

    def retrieve(self, request, id=None):
        board, role = _board(id, request.user)
        if not role:
            return _deny()
        return Response(board_dict(board, role))

    def partial_update(self, request, id=None):
        board, role = _board(id, request.user)
        if not role:
            return _deny()
        if not can_edit(role):
            return _deny("Viewers can't change this board.", status.HTTP_403_FORBIDDEN)
        d = request.data
        if "is_public" in d and role != OWNER:
            # Publishing somebody else's board is the owner's call, not an editor's.
            return _deny("Only the owner can make a board public or private.", status.HTTP_403_FORBIDDEN)
        fields = []
        if "name" in d:
            board.name = str(d.get("name") or "").strip()[:255] or board.name
            fields.append("name")
        if "description" in d:
            desc = str(d.get("description") or "")
            cap = over_char_limit(desc, membership_for(request.user).tier)
            if cap:
                return Response({"detail": f"That description is over your {cap:,}-character limit."},
                                status=status.HTTP_400_BAD_REQUEST)
            board.description = desc
            fields.append("description")
        if "is_public" in d:
            board.is_public = bool(d.get("is_public")) and str(d.get("is_public")).lower() not in ("false", "0")
            fields.append("is_public")
        if fields:
            board.save(update_fields=fields + ["updated_at"])
        return Response(board_dict(board, role))

    update = partial_update

    def destroy(self, request, id=None):
        board, role = _board(id, request.user)
        if not role:
            return _deny()
        if role != OWNER:
            return _deny("Only the owner can delete a board.", status.HTTP_403_FORBIDDEN)
        board.deleted_at = timezone.now()
        board.save(update_fields=["deleted_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    def add_column(self, request, id=None):
        board, role = _board(id, request.user)
        if not role:
            return _deny()
        if not can_edit(role):
            return _deny("Viewers can't add columns.", status.HTTP_403_FORBIDDEN)
        label = str(request.data.get("label") or "").strip()[:100]
        key = str(request.data.get("key") or "").strip().lower()
        if not label:
            return Response({"detail": "A column needs a label."}, status=status.HTTP_400_BAD_REQUEST)
        # The key is an internal handle the activity log records; nobody should
        # have to invent one, so it is derived from the label when not given.
        key = re.sub(r"[^a-z0-9]", "", key or label.lower())[:20] or "col"
        base, n = key, 2
        while SondayColumn.objects.filter(board=board, key=key).exists():
            suffix = str(n)
            key = base[:20 - len(suffix)] + suffix
            n += 1
        try:
            position = int(request.data.get("position", board.columns.count()))
        except (TypeError, ValueError):
            position = board.columns.count()
        try:
            column = SondayColumn.objects.create(board=board, key=key, label=label, position=position)
        except IntegrityError:
            return Response({"detail": "That column already exists."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(column_dict(column), status=status.HTTP_201_CREATED)

    def column(self, request, id=None, column_id=None):
        """PATCH renames or reorders a column; DELETE removes it.

        Deleting never orphans a card: its cards move to the board's first
        remaining column, because a card in no column is a card nobody sees.
        """
        board, role = _board(id, request.user)
        if not role:
            return _deny()
        if not can_edit(role):
            return _deny("Viewers can't change columns.", status.HTTP_403_FORBIDDEN)
        col = SondayColumn.objects.filter(pk=column_id, board=board).first()
        if not col:
            return _deny("Column not found")
        if request.method == "DELETE":
            rest = board.columns.exclude(pk=col.pk).order_by("position").first()
            if not rest:
                return Response({"detail": "A board needs at least one column."},
                                status=status.HTTP_400_BAD_REQUEST)
            SondayCard.objects.filter(column=col).update(column=rest)
            col.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        if "label" in request.data:
            col.label = str(request.data.get("label") or "").strip()[:100] or col.label
        if "position" in request.data:
            try:
                col.position = int(request.data.get("position"))
            except (TypeError, ValueError):
                return Response({"detail": "position must be a number."}, status=status.HTTP_400_BAD_REQUEST)
        col.save()
        return Response(column_dict(col))

    def invite_user(self, request, id=None):
        board, role = _board(id, request.user)
        if not role:
            return _deny()
        if role != OWNER:
            return _deny("Only the board owner can invite.", status.HTTP_403_FORBIDDEN)
        invite_role = request.data.get("role", EDITOR)
        if invite_role not in (EDITOR, VIEWER):
            return Response({"detail": "role must be 'editor' or 'viewer'"}, status=status.HTTP_400_BAD_REQUEST)
        username = str(request.data.get("username") or "").strip().lstrip("@")
        user_id = request.data.get("user_id")
        user = (User.objects.filter(username__iexact=username).first() if username else
                User.objects.filter(pk=user_id).first() if str(user_id or "").isdigit() else None)
        if not user:
            return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        if user.id == board.user_id:
            return Response({"detail": "You already own this board."}, status=status.HTTP_400_BAD_REQUEST)
        perm, created = SondayPermission.objects.update_or_create(
            board=board, user=user, defaults={"role": invite_role})
        if created:
            notify(user, "system", f"@{request.user.username} added you to the Sonday board "
                                   f"“{board.name}” as {invite_role}.", actor=request.user,
                   item_id=f"sonday:{board.id}")
        return Response(_perm_dict(perm), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def remove_user(self, request, id=None, user_id=None):
        """Owner removes a collaborator — or a collaborator leaves on their own."""
        board, role = _board(id, request.user)
        if not role:
            return _deny()
        if role != OWNER and int(user_id) != request.user.id:
            return _deny("Only the board owner can remove people.", status.HTTP_403_FORBIDDEN)
        SondayPermission.objects.filter(board=board, user_id=user_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def permissions(self, request, id=None):
        board, role = _board(id, request.user)
        if not role:
            return _deny()
        if role != OWNER:
            return _deny("Only board owner can view permissions", status.HTTP_403_FORBIDDEN)
        perms = SondayPermission.objects.filter(board=board).select_related("user")
        return Response([_perm_dict(p) for p in perms])


def _perm_dict(p):
    return {"id": p.id, "user": p.user_id, "user_display": p.user.username,
            "role": p.role, "created_at": p.created_at}


class SondayMetaView(ViewSet):
    """GET /api/economy/sonday/meta/ — what a board costs you, before you make one."""

    permission_classes = [IsAuthenticated]

    def retrieve(self, request):
        return Response({
            "quota": quota_for(request.user),
            "default_columns": [label for _, label in DEFAULT_COLUMNS],
            "colors": sorted(c for c in COLORS if c),
        })


# ---- cards -----------------------------------------------------------------

def _log(card, user, action, frm=None, to=None):
    SondayActivity.objects.create(card=card, user=user, action=action,
                                  from_column=frm, to_column=to)


class SondayCardViewSet(ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        board, role = _board(request.query_params.get("board_id"), request.user)
        if not role:
            return Response([])
        cards = (SondayCard.objects.filter(board=board, deleted_at__isnull=True)
                 .select_related("created_by", "board")
                 .prefetch_related(Prefetch(
                     "activities",
                     queryset=SondayActivity.objects.select_related("user").order_by("-created_at"))))
        return Response([card_dict(c, list(c.activities.all())) for c in cards])

    def create(self, request):
        board, role = _board(request.data.get("board_id"), request.user)
        if not role:
            return _deny()
        if not can_edit(role):
            return _deny("No write access", status.HTTP_403_FORBIDDEN)
        fields, err = _clean_card_fields(
            {**{k: request.data.get(k) for k in request.data}, "title": request.data.get("title")},
            membership_for(request.user).tier)
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        column = None
        column_id = request.data.get("column_id")
        if column_id:
            column = SondayColumn.objects.filter(pk=column_id, board=board).first()
            if not column:
                return _deny("Column not found")
        else:
            column = board.columns.order_by("position").first()
        card = SondayCard.objects.create(board=board, column=column, created_by=request.user, **fields)
        _log(card, request.user, SondayActivity.ACTION_CREATED, to=column.key if column else None)
        return Response(card_dict(card), status=status.HTTP_201_CREATED)

    def retrieve(self, request, id=None):
        card, role = _card(id, request.user)
        if not role:
            return _deny("Card not found")
        return Response(card_dict(card))

    def partial_update(self, request, id=None):
        card, role = _card(id, request.user)
        if not role:
            return _deny("Card not found")
        if not can_edit(role):
            return _deny("No write access", status.HTTP_403_FORBIDDEN)
        fields, err = _clean_card_fields(request.data, membership_for(request.user).tier)
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        for k, v in fields.items():
            setattr(card, k, v)
        if fields:
            card.save(update_fields=list(fields) + ["updated_at"])
            _log(card, request.user, SondayActivity.ACTION_UPDATED)
        return Response(card_dict(card))

    update = partial_update

    def destroy(self, request, id=None):
        card, role = _card(id, request.user)
        if not role:
            return _deny("Card not found")
        if not can_edit(role):
            return _deny("No write access", status.HTTP_403_FORBIDDEN)
        card.deleted_at = timezone.now()
        card.save(update_fields=["deleted_at", "updated_at"])
        _log(card, request.user, SondayActivity.ACTION_DELETED,
             frm=card.column.key if card.column else None)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def move(self, request, id=None):
        card, role = _card(id, request.user)
        if not role:
            return _deny("Card not found")
        if not can_edit(role):
            return _deny("No write access", status.HTTP_403_FORBIDDEN)
        column = SondayColumn.objects.filter(pk=request.data.get("column_id"), board=card.board).first()
        if not column:
            return _deny("Column not found")
        try:
            position = int(request.data.get("position", 9999))
        except (TypeError, ValueError):
            position = 9999
        from_col = card.column.key if card.column else None
        card.column = column
        card.position = position
        card.save(update_fields=["column", "position", "updated_at"])
        _log(card, request.user, SondayActivity.ACTION_MOVED, frm=from_col, to=column.key)
        return Response(card_dict(card))
