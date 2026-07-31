from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.economy.models import Post

from .models import (KIND_CHOICES, ROLE_COLLABORATOR, ROLE_INVITED, ROLE_OWNER,
                     STATUS_CHOICES, STATUS_OPEN, CollabMember, CollabProject)

ICONS = {"original": None, "cover": "🫴🏼", "remix": "🔄"}


def _member_dict(m):
    return {"user": m.user.username, "role": m.role, "persona": m.persona,
            "contribution": m.contribution, "split_percent": m.split_percent,
            "joined_at": m.joined_at}


def _project_dict(p, full=False):
    out = {
        "id": p.id, "kind": p.kind, "icon": ICONS.get(p.kind),
        "title": p.title, "brief": p.brief, "status": p.status,
        "owner": p.owner.username, "seeking": p.seeking, "genres": p.genres,
        "source_post_id": p.source_post_id, "source_credit": p.source_credit,
        "result_post_id": p.result_post_id, "deal_id": p.deal_id,
        "member_count": p.members.exclude(role=ROLE_INVITED).count(),
        "split_total": p.split_total(),
        "updated_at": p.updated_at,
    }
    if full:
        out["members"] = [_member_dict(m) for m in p.members.select_related("user")]
        out["split_warning"] = p.split_error()
    return out


class CatalogView(APIView):
    """GET the CollabZ vocabulary. Public — it's a picker."""

    permission_classes = [AllowAny]

    def get(self, _request):
        return Response({
            "kinds": [{"key": k, "label": v, "icon": ICONS.get(k),
                       "needs_source": k in ("cover", "remix")}
                      for k, v in KIND_CHOICES],
            "statuses": [{"key": k, "label": v} for k, v in STATUS_CHOICES],
            "roles": ["owner", "collaborator", "invited"],
        })


class ProjectsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = CollabProject.objects.select_related("owner")
        if request.query_params.get("mine"):
            qs = qs.filter(members__user=request.user).distinct()
        kind = request.query_params.get("kind")
        if kind in dict(KIND_CHOICES):
            qs = qs.filter(kind=kind)
        state = request.query_params.get("status")
        if state in dict(STATUS_CHOICES):
            qs = qs.filter(status=state)
        return Response({"projects": [_project_dict(p) for p in qs[:200]]})

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "title required"},
                            status=status.HTTP_400_BAD_REQUEST)
        kind = d.get("kind") if d.get("kind") in dict(KIND_CHOICES) else "original"

        source = None
        if d.get("source_post_id"):
            source = Post.objects.filter(pk=d["source_post_id"]).first()
            if not source:
                return Response({"detail": "No such source post."},
                                status=status.HTTP_400_BAD_REQUEST)

        p = CollabProject(
            owner=request.user, title=title[:160], kind=kind,
            brief=str(d.get("brief", ""))[:2000],
            source_post=source,
            source_credit=str(d.get("source_credit", ""))[:300],
            seeking=[str(s)[:60] for s in (d.get("seeking") or [])][:20],
            genres=[str(g)[:60] for g in (d.get("genres") or [])][:20],
            status=STATUS_OPEN,
        )
        problem = p.source_error()
        if problem:
            return Response({"detail": problem},
                            status=status.HTTP_400_BAD_REQUEST)
        p.save()
        CollabMember.objects.create(project=p, user=request.user, role=ROLE_OWNER,
                                    persona=str(d.get("persona", ""))[:40])
        return Response({"project": _project_dict(p, full=True)},
                        status=status.HTTP_201_CREATED)


class ProjectDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        p = CollabProject.objects.filter(pk=pk).first()
        if not p:
            return Response({"detail": "No such project."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response({"project": _project_dict(p, full=True)})

    def patch(self, request, pk):
        p = CollabProject.objects.filter(pk=pk, owner=request.user).first()
        if not p:
            return Response({"detail": "Not your project."},
                            status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        for field, cap in (("title", 160), ("brief", 2000), ("source_credit", 300)):
            if field in d:
                setattr(p, field, str(d[field])[:cap])
        if d.get("status") in dict(STATUS_CHOICES):
            p.status = d["status"]
        if "result_post_id" in d:
            result = Post.objects.filter(pk=d["result_post_id"],
                                         author=request.user).first()
            if d["result_post_id"] and not result:
                return Response({"detail": "That's not your post."},
                                status=status.HTTP_400_BAD_REQUEST)
            p.result_post = result
        problem = p.source_error()
        if problem:
            return Response({"detail": problem},
                            status=status.HTTP_400_BAD_REQUEST)
        p.save()
        return Response({"project": _project_dict(p, full=True)})

    def delete(self, request, pk):
        p = CollabProject.objects.filter(pk=pk, owner=request.user).first()
        if not p:
            return Response({"detail": "Not your project."},
                            status=status.HTTP_404_NOT_FOUND)
        p.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MembersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        p = CollabProject.objects.filter(pk=pk).first()
        if not p:
            return Response({"detail": "No such project."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response({"members": [_member_dict(m) for m in
                                     p.members.select_related("user")],
                         "split_total": p.split_total(),
                         "split_warning": p.split_error()})

    def post(self, request, pk):
        """Owner invites somebody, or a member updates their own row."""
        from django.contrib.auth import get_user_model

        p = CollabProject.objects.filter(pk=pk).first()
        if not p:
            return Response({"detail": "No such project."},
                            status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        username = str(d.get("username", "")).strip()

        if username and username != request.user.username:
            if p.owner_id != request.user.id:
                return Response({"detail": "Only the owner adds people."},
                                status=status.HTTP_403_FORBIDDEN)
            target = get_user_model().objects.filter(username=username).first()
            if not target:
                return Response({"detail": "No such member."},
                                status=status.HTTP_404_NOT_FOUND)
            role = ROLE_INVITED
        else:
            target, role = request.user, ROLE_COLLABORATOR

        member, created = CollabMember.objects.get_or_create(
            project=p, user=target, defaults={"role": role})
        if not created and member.role == ROLE_INVITED and target == request.user:
            member.role = ROLE_COLLABORATOR   # accepting an invite

        if "persona" in d:
            member.persona = str(d["persona"])[:40]
        if "contribution" in d:
            member.contribution = str(d["contribution"])[:300]
        if "split_percent" in d and (p.owner_id == request.user.id
                                     or target == request.user):
            try:
                member.split_percent = max(0, min(int(d["split_percent"]), 100))
            except (TypeError, ValueError):
                return Response({"detail": "split_percent must be a whole number."},
                                status=status.HTTP_400_BAD_REQUEST)
        member.save()

        # Reported, not enforced: splits are usually wrong while people are
        # still negotiating, and refusing the save would make the tool useless
        # exactly when it's being used. It hard-fails at payout instead.
        return Response({"member": _member_dict(member),
                         "split_total": p.split_total(),
                         "split_warning": p.split_error()},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request, pk):
        p = CollabProject.objects.filter(pk=pk).first()
        if not p:
            return Response({"detail": "No such project."},
                            status=status.HTTP_404_NOT_FOUND)
        username = request.query_params.get("username") or request.user.username
        if username != request.user.username and p.owner_id != request.user.id:
            return Response({"detail": "Only the owner removes other people."},
                            status=status.HTTP_403_FORBIDDEN)
        member = p.members.filter(user__username=username).first()
        if not member:
            return Response({"detail": "Not on this project."},
                            status=status.HTTP_404_NOT_FOUND)
        if member.role == ROLE_OWNER:
            return Response({"detail": "The owner can't leave — archive it instead."},
                            status=status.HTTP_409_CONFLICT)
        member.delete()
        return Response({"split_total": p.split_total(),
                         "split_warning": p.split_error()})
