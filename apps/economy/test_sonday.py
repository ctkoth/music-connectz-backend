"""Tests for Path 5: SondayZ Kanban board for creative project management."""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from apps.economy.models import (
    SondayBoard, SondayColumn, SondayCard, SondayPermission, SondayActivity,
    Membership, Wallet, TIER_FREE, TIER_PREMIUM
)

User = get_user_model()


class SondayBoardCreationTests(APITestCase):
    """Test board creation and tier gating."""

    def setUp(self):
        self.client = APIClient()
        self.free_user = User.objects.create_user(
            username="free_user",
            email="free@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.free_user, tier=TIER_FREE)
        Wallet.objects.create(user=self.free_user, spinaz=1000)

        self.premium_user = User.objects.create_user(
            username="premium_user",
            email="premium@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.premium_user, tier=TIER_PREMIUM)
        Wallet.objects.create(user=self.premium_user, spinaz=1000)

    def test_free_user_gets_one_board_not_none(self):
        """Free keeps one board; the second asks for Premium and says why.

        It used to be Premium-only — a limit that said "whether", which the
        tier rules forbid. A Free member now has a board to try it with.
        """
        self.client.force_authenticate(user=self.free_user)
        first = self.client.post("/api/economy/sonday/", {"name": "One"})
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self.client.post("/api/economy/sonday/", {"name": "Two"})
        self.assertEqual(second.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Premium", second.data["detail"])
        self.assertEqual(second.data["quota"]["left"], 0)

    def test_the_quota_is_served_before_the_button(self):
        self.client.force_authenticate(user=self.free_user)
        q = self.client.get("/api/economy/sonday/meta/").data["quota"]
        self.assertEqual((q["per_tier"], q["used"], q["left"]), (1, 0, 1))
        self.client.force_authenticate(user=self.premium_user)
        self.assertIsNone(self.client.get("/api/economy/sonday/meta/").data["quota"]["left"])

    def test_premium_user_can_create_board(self):
        """Premium users can create Sonday boards."""
        self.client.force_authenticate(user=self.premium_user)
        data = {
            "name": "My Project Board",
            "description": "Organizing my tracks"
        }
        response = self.client.post("/api/economy/sonday/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "My Project Board")
        self.assertEqual(response.data["user_display"], self.premium_user.username)
        self.assertEqual(response.data["my_role"], "owner")

    def test_board_has_default_columns(self):
        """New board is created with default columns (Draft, In Progress, Review, Done)."""
        self.client.force_authenticate(user=self.premium_user)
        data = {
            "name": "My Project Board",
            "description": "Organizing my tracks"
        }
        response = self.client.post("/api/economy/sonday/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        board_id = response.data["id"]

        # Check board has 4 default columns
        board = SondayBoard.objects.get(id=board_id)
        columns = board.columns.all()
        self.assertEqual(columns.count(), 4)

        # Verify column labels and keys
        col_keys = {c.key for c in columns}
        self.assertEqual(col_keys, {"draft", "inprogress", "review", "done"})

        labels = {c.label for c in columns}
        self.assertIn("Drafts", labels)
        self.assertIn("In Progress", labels)


class SondayBoardAccessTests(APITestCase):
    """Test board access control and permissions."""

    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.owner, tier=TIER_PREMIUM)
        Wallet.objects.create(user=self.owner, spinaz=1000)

        self.editor = User.objects.create_user(
            username="editor",
            email="editor@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.editor, tier=TIER_FREE)
        Wallet.objects.create(user=self.editor, spinaz=1000)

        self.viewer = User.objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.viewer, tier=TIER_FREE)
        Wallet.objects.create(user=self.viewer, spinaz=1000)

        self.stranger = User.objects.create_user(
            username="stranger",
            email="stranger@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.stranger, tier=TIER_FREE)
        Wallet.objects.create(user=self.stranger, spinaz=1000)

        # Create a private board
        self.board = SondayBoard.objects.create(
            user=self.owner,
            name="Private Board",
            description="Owner's board",
            is_public=False
        )

        # Add columns
        SondayColumn.objects.create(board=self.board, key="draft", label="Draft", position=0, is_default=True)

        # Grant permissions
        SondayPermission.objects.create(
            board=self.board,
            user=self.editor,
            role=SondayPermission.ROLE_EDITOR
        )
        SondayPermission.objects.create(
            board=self.board,
            user=self.viewer,
            role=SondayPermission.ROLE_VIEWER
        )

    def test_owner_can_access_own_board(self):
        """Owner can access their own board."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(f"/api/economy/sonday/{self.board.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["my_role"], "owner")

    def test_editor_can_access_shared_board(self):
        """User with editor role can access shared board."""
        self.client.force_authenticate(user=self.editor)
        response = self.client.get(f"/api/economy/sonday/{self.board.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["my_role"], "editor")

    def test_viewer_can_access_shared_board(self):
        """User with viewer role can access shared board."""
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(f"/api/economy/sonday/{self.board.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["my_role"], "viewer")

    def test_stranger_cannot_access_private_board(self):
        """Stranger without permission cannot access private board."""
        self.client.force_authenticate(user=self.stranger)
        response = self.client.get(f"/api/economy/sonday/{self.board.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_board_accessible_to_all(self):
        """Public board is accessible to anyone with authentication."""
        public_board = SondayBoard.objects.create(
            user=self.owner,
            name="Public Board",
            is_public=True
        )
        self.client.force_authenticate(user=self.stranger)
        response = self.client.get(f"/api/economy/sonday/{public_board.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["my_role"], "viewer")


class SondayColumnTests(APITestCase):
    """Test column management."""

    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.owner, tier=TIER_PREMIUM)
        Wallet.objects.create(user=self.owner, spinaz=1000)

        self.editor = User.objects.create_user(
            username="editor",
            email="editor@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.editor, tier=TIER_FREE)
        Wallet.objects.create(user=self.editor, spinaz=1000)

        self.board = SondayBoard.objects.create(
            user=self.owner,
            name="Test Board",
            is_public=False
        )
        SondayColumn.objects.create(board=self.board, key="draft", label="Draft", position=0, is_default=True)

        SondayPermission.objects.create(
            board=self.board,
            user=self.editor,
            role=SondayPermission.ROLE_EDITOR
        )

    def test_owner_can_add_column(self):
        """Owner can add a new column."""
        self.client.force_authenticate(user=self.owner)
        data = {
            "key": "feedback",
            "label": "Feedback",
            "position": 99
        }
        response = self.client.post(f"/api/economy/sonday/{self.board.id}/add_column/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["label"], "Feedback")

        # Verify column was created
        board = SondayBoard.objects.get(id=self.board.id)
        self.assertEqual(board.columns.count(), 2)

    def test_editor_can_add_column(self):
        """Editor can add a new column."""
        self.client.force_authenticate(user=self.editor)
        data = {
            "key": "testing",
            "label": "Testing",
            "position": 99
        }
        response = self.client.post(f"/api/economy/sonday/{self.board.id}/add_column/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_viewer_cannot_add_column(self):
        """Viewer cannot add a column."""
        viewer = User.objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=viewer, tier=TIER_FREE)
        Wallet.objects.create(user=viewer, spinaz=1000)
        SondayPermission.objects.create(
            board=self.board,
            user=viewer,
            role=SondayPermission.ROLE_VIEWER
        )

        self.client.force_authenticate(user=viewer)
        data = {
            "key": "archive",
            "label": "Archive",
            "position": 99
        }
        response = self.client.post(f"/api/economy/sonday/{self.board.id}/add_column/", data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class SondayCardTests(APITestCase):
    """Test card management and activity logging."""

    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.owner, tier=TIER_PREMIUM)
        Wallet.objects.create(user=self.owner, spinaz=1000)

        self.board = SondayBoard.objects.create(
            user=self.owner,
            name="Test Board",
            is_public=False
        )

        self.draft_col = SondayColumn.objects.create(
            board=self.board, key="draft", label="Draft", position=0, is_default=True
        )
        self.in_progress_col = SondayColumn.objects.create(
            board=self.board, key="inprogress", label="In Progress", position=1, is_default=True
        )

    def test_create_card(self):
        """Owner can create a card in a column."""
        self.client.force_authenticate(user=self.owner)
        data = {
            "board_id": self.board.id,
            "column_id": self.draft_col.id,
            "title": "Record vocals",
            "description": "Record new vocals for the track"
        }
        response = self.client.post("/api/economy/sonday/cards/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Record vocals")
        self.assertEqual(response.data["created_by_display"], self.owner.username)

    def test_card_has_activity_log(self):
        """Card creation is logged in activity."""
        self.client.force_authenticate(user=self.owner)
        data = {
            "board_id": self.board.id,
            "column_id": self.draft_col.id,
            "title": "Mix track",
            "description": "Mix the final version"
        }
        response = self.client.post("/api/economy/sonday/cards/", data)
        card_id = response.data["id"]

        # Check activity log
        card = SondayCard.objects.get(id=card_id)
        activities = card.activities.all()
        self.assertEqual(activities.count(), 1)
        self.assertEqual(activities[0].action, SondayActivity.ACTION_CREATED)
        self.assertEqual(activities[0].to_column, "draft")

    def test_move_card_to_different_column(self):
        """Owner can move a card to a different column."""
        # Create a card through the API to get activity log
        self.client.force_authenticate(user=self.owner)
        create_data = {
            "board_id": self.board.id,
            "column_id": self.draft_col.id,
            "title": "Test card to move"
        }
        create_response = self.client.post("/api/economy/sonday/cards/", create_data)
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        card_id = create_response.data["id"]

        # Move the card
        move_data = {
            "column_id": self.in_progress_col.id,
            "position": 0
        }
        response = self.client.post(f"/api/economy/sonday/cards/{card_id}/move/", move_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["column"], self.in_progress_col.id)

        # Check activity was logged
        card = SondayCard.objects.get(id=card_id)
        activities = list(card.activities.all().order_by("id"))
        self.assertEqual(len(activities), 2)  # created + moved

        # First activity should be creation
        self.assertEqual(activities[0].action, SondayActivity.ACTION_CREATED)

        # Second activity should be move
        move_activity = activities[1]
        self.assertEqual(move_activity.action, SondayActivity.ACTION_MOVED)
        self.assertEqual(move_activity.from_column, "draft")
        self.assertEqual(move_activity.to_column, "inprogress")

    def test_viewer_cannot_create_card(self):
        """Viewer cannot create cards (no write access)."""
        viewer = User.objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=viewer, tier=TIER_FREE)
        Wallet.objects.create(user=viewer, spinaz=1000)
        SondayPermission.objects.create(
            board=self.board,
            user=viewer,
            role=SondayPermission.ROLE_VIEWER
        )

        self.client.force_authenticate(user=viewer)
        data = {
            "board_id": self.board.id,
            "column_id": self.draft_col.id,
            "title": "New card",
            "description": "Test"
        }
        response = self.client.post("/api/economy/sonday/cards/", data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class SondayPermissionTests(APITestCase):
    """Test collaborator management."""

    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.owner, tier=TIER_PREMIUM)
        Wallet.objects.create(user=self.owner, spinaz=1000)

        self.collaborator = User.objects.create_user(
            username="collab",
            email="collab@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.collaborator, tier=TIER_FREE)
        Wallet.objects.create(user=self.collaborator, spinaz=1000)

        self.board = SondayBoard.objects.create(
            user=self.owner,
            name="Test Board",
            is_public=False
        )
        SondayColumn.objects.create(board=self.board, key="draft", label="Draft", position=0, is_default=True)

    def test_owner_can_invite_user(self):
        """Owner can invite a user as editor."""
        self.client.force_authenticate(user=self.owner)
        data = {
            "user_id": self.collaborator.id,
            "role": SondayPermission.ROLE_EDITOR
        }
        response = self.client.post(f"/api/economy/sonday/{self.board.id}/invite_user/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["role"], SondayPermission.ROLE_EDITOR)

        # Verify permission was created
        perm = SondayPermission.objects.get(board=self.board, user=self.collaborator)
        self.assertEqual(perm.role, SondayPermission.ROLE_EDITOR)

    def test_non_owner_cannot_invite_user(self):
        """Non-owner cannot invite users."""
        editor = User.objects.create_user(
            username="editor",
            email="editor@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=editor, tier=TIER_FREE)
        Wallet.objects.create(user=editor, spinaz=1000)
        SondayPermission.objects.create(
            board=self.board,
            user=editor,
            role=SondayPermission.ROLE_EDITOR
        )

        self.client.force_authenticate(user=editor)
        data = {
            "user_id": self.collaborator.id,
            "role": SondayPermission.ROLE_EDITOR
        }
        response = self.client.post(f"/api/economy/sonday/{self.board.id}/invite_user/", data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_list_permissions(self):
        """Owner can view all collaborators on board."""
        SondayPermission.objects.create(
            board=self.board,
            user=self.collaborator,
            role=SondayPermission.ROLE_EDITOR
        )

        self.client.force_authenticate(user=self.owner)
        response = self.client.get(f"/api/economy/sonday/{self.board.id}/permissions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["role"], SondayPermission.ROLE_EDITOR)

    def test_non_owner_cannot_list_permissions(self):
        """Non-owner cannot view collaborators."""
        SondayPermission.objects.create(
            board=self.board,
            user=self.collaborator,
            role=SondayPermission.ROLE_EDITOR
        )

        self.client.force_authenticate(user=self.collaborator)
        response = self.client.get(f"/api/economy/sonday/{self.board.id}/permissions/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class SondayBoardListTests(APITestCase):
    """Test board listing and queryset filtering."""

    def setUp(self):
        self.client = APIClient()
        self.user1 = User.objects.create_user(
            username="user1",
            email="user1@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.user1, tier=TIER_PREMIUM)
        Wallet.objects.create(user=self.user1, spinaz=1000)

        self.user2 = User.objects.create_user(
            username="user2",
            email="user2@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.user2, tier=TIER_PREMIUM)
        Wallet.objects.create(user=self.user2, spinaz=1000)

        # User1's private board
        self.private_board = SondayBoard.objects.create(
            user=self.user1,
            name="Private Board",
            is_public=False
        )
        SondayColumn.objects.create(board=self.private_board, key="draft", label="Draft", position=0, is_default=True)

        # Shared board (User2 is editor)
        self.shared_board = SondayBoard.objects.create(
            user=self.user2,
            name="Shared Board",
            is_public=False
        )
        SondayColumn.objects.create(board=self.shared_board, key="draft", label="Draft", position=0, is_default=True)
        SondayPermission.objects.create(
            board=self.shared_board,
            user=self.user1,
            role=SondayPermission.ROLE_EDITOR
        )

        # Public board
        self.public_board = SondayBoard.objects.create(
            user=self.user2,
            name="Public Board",
            is_public=True
        )
        SondayColumn.objects.create(board=self.public_board, key="draft", label="Draft", position=0, is_default=True)

    def test_user_sees_owned_boards(self):
        """User sees boards they own."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get("/api/economy/sonday/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Check that owned board is in the response
        # Response data may be paginated or a list
        boards_data = response.data.get("results", response.data) if isinstance(response.data, dict) else response.data
        board_ids = [b["id"] for b in boards_data]
        self.assertIn(self.private_board.id, board_ids)

    def test_soft_delete_excludes_board(self):
        """Soft-deleted boards are not returned in list."""
        self.client.force_authenticate(user=self.user1)
        # Soft-delete the private board
        self.private_board.deleted_at = timezone.now()
        self.private_board.save()

        response = self.client.get("/api/economy/sonday/")
        boards_data = response.data.get("results", response.data) if isinstance(response.data, dict) else response.data
        board_ids = [b["id"] for b in boards_data]
        self.assertNotIn(self.private_board.id, board_ids)


class SondayCardCrossPollinationTests(APITestCase):
    """Test cross-pollination linking."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="user",
            email="user@example.com",
            password="pw12345!"
        )
        Membership.objects.create(user=self.user, tier=TIER_PREMIUM)
        Wallet.objects.create(user=self.user, spinaz=1000)

        self.board = SondayBoard.objects.create(
            user=self.user,
            name="Test Board",
            is_public=False
        )
        self.column = SondayColumn.objects.create(
            board=self.board, key="draft", label="Draft", position=0, is_default=True
        )

    def test_card_can_link_to_external_resource(self):
        """Card can link to an external resource (take, post, collab)."""
        self.client.force_authenticate(user=self.user)
        data = {
            "board_id": self.board.id,
            "column_id": self.column.id,
            "title": "Review beat",
            "linked_app_key": "beatz",
            "linked_target": "beatz:123"
        }
        response = self.client.post("/api/economy/sonday/cards/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["linked_app_key"], "beatz")
        self.assertEqual(response.data["linked_target"], "beatz:123")


from django.utils import timezone


class SondayCardsBelongToTheirBoardTests(APITestCase):
    """The hole this screen could not ship on top of.

    Card read/edit/delete checked nothing — a stranger could read, rewrite and
    hard-delete a card on somebody else's private board by id (200, 200, 204).
    """

    def setUp(self):
        self.owner = User.objects.create_user("owner_s", "o@e.com", "pw12345!")
        self.stranger = User.objects.create_user("stranger_s", "s@e.com", "pw12345!")
        self.viewer = User.objects.create_user("viewer_s", "v@e.com", "pw12345!")
        self.board = SondayBoard.objects.create(user=self.owner, name="secret")
        self.col = SondayColumn.objects.create(board=self.board, key="draft", label="Draft", position=0)
        self.col2 = SondayColumn.objects.create(board=self.board, key="done", label="Done", position=1)
        self.card = SondayCard.objects.create(board=self.board, column=self.col, title="private card")
        SondayPermission.objects.create(board=self.board, user=self.viewer, role=SondayPermission.ROLE_VIEWER)

    def as_(self, who):
        c = APIClient(); c.force_authenticate(who); return c

    def url(self):
        return f"/api/economy/sonday/cards/{self.card.id}/"

    def test_a_stranger_cannot_read_it(self):
        self.assertEqual(self.as_(self.stranger).get(self.url()).status_code, 404)

    def test_a_stranger_cannot_edit_it(self):
        r = self.as_(self.stranger).patch(self.url(), {"title": "pwned"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(SondayCard.objects.get(pk=self.card.pk).title, "private card")

    def test_a_stranger_cannot_delete_it(self):
        self.assertEqual(self.as_(self.stranger).delete(self.url()).status_code, 404)
        self.assertIsNone(SondayCard.objects.get(pk=self.card.pk).deleted_at)

    def test_a_viewer_can_read_but_not_write(self):
        v = self.as_(self.viewer)
        self.assertEqual(v.get(self.url()).status_code, 200)
        self.assertEqual(v.patch(self.url(), {"title": "x"}, format="json").status_code, 403)
        self.assertEqual(v.delete(self.url()).status_code, 403)

    def test_the_owner_edits_and_it_is_logged(self):
        r = self.as_(self.owner).patch(self.url(), {"title": "renamed", "color": "cyan",
                                                    "due_date": "2026-12-01"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["title"], "renamed")
        self.assertEqual(r.data["due_date"], "2026-12-01")
        self.assertTrue(SondayActivity.objects.filter(card=self.card, action="updated").exists())

    def test_delete_is_soft_and_keeps_the_history(self):
        self.assertEqual(self.as_(self.owner).delete(self.url()).status_code, 204)
        card = SondayCard.objects.get(pk=self.card.pk)
        self.assertIsNotNone(card.deleted_at)
        self.assertTrue(SondayActivity.objects.filter(card=card, action="deleted").exists())
        board = self.as_(self.owner).get(f"/api/economy/sonday/{self.board.id}/").data
        self.assertEqual(board["cards"], [])

    def test_a_card_cannot_move_into_another_boards_column(self):
        other = SondayBoard.objects.create(user=self.owner, name="other")
        foreign = SondayColumn.objects.create(board=other, key="x", label="X")
        r = self.as_(self.owner).post(f"{self.url()}move/", {"column_id": foreign.id}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_a_bad_colour_or_date_is_refused_not_stored(self):
        o = self.as_(self.owner)
        self.assertEqual(o.patch(self.url(), {"color": "<script>"}, format="json").status_code, 400)
        self.assertEqual(o.patch(self.url(), {"due_date": "tomorrow"}, format="json").status_code, 400)

    def test_a_private_board_reads_as_missing_to_a_stranger(self):
        r = self.as_(self.stranger).get(f"/api/economy/sonday/{self.board.id}/")
        self.assertEqual(r.status_code, 404)


class SondayBoardRulesTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner_b", "o@e.com", "pw12345!")
        self.editor = User.objects.create_user("editor_b", "e@e.com", "pw12345!")
        self.board = SondayBoard.objects.create(user=self.owner, name="b")
        self.col = SondayColumn.objects.create(board=self.board, key="draft", label="Draft", position=0)
        self.col2 = SondayColumn.objects.create(board=self.board, key="done", label="Done", position=1)
        SondayPermission.objects.create(board=self.board, user=self.editor, role=SondayPermission.ROLE_EDITOR)

    def as_(self, who):
        c = APIClient(); c.force_authenticate(who); return c

    def test_only_the_owner_publishes_a_board(self):
        r = self.as_(self.editor).patch(f"/api/economy/sonday/{self.board.id}/", {"is_public": True}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.as_(self.owner).patch(f"/api/economy/sonday/{self.board.id}/", {"is_public": True}, format="json")
        self.assertTrue(r.data["is_public"])

    def test_only_the_owner_deletes_and_it_is_soft(self):
        self.assertEqual(self.as_(self.editor).delete(f"/api/economy/sonday/{self.board.id}/").status_code, 403)
        self.assertEqual(self.as_(self.owner).delete(f"/api/economy/sonday/{self.board.id}/").status_code, 204)
        self.assertIsNotNone(SondayBoard.objects.get(pk=self.board.pk).deleted_at)

    def test_invite_by_username_and_the_invitee_is_told(self):
        from apps.economy.models import Notification
        friend = User.objects.create_user("friend_b", "f@e.com", "pw12345!")
        r = self.as_(self.owner).post(f"/api/economy/sonday/{self.board.id}/invite_user/",
                                      {"username": "@friend_b", "role": "viewer"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(Notification.objects.filter(user=friend).exists())

    def test_a_collaborator_can_leave(self):
        r = self.as_(self.editor).delete(f"/api/economy/sonday/{self.board.id}/members/{self.editor.id}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(SondayPermission.objects.filter(user=self.editor).exists())

    def test_deleting_a_column_moves_its_cards_rather_than_orphaning_them(self):
        card = SondayCard.objects.create(board=self.board, column=self.col2, title="t")
        r = self.as_(self.owner).delete(f"/api/economy/sonday/{self.board.id}/columns/{self.col2.id}/")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(SondayCard.objects.get(pk=card.pk).column_id, self.col.id)

    def test_the_last_column_cannot_go(self):
        self.as_(self.owner).delete(f"/api/economy/sonday/{self.board.id}/columns/{self.col2.id}/")
        r = self.as_(self.owner).delete(f"/api/economy/sonday/{self.board.id}/columns/{self.col.id}/")
        self.assertEqual(r.status_code, 400)

    def test_a_column_key_is_derived_from_the_label(self):
        r = self.as_(self.owner).post(f"/api/economy/sonday/{self.board.id}/add_column/",
                                      {"label": "Mixing & Mastering"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["key"], "mixingmastering")

    def test_a_linked_card_carries_where_it_opens(self):
        o = self.as_(self.owner)
        r = o.post("/api/economy/sonday/cards/", {"board_id": self.board.id, "title": "Master it",
                                                  "linked_target": "/p/12"}, format="json")
        self.assertEqual(r.data["open_in"], {"url": "/p/12"})
        self.assertEqual(r.data["column"], self.col.id)  # no column given → the first one
        r = o.post("/api/economy/sonday/cards/", {"board_id": self.board.id, "title": "Fund it",
                                                  "linked_app_key": "collabz", "linked_target": "collabz-deals"},
                   format="json")
        self.assertEqual(r.data["open_in"], {"tab": "collabz", "target": "collabz-deals"})

    def test_the_board_does_not_cost_a_query_per_card(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        o = self.as_(self.owner)
        url = f"/api/economy/sonday/{self.board.id}/"
        SondayCard.objects.create(board=self.board, column=self.col, title="a")
        o.get(url)
        with CaptureQueriesContext(connection) as few:
            o.get(url)
        for i in range(8):
            SondayCard.objects.create(board=self.board, column=self.col, title=f"c{i}")
        with CaptureQueriesContext(connection) as many:
            o.get(url)
        self.assertEqual(len(few.captured_queries), len(many.captured_queries))
