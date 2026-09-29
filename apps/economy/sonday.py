"""Path 5: Sonday — Kanban board for creative project management.

Producers and artists organize work on boards with columns (Draft, In Progress,
Review, Done) and cards that move between them. Premium-only feature. Cards can
link to external resources (takes, posts, collabs) for cross-pollination.
"""
from django.contrib.auth import get_user_model
from django.db.models import Q, F
from rest_framework import status, serializers
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.economy.models import (
    SondayBoard, SondayColumn, SondayCard, SondayPermission, SondayActivity,
    Membership, TIER_FREE, TIER_DEBUG
)

User = get_user_model()


# ============================================================================
# Permissions
# ============================================================================

class IsBoardAccessible(IsAuthenticated):
    """User has any access to the board (owner/editor/viewer/public)."""

    def has_object_permission(self, request, view, obj):
        if obj.user_id == request.user.id:
            return True
        if obj.is_public:
            return True
        perm = SondayPermission.objects.filter(board_id=obj.id, user_id=request.user.id).first()
        return perm is not None


class IsBoardEditor(IsAuthenticated):
    """User can edit the board (owner or editor role)."""

    def has_object_permission(self, request, view, obj):
        if obj.user_id == request.user.id:
            return True
        perm = SondayPermission.objects.filter(
            board_id=obj.id, user_id=request.user.id
        ).first()
        return perm and perm.role in [SondayPermission.ROLE_EDITOR, SondayPermission.ROLE_OWNER]


class IsBoardOwner(IsAuthenticated):
    """User is the board owner."""

    def has_object_permission(self, request, view, obj):
        return obj.user_id == request.user.id


# ============================================================================
# Serializers
# ============================================================================

class SondayColumnSerializer(serializers.ModelSerializer):
    class Meta:
        model = SondayColumn
        fields = ["id", "key", "label", "position", "is_default", "created_at"]
        read_only_fields = ["created_at"]


class SondayActivitySerializer(serializers.ModelSerializer):
    user_display = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = SondayActivity
        fields = ["id", "user_display", "action", "from_column", "to_column", "created_at"]
        read_only_fields = ["created_at"]


class SondayCardSerializer(serializers.ModelSerializer):
    activities = SondayActivitySerializer(many=True, read_only=True)
    created_by_display = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = SondayCard
        fields = [
            "id", "board", "column", "title", "description", "position", "color",
            "due_date", "linked_app_key", "linked_target", "created_by_display",
            "created_at", "updated_at", "activities"
        ]
        read_only_fields = ["created_at", "updated_at", "board", "created_by_display"]


class SondayBoardSerializer(serializers.ModelSerializer):
    columns = SondayColumnSerializer(many=True, read_only=True)
    cards = SondayCardSerializer(many=True, read_only=True)
    user_display = serializers.CharField(source="user.username", read_only=True)
    my_role = serializers.SerializerMethodField()

    class Meta:
        model = SondayBoard
        fields = [
            "id", "user_display", "name", "description", "is_public",
            "created_at", "updated_at", "columns", "cards", "my_role"
        ]
        read_only_fields = ["created_at", "updated_at", "user_display"]

    def get_my_role(self, obj):
        """Determine current user's role on this board."""
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return "none" if obj.is_public else None

        if obj.user_id == request.user.id:
            return "owner"

        if obj.is_public:
            return "viewer"

        perm = SondayPermission.objects.filter(
            board_id=obj.id, user_id=request.user.id
        ).first()
        return perm.role if perm else None


class SondayPermissionSerializer(serializers.ModelSerializer):
    user_display = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = SondayPermission
        fields = ["id", "user", "user_display", "role", "created_at"]
        read_only_fields = ["created_at"]


# ============================================================================
# Views
# ============================================================================

