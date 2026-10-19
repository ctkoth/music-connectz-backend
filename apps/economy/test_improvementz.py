"""Tests for Gap 3 — Improvement Loop (goals, drills, accountability)."""
from datetime import timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from .models import Goal, DrillPrescription, GoalProgress, AccountabilityGroup, AccountabilityGroupMember, Call, Membership, Wallet, TIER_FREE

User = get_user_model()


class GoalTests(TestCase):
    """Test goal creation and management."""

    def setUp(self):
        self.member = User.objects.create_user(
            username="member", email="member@test.com", password="pw"
        )
        Membership.objects.create(user=self.member, tier=TIER_FREE)
        Wallet.objects.create(user=self.member)

        self.coach = User.objects.create_user(
            username="coach", email="coach@test.com", password="pw"
        )
        Membership.objects.create(user=self.coach, tier=TIER_FREE)
        Wallet.objects.create(user=self.coach)

        self.client = APIClient()

    def test_create_goal(self):
        """Test creating a new goal."""
        self.client.force_authenticate(user=self.member)
        response = self.client.post("/api/economy/improvementz/goals/", {
            "title": "Hit high C",
            "description": "Nail the high C in my solo",
            "app_key": "singz",
            "target_metric": "5 times in a row",
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Hit high C")
        self.assertEqual(response.data["status"], "active")

        goal = Goal.objects.get(id=response.data["id"])
        self.assertEqual(goal.member, self.member)
        self.assertEqual(goal.app_key, "singz")

    def test_get_goals(self):
        """Test listing member's goals."""
        goal1 = Goal.objects.create(
            member=self.member,
            app_key="singz",
            title="Goal 1",
            target_metric="10 times"
        )
        goal2 = Goal.objects.create(
            member=self.member,
            app_key="rapz",
            title="Goal 2",
            target_metric="5 minutes"
        )

        self.client.force_authenticate(user=self.member)
        response = self.client.get("/api/economy/improvementz/goals/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["goals"]), 2)

    def test_filter_goals_by_app_key(self):
        """Test filtering goals by app_key."""
        Goal.objects.create(
            member=self.member,
            app_key="singz",
            title="Sing Goal",
            target_metric="10 times"
        )
        Goal.objects.create(
            member=self.member,
            app_key="rapz",
            title="Rap Goal",
            target_metric="5 minutes"
        )

        self.client.force_authenticate(user=self.member)
        response = self.client.get("/api/economy/improvementz/goals/?app_key=singz")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["goals"]), 1)
        self.assertEqual(response.data["goals"][0]["app_key"], "singz")

    def test_filter_goals_by_status(self):
        """Test filtering goals by status."""
        active_goal = Goal.objects.create(
            member=self.member,
            title="Active Goal",
            target_metric="10 times",
            status=Goal.STATUS_ACTIVE
        )
        completed_goal = Goal.objects.create(
            member=self.member,
            title="Completed Goal",
            target_metric="5 times",
            status=Goal.STATUS_COMPLETED,
            completed_at=timezone.now()
        )

        self.client.force_authenticate(user=self.member)
        response = self.client.get("/api/economy/improvementz/goals/?status=active")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["goals"]), 1)
        self.assertEqual(response.data["goals"][0]["status"], "active")

    def test_complete_goal(self):
        """Test marking goal as complete."""
        goal = Goal.objects.create(
            member=self.member,
            title="Goal",
            target_metric="10 times",
            status=Goal.STATUS_ACTIVE
        )

        self.client.force_authenticate(user=self.member)
        response = self.client.post(f"/api/economy/improvementz/goals/{goal.id}/", {
            "action": "complete"
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "completed")

        goal.refresh_from_db()
        self.assertEqual(goal.status, Goal.STATUS_COMPLETED)
        self.assertIsNotNone(goal.completed_at)

    def test_abandon_goal(self):
        """Test abandoning a goal."""
        goal = Goal.objects.create(
            member=self.member,
            title="Goal",
            target_metric="10 times",
            status=Goal.STATUS_ACTIVE
        )

        self.client.force_authenticate(user=self.member)
        response = self.client.post(f"/api/economy/improvementz/goals/{goal.id}/", {
            "action": "abandon"
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "abandoned")

        goal.refresh_from_db()
        self.assertEqual(goal.status, Goal.STATUS_ABANDONED)
        self.assertIsNotNone(goal.abandoned_at)

    def test_update_goal(self):
        """Test updating goal details."""
        goal = Goal.objects.create(
            member=self.member,
            title="Old Title",
            description="Old description",
            target_metric="10 times"
        )

        self.client.force_authenticate(user=self.member)
        response = self.client.patch(f"/api/economy/improvementz/goals/{goal.id}/", {
            "title": "New Title",
            "description": "New description"
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "New Title")
        self.assertEqual(response.data["description"], "New description")

    def test_cannot_access_others_goal(self):
        """Test that member cannot access another's goal."""
        other_member = User.objects.create_user(
            username="other", email="other@test.com", password="pw"
        )
        Membership.objects.create(user=other_member, tier=TIER_FREE)
        Wallet.objects.create(user=other_member)

        goal = Goal.objects.create(
            member=other_member,
            title="Goal",
            target_metric="10 times"
        )

        self.client.force_authenticate(user=self.member)
        response = self.client.get(f"/api/economy/improvementz/goals/{goal.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class DrillPrescriptionTests(TestCase):
    """Test drill prescriptions."""

    def setUp(self):
        self.coach = User.objects.create_user(
            username="coach", email="coach@test.com", password="pw"
        )
        Membership.objects.create(user=self.coach, tier=TIER_FREE)
        Wallet.objects.create(user=self.coach)

        self.student = User.objects.create_user(
            username="student", email="student@test.com", password="pw"
        )
        Membership.objects.create(user=self.student, tier=TIER_FREE)
        Wallet.objects.create(user=self.student)

        self.client = APIClient()

    def test_coach_prescribe_drill(self):
        """Test coach prescribing a drill."""
        self.client.force_authenticate(user=self.coach)
        response = self.client.post("/api/economy/improvementz/drills/", {
            "student_id": self.student.id,
            "drill_type": "pitch_accuracy",
            "instructions": "Work on hitting the target pitch consistently",
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["drill_type"], "pitch_accuracy")
        self.assertEqual(response.data["coach_id"], self.coach.id)

    def test_prescribe_drill_with_call(self):
        """Test prescribing a drill linked to a specific call."""
        call = Call.objects.create(
            caller=self.student,
            callee=self.coach,
            status=Call.STATUS_ENDED,
            rate_cents_per_min=100,
            billed_seconds=600
        )

        self.client.force_authenticate(user=self.coach)
        response = self.client.post("/api/economy/improvementz/drills/", {
            "student_id": self.student.id,
            "call_id": call.id,
            "drill_type": "timing",
            "instructions": "Stay on beat",
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        drill = DrillPrescription.objects.get(id=response.data["id"])
        self.assertEqual(drill.call_id, call.id)

    def test_student_list_drills(self):
        """Test student listing prescribed drills."""
        DrillPrescription.objects.create(
            coach=self.coach,
            student=self.student,
            drill_type="pitch_accuracy",
            instructions="Work on pitch"
        )
        DrillPrescription.objects.create(
            coach=self.coach,
            student=self.student,
            drill_type="timing",
            instructions="Stay on beat"
        )

        self.client.force_authenticate(user=self.student)
        response = self.client.get("/api/economy/improvementz/drills/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["drills"]), 2)

    def test_filter_drills_by_completion(self):
        """Test filtering drills by completion status."""
        completed_drill = DrillPrescription.objects.create(
            coach=self.coach,
            student=self.student,
            drill_type="pitch_accuracy",
            is_completed=True,
            completed_at=timezone.now()
        )
        pending_drill = DrillPrescription.objects.create(
            coach=self.coach,
            student=self.student,
            drill_type="timing",
            is_completed=False
        )

        self.client.force_authenticate(user=self.student)
        response = self.client.get("/api/economy/improvementz/drills/?is_completed=false")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["drills"]), 1)
        self.assertEqual(response.data["drills"][0]["drill_type"], "timing")

    def test_student_complete_drill(self):
        """Test student marking drill as completed."""
        drill = DrillPrescription.objects.create(
            coach=self.coach,
            student=self.student,
            drill_type="pitch_accuracy",
            is_completed=False
        )

        self.client.force_authenticate(user=self.student)
        response = self.client.post(f"/api/economy/improvementz/drills/{drill.id}/complete/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_completed"])

        drill.refresh_from_db()
        self.assertTrue(drill.is_completed)
        self.assertIsNotNone(drill.completed_at)

    def test_cannot_prescribe_for_other_coach(self):
        """Test that only the lesson coach can prescribe drills for a call."""
        other_coach = User.objects.create_user(
            username="other_coach", email="other@test.com", password="pw"
        )
        Membership.objects.create(user=other_coach, tier=TIER_FREE)
        Wallet.objects.create(user=other_coach)

        call = Call.objects.create(
            caller=self.student,
            callee=self.coach,
            status=Call.STATUS_ENDED,
            rate_cents_per_min=100
        )

        self.client.force_authenticate(user=other_coach)
        response = self.client.post("/api/economy/improvementz/drills/", {
            "student_id": self.student.id,
            "call_id": call.id,
            "drill_type": "timing",
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AccountabilityGroupTests(TestCase):
    """Test accountability groups."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner", email="owner@test.com", password="pw"
        )
        Membership.objects.create(user=self.owner, tier=TIER_FREE)
        Wallet.objects.create(user=self.owner)

        self.member1 = User.objects.create_user(
            username="member1", email="member1@test.com", password="pw"
        )
        Membership.objects.create(user=self.member1, tier=TIER_FREE)
        Wallet.objects.create(user=self.member1)

        self.member2 = User.objects.create_user(
            username="member2", email="member2@test.com", password="pw"
        )
        Membership.objects.create(user=self.member2, tier=TIER_FREE)
        Wallet.objects.create(user=self.member2)

        self.client = APIClient()

    def test_create_group(self):
        """Test creating an accountability group."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.post("/api/economy/improvementz/groups/", {
            "name": "Vocal Improvement Squad",
            "description": "Let's get better at singing together",
            "app_key": "singz",
            "is_public": True
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Vocal Improvement Squad")
        self.assertEqual(response.data["member_count"], 1)  # Owner is auto-member

        group = AccountabilityGroup.objects.get(id=response.data["id"])
        self.assertEqual(group.owner, self.owner)
        self.assertTrue(group.members.filter(member=self.owner).exists())

    def test_list_groups(self):
        """Test listing public groups."""
        group = AccountabilityGroup.objects.create(
            name="Group",
            owner=self.owner,
            app_key="singz",
            is_public=True
        )
        AccountabilityGroupMember.objects.create(group=group, member=self.owner)

        self.client.force_authenticate(user=self.member1)
        response = self.client.get("/api/economy/improvementz/groups/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["groups"]), 1)
        self.assertFalse(response.data["groups"][0]["is_member"])

    def test_join_public_group(self):
        """Test joining a public group."""
        group = AccountabilityGroup.objects.create(
            name="Public Group",
            owner=self.owner,
            app_key="singz",
            is_public=True
        )
        AccountabilityGroupMember.objects.create(group=group, member=self.owner)

        self.client.force_authenticate(user=self.member1)
        response = self.client.post(f"/api/economy/improvementz/groups/{group.id}/", {
            "action": "join"
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(group.members.filter(member=self.member1).exists())

    def test_cannot_join_private_group(self):
        """Test that non-owner cannot join private group."""
        group = AccountabilityGroup.objects.create(
            name="Private Group",
            owner=self.owner,
            app_key="singz",
            is_public=False
        )
        AccountabilityGroupMember.objects.create(group=group, member=self.owner)

        self.client.force_authenticate(user=self.member1)
        response = self.client.post(f"/api/economy/improvementz/groups/{group.id}/", {
            "action": "join"
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_leave_group(self):
        """Test leaving a group."""
        group = AccountabilityGroup.objects.create(
            name="Group",
            owner=self.owner,
            app_key="singz",
            is_public=True
        )
        AccountabilityGroupMember.objects.create(group=group, member=self.owner)
        AccountabilityGroupMember.objects.create(group=group, member=self.member1)

        self.client.force_authenticate(user=self.member1)
        response = self.client.post(f"/api/economy/improvementz/groups/{group.id}/", {
            "action": "leave"
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(group.members.filter(member=self.member1).exists())

    def test_owner_cannot_leave_group(self):
        """Test that owner cannot leave their own group."""
        group = AccountabilityGroup.objects.create(
            name="Group",
            owner=self.owner,
            app_key="singz"
        )
        AccountabilityGroupMember.objects.create(group=group, member=self.owner)

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(f"/api/economy/improvementz/groups/{group.id}/", {
            "action": "leave"
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_group_details(self):
        """Test getting group details and members."""
        group = AccountabilityGroup.objects.create(
            name="Group",
            description="A group for accountability",
            owner=self.owner,
            app_key="singz",
            is_public=True
        )
        AccountabilityGroupMember.objects.create(group=group, member=self.owner)
        AccountabilityGroupMember.objects.create(group=group, member=self.member1)

        self.client.force_authenticate(user=self.member2)
        response = self.client.get(f"/api/economy/improvementz/groups/{group.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Group")
        self.assertEqual(response.data["member_count"], 2)
        self.assertEqual(len(response.data["members"]), 2)
        self.assertFalse(response.data["is_member"])

    def test_filter_groups_by_app_key(self):
        """Test filtering groups by app_key."""
        singz_group = AccountabilityGroup.objects.create(
            name="Singing Group",
            owner=self.owner,
            app_key="singz",
            is_public=True
        )
        rapz_group = AccountabilityGroup.objects.create(
            name="Rapping Group",
            owner=self.owner,
            app_key="rapz",
            is_public=True
        )
        AccountabilityGroupMember.objects.create(group=singz_group, member=self.owner)
        AccountabilityGroupMember.objects.create(group=rapz_group, member=self.owner)

        self.client.force_authenticate(user=self.member1)
        response = self.client.get("/api/economy/improvementz/groups/?app_key=singz")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["groups"]), 1)
        self.assertEqual(response.data["groups"][0]["app_key"], "singz")
