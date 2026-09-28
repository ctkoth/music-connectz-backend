"""Gap 3: Improvement Loop — goal tracking, drill prescriptions, accountability.

The improvement loop creates a virtuous cycle: members set goals, coaches
prescribe targeted drills, peer accountability groups keep engagement high,
and the resulting stronger performances feed back into discovery and content
quality. Discovery depends on taste; taste depends on signals from takes that
have been coached and drilled.

Three affordances:

  * Goals are keyed by (member, app_key) so a coach in SingZ sees only
    singing goals, not drumming ones. A member working on both instruments
    keeps separate goal lists.
  * Drill prescriptions are given AFTER a lesson ends, so a coach has heard
    the member's performance and can prescribe what they heard they needed.
    A prescription expires when the member marks it complete, not after a time.
  * Accountability groups are peer-driven: members join to hold each other
    accountable for their practice, with visible progress so the group can
    celebrate wins and spot where somebody is stuck.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes

from .models import Goal, DrillPrescription, GoalProgress, AccountabilityGroup, AccountabilityGroupMember, Call

User = get_user_model()


class GoalListView(APIView):
    """GET /api/economy/improvementz/goals/ — list member's goals.
    POST /api/economy/improvementz/goals/ — create a new goal.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get all goals for the member, optionally filtered by app_key and status."""
        app_key = request.query_params.get("app_key")
        status_filter = request.query_params.get("status")

        goals = Goal.objects.filter(member=request.user)

        if app_key:
            goals = goals.filter(app_key=app_key)

        if status_filter:
            if status_filter not in ["active", "completed", "abandoned"]:
                return Response(
                    {"status": "Invalid status. Must be active, completed, or abandoned."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            goals = goals.filter(status=status_filter)

        return Response({
            "goals": [
                {
                    "id": g.id,
                    "app_key": g.app_key,
                    "title": g.title,
                    "description": g.description,
                    "target_metric": g.target_metric,
                    "progress_so_far": g.progress_so_far,
                    "status": g.status,
                    "created_at": g.created_at,
                    "completed_at": g.completed_at,
                    "abandoned_at": g.abandoned_at,
                }
                for g in goals
            ]
        })

    def post(self, request):
        """Create a new goal."""
        title = request.data.get("title")
        description = request.data.get("description", "")
        app_key = request.data.get("app_key", "singz")
        target_metric = request.data.get("target_metric")

        if not title:
            return Response(
                {"title": "Required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not target_metric:
            return Response(
                {"target_metric": "Required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        goal = Goal.objects.create(
            member=request.user,
            title=title,
            description=description,
            app_key=app_key,
            target_metric=target_metric,
            status=Goal.STATUS_ACTIVE
        )

        return Response({
            "id": goal.id,
            "app_key": goal.app_key,
            "title": goal.title,
            "description": goal.description,
            "target_metric": goal.target_metric,
            "progress_so_far": goal.progress_so_far,
            "status": goal.status,
            "created_at": goal.created_at,
        }, status=status.HTTP_201_CREATED)


class GoalDetailView(APIView):
    """GET /api/economy/improvementz/goals/<goal_id>/ — get goal details.
    PATCH /api/economy/improvementz/goals/<goal_id>/ — update goal.
    POST /api/economy/improvementz/goals/<goal_id>/complete/ — mark goal as complete.
    POST /api/economy/improvementz/goals/<goal_id>/abandon/ — abandon goal.
    """
    permission_classes = [IsAuthenticated]

    def get_goal(self, goal_id, user):
        """Get goal if it belongs to the user."""
        try:
            goal = Goal.objects.get(id=goal_id, member=user)
        except Goal.DoesNotExist:
            return None
        return goal

    def get(self, request, goal_id):
        """Get goal details with progress entries."""
        goal = self.get_goal(goal_id, request.user)
        if not goal:
            return Response(
                {"detail": "Goal not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        progress_entries = GoalProgress.objects.filter(goal=goal)

        return Response({
            "id": goal.id,
            "app_key": goal.app_key,
            "title": goal.title,
            "description": goal.description,
            "target_metric": goal.target_metric,
            "progress_so_far": goal.progress_so_far,
            "status": goal.status,
            "created_at": goal.created_at,
            "completed_at": goal.completed_at,
            "abandoned_at": goal.abandoned_at,
            "progress_entries": [
                {
                    "id": p.id,
                    "improvement_amount": p.improvement_amount,
                    "recorded_at": p.recorded_at,
                    "drill_take_id": p.drill_take_id,
                    "practice_session_id": p.practice_session_id,
                }
                for p in progress_entries
            ]
        })

    def patch(self, request, goal_id):
        """Update goal details."""
        goal = self.get_goal(goal_id, request.user)
        if not goal:
            return Response(
                {"detail": "Goal not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if "title" in request.data:
            goal.title = request.data["title"]
        if "description" in request.data:
            goal.description = request.data["description"]
        if "target_metric" in request.data:
            goal.target_metric = request.data["target_metric"]

        goal.save()

        return Response({
            "id": goal.id,
            "app_key": goal.app_key,
            "title": goal.title,
            "description": goal.description,
            "target_metric": goal.target_metric,
            "progress_so_far": goal.progress_so_far,
            "status": goal.status,
            "updated_at": goal.updated_at if hasattr(goal, 'updated_at') else timezone.now(),
        })

    def post(self, request, goal_id):
        """Complete or abandon goal based on action parameter."""
        goal = self.get_goal(goal_id, request.user)
        if not goal:
            return Response(
                {"detail": "Goal not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        action = request.data.get("action")

        if action == "complete":
            goal.status = Goal.STATUS_COMPLETED
            goal.completed_at = timezone.now()
            goal.save()
            return Response({
                "id": goal.id,
                "status": goal.status,
                "completed_at": goal.completed_at,
            })

        elif action == "abandon":
            goal.status = Goal.STATUS_ABANDONED
            goal.abandoned_at = timezone.now()
            goal.save()
            return Response({
                "id": goal.id,
                "status": goal.status,
                "abandoned_at": goal.abandoned_at,
            })

        else:
            return Response(
                {"action": "Must be 'complete' or 'abandon'"},
                status=status.HTTP_400_BAD_REQUEST
            )


class DrillPrescriptionListView(APIView):
    """GET /api/economy/improvementz/drills/ — list prescriptions for member.
    POST /api/economy/improvementz/drills/ — coach prescribes a drill (after lesson).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List drills prescribed to the member, optionally filtered by completion status."""
        is_completed = request.query_params.get("is_completed")

        drills = DrillPrescription.objects.filter(student=request.user)

        if is_completed is not None:
            is_completed_bool = is_completed.lower() == "true"
            drills = drills.filter(is_completed=is_completed_bool)

        return Response({
            "drills": [
                {
                    "id": d.id,
                    "coach_id": d.coach_id,
                    "coach": d.coach.username,
                    "drill_type": d.drill_type,
                    "instructions": d.instructions,
                    "is_completed": d.is_completed,
                    "created_at": d.created_at,
                    "completed_at": d.completed_at,
                }
                for d in drills
            ]
        })

    def post(self, request):
        """Coach prescribes a drill to a student after a lesson.

        Body: {
            "student_id": <int>,
            "call_id": <int>,  # optional: links to the lesson this drill is for
            "drill_type": "<string>",
            "instructions": "<string>"
        }
        """
        student_id = request.data.get("student_id")
        call_id = request.data.get("call_id")
        drill_type = request.data.get("drill_type")
        instructions = request.data.get("instructions", "")

        if not student_id:
            return Response(
                {"student_id": "Required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not drill_type:
            return Response(
                {"drill_type": "Required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            student = User.objects.get(id=student_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "Student not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Verify the requester is the coach in the call (if call_id provided)
        call = None
        if call_id:
            try:
                call = Call.objects.get(id=call_id)
                if call.callee != request.user:
                    return Response(
                        {"detail": "Only the coach can prescribe drills for this call"},
                        status=status.HTTP_403_FORBIDDEN
                    )
            except Call.DoesNotExist:
                return Response(
                    {"detail": "Call not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        prescription = DrillPrescription.objects.create(
            coach=request.user,
            student=student,
            call=call,
            drill_type=drill_type,
            instructions=instructions
        )

        return Response({
            "id": prescription.id,
            "coach_id": prescription.coach_id,
            "student_id": prescription.student_id,
            "drill_type": prescription.drill_type,
            "instructions": prescription.instructions,
            "is_completed": prescription.is_completed,
            "created_at": prescription.created_at,
        }, status=status.HTTP_201_CREATED)


class DrillPrescriptionDetailView(APIView):
    """POST /api/economy/improvementz/drills/<drill_id>/complete/ — mark drill complete."""
    permission_classes = [IsAuthenticated]

    def post(self, request, drill_id):
        """Mark a prescribed drill as completed."""
        try:
            drill = DrillPrescription.objects.get(id=drill_id, student=request.user)
        except DrillPrescription.DoesNotExist:
            return Response(
                {"detail": "Drill prescription not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if drill.is_completed:
            return Response(
                {"detail": "Drill already completed"},
                status=status.HTTP_400_BAD_REQUEST
            )

        drill.is_completed = True
        drill.completed_at = timezone.now()
        drill.save()

        return Response({
            "id": drill.id,
            "is_completed": drill.is_completed,
            "completed_at": drill.completed_at,
        })


class AccountabilityGroupListView(APIView):
    """GET /api/economy/improvementz/groups/ — list accountability groups.
    POST /api/economy/improvementz/groups/ — create a new group.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List public groups and groups the member is in, optionally filtered by app_key."""
        app_key = request.query_params.get("app_key")

        # Get groups the member is already in
        member_groups = AccountabilityGroup.objects.filter(
            members__member=request.user
        )

        # Get public groups the member is not in
        public_groups = AccountabilityGroup.objects.filter(
            is_public=True
        ).exclude(members__member=request.user)

        groups = member_groups | public_groups

        if app_key:
            groups = groups.filter(app_key=app_key)

        groups = groups.distinct().order_by("-created_at")

        return Response({
            "groups": [
                {
                    "id": g.id,
                    "name": g.name,
                    "description": g.description,
                    "owner_id": g.owner_id,
                    "owner": g.owner.username,
                    "app_key": g.app_key,
                    "is_public": g.is_public,
                    "member_count": g.members.count(),
                    "is_member": g.members.filter(member=request.user).exists(),
                    "created_at": g.created_at,
                }
                for g in groups
            ]
        })

    def post(self, request):
        """Create a new accountability group."""
        name = request.data.get("name")
        description = request.data.get("description", "")
        app_key = request.data.get("app_key", "singz")
        is_public = request.data.get("is_public", True)

        if not name:
            return Response(
                {"name": "Required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        group = AccountabilityGroup.objects.create(
            name=name,
            description=description,
            owner=request.user,
            app_key=app_key,
            is_public=is_public
        )

        # Owner is automatically a member
        AccountabilityGroupMember.objects.create(
            group=group,
            member=request.user
        )

        return Response({
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "owner_id": group.owner_id,
            "app_key": group.app_key,
            "is_public": group.is_public,
            "member_count": 1,
            "created_at": group.created_at,
        }, status=status.HTTP_201_CREATED)


class AccountabilityGroupDetailView(APIView):
    """GET /api/economy/improvementz/groups/<group_id>/ — get group details.
    POST /api/economy/improvementz/groups/<group_id>/join/ — join a group.
    POST /api/economy/improvementz/groups/<group_id>/leave/ — leave a group.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        """Get group details and members."""
        try:
            group = AccountabilityGroup.objects.get(id=group_id)
        except AccountabilityGroup.DoesNotExist:
            return Response(
                {"detail": "Group not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        members = group.members.all()

        return Response({
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "owner_id": group.owner_id,
            "owner": group.owner.username,
            "app_key": group.app_key,
            "is_public": group.is_public,
            "member_count": members.count(),
            "is_member": members.filter(member=request.user).exists(),
            "members": [
                {
                    "id": m.member_id,
                    "username": m.member.username,
                    "joined_at": m.joined_at,
                }
                for m in members
            ],
            "created_at": group.created_at,
        })

    def post(self, request, group_id):
        """Join or leave a group based on action parameter."""
        try:
            group = AccountabilityGroup.objects.get(id=group_id)
        except AccountabilityGroup.DoesNotExist:
            return Response(
                {"detail": "Group not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        action = request.data.get("action")

        if action == "join":
            if group.members.filter(member=request.user).exists():
                return Response(
                    {"detail": "Already a member of this group"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not group.is_public and group.owner != request.user:
                return Response(
                    {"detail": "Cannot join private group without invitation"},
                    status=status.HTTP_403_FORBIDDEN
                )

            AccountabilityGroupMember.objects.create(
                group=group,
                member=request.user
            )

            return Response({
                "id": group.id,
                "name": group.name,
                "is_member": True,
                "member_count": group.members.count(),
            }, status=status.HTTP_201_CREATED)

        elif action == "leave":
            membership = group.members.filter(member=request.user).first()
            if not membership:
                return Response(
                    {"detail": "Not a member of this group"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if group.owner == request.user:
                return Response(
                    {"detail": "Owner cannot leave the group"},
                    status=status.HTTP_403_FORBIDDEN
                )

            membership.delete()

            return Response({
                "id": group.id,
                "is_member": False,
                "member_count": group.members.count(),
            })

        else:
            return Response(
                {"action": "Must be 'join' or 'leave'"},
                status=status.HTTP_400_BAD_REQUEST
            )