class SondayBoardViewSet(ModelViewSet):
    """CRUD operations for Sonday boards."""

    serializer_class = SondayBoardSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        """Return boards user owns or has access to (not soft-deleted)."""
        user = self.request.user
        return SondayBoard.objects.filter(
            Q(user=user) | Q(permissions__user=user) | Q(is_public=True),
            deleted_at__isnull=True
        ).distinct()

    def get_object(self):
        """Override to check access."""
        obj = super().get_object()
        if obj.deleted_at is not None:
            return None
        if obj.user_id == self.request.user.id:
            return obj
        if obj.is_public:
            return obj
        perm = SondayPermission.objects.filter(
            board_id=obj.id, user_id=self.request.user.id
        ).first()
        if perm is None:
            return None
        return obj

    def get_permissions(self):
        """Different permissions for different actions."""
        if self.action == "create":
            return [IsAuthenticated()]
        elif self.action in ["list", "retrieve"]:
            return [IsAuthenticated()]
        elif self.action in ["update", "partial_update", "destroy", "add_column", "invite_user"]:
            return [IsBoardEditor()]
        return [IsAuthenticated()]

    def check_premium(self):
        """Check if user can create/edit boards (Premium-only)."""
        user = self.request.user
        try:
            membership = user.membership
            if membership.tier == TIER_FREE and membership.tier != TIER_DEBUG:
                return False
        except Membership.DoesNotExist:
            return False
        return True

    def create(self, request, *args, **kwargs):
        """Create board (Premium-only)."""
        if not self.check_premium():
            return Response(
                {"detail": "Sonday boards are a Premium feature"},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        board = SondayBoard.objects.create(
            user=request.user,
            name=serializer.validated_data.get("name", "Untitled Board"),
            description=serializer.validated_data.get("description", "")
        )

        # Create default columns
        defaults = [
            ("draft", "Drafts", 0),
            ("inprogress", "In Progress", 1),
            ("review", "Review", 2),
            ("done", "Released", 3),
        ]
        for key, label, pos in defaults:
            SondayColumn.objects.create(
                board=board, key=key, label=label, position=pos, is_default=True
            )

        return Response(
            SondayBoardSerializer(board, context={"request": request}).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def add_column(self, request, id=None):
        """Add a new column to the board."""
        board = self.get_object()
        key = request.data.get("key")
        label = request.data.get("label")
        position = request.data.get("position", 99)

        if not key or not label:
            return Response(
                {"detail": "key and label required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        column = SondayColumn.objects.create(
            board=board, key=key, label=label, position=position
        )
        return Response(
            SondayColumnSerializer(column).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def invite_user(self, request, id=None):
        """Invite user to collaborate on board (owner only)."""
        board = self.get_object()
        if board.user_id != request.user.id:
            return Response(
                {"detail": "Only board owner can invite"},
                status=status.HTTP_403_FORBIDDEN
            )

        user_id = request.data.get("user_id")
        role = request.data.get("role", SondayPermission.ROLE_EDITOR)

        if role not in [SondayPermission.ROLE_EDITOR, SondayPermission.ROLE_VIEWER]:
            return Response(
                {"detail": "role must be 'editor' or 'viewer'"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        perm, created = SondayPermission.objects.update_or_create(
            board=board, user=user, defaults={"role": role}
        )

        return Response(
            SondayPermissionSerializer(perm).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    @action(detail=True, methods=["get"])
    def permissions(self, request, id=None):
        """List collaborators on board (owner only)."""
        board = self.get_object()
        if board.user_id != request.user.id:
            return Response(
                {"detail": "Only board owner can view permissions"},
                status=status.HTTP_403_FORBIDDEN
            )

        perms = SondayPermission.objects.filter(board=board)
        serializer = SondayPermissionSerializer(perms, many=True)
        return Response(serializer.data)


class SondayCardViewSet(ModelViewSet):
    """CRUD operations for cards."""

    serializer_class = SondayCardSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        """Return cards from boards user can access (not soft-deleted)."""
        board_id = self.request.query_params.get("board_id")

        # If board_id is provided (for list operations), filter by that board
        if board_id:
            try:
                board = SondayBoard.objects.get(id=board_id, deleted_at__isnull=True)
            except SondayBoard.DoesNotExist:
                return SondayCard.objects.none()

            # Check access
            if board.user_id != self.request.user.id and not board.is_public:
                if not SondayPermission.objects.filter(
                    board=board, user=self.request.user
                ).exists():
                    return SondayCard.objects.none()

            return SondayCard.objects.filter(board=board, deleted_at__isnull=True)

        # For individual card operations (retrieve, update, delete), return all cards
        # Permission checks are done in the action methods
        return SondayCard.objects.filter(deleted_at__isnull=True)

    def create(self, request, *args, **kwargs):
        """Create card in column."""
        board_id = request.data.get("board_id")
        column_id = request.data.get("column_id")
        title = request.data.get("title")

        try:
            board = SondayBoard.objects.get(id=board_id)
        except SondayBoard.DoesNotExist:
            return Response(
                {"detail": "Board not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check write access
        if board.user_id != request.user.id:
            perm = SondayPermission.objects.filter(
                board=board, user=request.user
            ).first()
            if not perm or perm.role == SondayPermission.ROLE_VIEWER:
                return Response(
                    {"detail": "No write access"},
                    status=status.HTTP_403_FORBIDDEN
                )

        if not title:
            return Response(
                {"detail": "title required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        column = None
        if column_id:
            try:
                column = SondayColumn.objects.get(id=column_id, board=board)
            except SondayColumn.DoesNotExist:
                return Response(
                    {"detail": "Column not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        card = SondayCard.objects.create(
            board=board,
            column=column,
            title=title,
            description=request.data.get("description", ""),
            created_by=request.user,
            linked_app_key=request.data.get("linked_app_key"),
            linked_target=request.data.get("linked_target")
        )

        # Log activity
        SondayActivity.objects.create(
            card=card,
            user=request.user,
            action=SondayActivity.ACTION_CREATED,
            to_column=column.key if column else None
        )

        return Response(
            SondayCardSerializer(card, context={"request": request}).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def move(self, request, id=None):
        """Move card to different column and position."""
        card = self.get_object()
        board = card.board

        # Check write access
        if board.user_id != request.user.id:
            perm = SondayPermission.objects.filter(
                board=board, user=request.user
            ).first()
            if not perm or perm.role == SondayPermission.ROLE_VIEWER:
                return Response(
                    {"detail": "No write access"},
                    status=status.HTTP_403_FORBIDDEN
                )

        column_id = request.data.get("column_id")
        position = request.data.get("position", 9999)

        try:
            column = SondayColumn.objects.get(id=column_id, board=board)
        except SondayColumn.DoesNotExist:
            return Response(
                {"detail": "Column not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        from_col = card.column.key if card.column else None
        to_col = column.key

        card.column = column
        card.position = position
        card.save()

        # Log activity
        SondayActivity.objects.create(
            card=card,
            user=request.user,
            action=SondayActivity.ACTION_MOVED,
            from_column=from_col,
            to_column=to_col
        )

        return Response(
            SondayCardSerializer(card, context={"request": request}).data
        )
