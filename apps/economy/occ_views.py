"""OCC coding-agent endpoints — projects, files, and agentic runs.

    GET  POST   /api/economy/occ/projects/                list / create
    GET  DELETE /api/economy/occ/projects/<id>/           detail (with files) / delete
    GET  POST   /api/economy/occ/projects/<id>/files/     read a file / write one
    DELETE      /api/economy/occ/projects/<id>/files/     delete one (?path=)
    POST        /api/economy/occ/projects/<id>/agent/     run the agent
    GET         /api/economy/occ/projects/<id>/runs/      what the agent has done

Every route is scoped to `request.user` — a project id belonging to somebody else
is a 404, not a 403, so ids can't be probed for existence.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AgentRun, Project, ProjectFile
from .occ_agent import MAX_STEPS, max_steps_for, run_agent, transcript
from .occ_tools import (MAX_FILE_CHARS, MAX_FILES, MAX_TOTAL_CHARS,
                        TOOL_SCHEMAS, normalize_path)

MAX_PROJECTS = 25


def _project_dict(p, files=False):
    rows = list(p.files.only("path", "content", "updated_at")) if files else []
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "file_count": p.files.count(),
        "chars": sum(len(f.content) for f in rows) if files else None,
        "runs": p.runs.count(),
        "updated_at": p.updated_at,
        **({"files": [
            {"path": f.path, "chars": len(f.content), "lines": f.content.count("\n") + 1,
             "updated_at": f.updated_at}
            for f in rows
        ]} if files else {}),
    }


def _owned(request, pk):
    return Project.objects.filter(pk=pk, owner=request.user).first()


class ProjectsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "projects": [_project_dict(p) for p in request.user.occ_projects.all()[:MAX_PROJECTS]],
            "limits": {
                "projects": MAX_PROJECTS, "files": MAX_FILES,
                "file_chars": MAX_FILE_CHARS, "total_chars": MAX_TOTAL_CHARS,
                "max_steps": max_steps_for(request.user),
                "max_steps_by_tier": MAX_STEPS,
            },
            # So a client can show what the agent is able to do without guessing.
            "tools": [{"name": t["name"], "description": t["description"]} for t in TOOL_SCHEMAS],
            "can_run_code": False,
        })

    def post(self, request):
        name = str((request.data or {}).get("name", "")).strip()
        if not name:
            return Response({"detail": "name required"}, status=status.HTTP_400_BAD_REQUEST)
        name = name[:80]
        if request.user.occ_projects.count() >= MAX_PROJECTS:
            return Response({"detail": f"you already have {MAX_PROJECTS} projects"},
                            status=status.HTTP_400_BAD_REQUEST)
        if request.user.occ_projects.filter(name=name).exists():
            return Response({"detail": f"you already have a project called {name!r}"},
                            status=status.HTTP_409_CONFLICT)
        p = Project.objects.create(
            owner=request.user, name=name,
            description=str((request.data or {}).get("description", ""))[:500],
        )
        return Response({"project": _project_dict(p, files=True)}, status=status.HTTP_201_CREATED)


class ProjectDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        p = _owned(request, pk)
        if not p:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"project": _project_dict(p, files=True)})

    def delete(self, request, pk):
        p = _owned(request, pk)
        if not p:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        p.delete()
        return Response({"deleted": pk})


class ProjectFilesView(APIView):
    """Direct file access, so a member can read and edit without the agent.

    The agent is not the only way in on purpose: a workspace you can only change
    by asking a model to change it is not a workspace you own.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        p = _owned(request, pk)
        if not p:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        path = normalize_path(request.query_params.get("path", ""))
        if not path:
            return Response({"files": _project_dict(p, files=True)["files"]})
        row = p.files.filter(path=path).first()
        if not row:
            return Response({"detail": f"no such file: {path}"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"path": row.path, "content": row.content, "updated_at": row.updated_at})

    def post(self, request, pk):
        p = _owned(request, pk)
        if not p:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        path = normalize_path(d.get("path", ""))
        if not path:
            return Response({"detail": "a valid workspace-relative path is required"},
                            status=status.HTTP_400_BAD_REQUEST)
        content = d.get("content")
        content = "" if content is None else str(content)
        if len(content) > MAX_FILE_CHARS:
            return Response({"detail": f"file over {MAX_FILE_CHARS} chars"},
                            status=status.HTTP_400_BAD_REQUEST)
        existing = p.files.filter(path=path).first()
        if not existing and p.files.count() >= MAX_FILES:
            return Response({"detail": f"project already has {MAX_FILES} files"},
                            status=status.HTTP_400_BAD_REQUEST)
        total = sum(len(f.content) for f in p.files.exclude(path=path).only("content"))
        if total + len(content) > MAX_TOTAL_CHARS:
            return Response({"detail": "project would exceed its total size limit"},
                            status=status.HTTP_400_BAD_REQUEST)
        row, created = ProjectFile.objects.update_or_create(
            project=p, path=path, defaults={"content": content}
        )
        p.save(update_fields=["updated_at"])
        return Response({"path": row.path, "chars": len(content), "created": created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request, pk):
        p = _owned(request, pk)
        if not p:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        path = normalize_path(request.query_params.get("path", ""))
        row = p.files.filter(path=path).first() if path else None
        if not row:
            return Response({"detail": "no such file"}, status=status.HTTP_404_NOT_FOUND)
        row.delete()
        return Response({"deleted": path})


class AgentView(APIView):
    """POST {prompt, history?, dry_run?, max_steps?} — run the loop.

    Charges the model minimum per step (Corey's rate), same pass-through pricing
    as OCC chat. `dry_run` plans without writing, which is the right first move on
    a project that already has work in it.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        p = _owned(request, pk)
        if not p:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        prompt = str(d.get("prompt", "")).strip()
        if not prompt:
            return Response({"detail": "prompt is required."}, status=status.HTTP_400_BAD_REQUEST)

        result, code = run_agent(
            request.user, p, prompt,
            history=d.get("history") or [],
            max_steps=d.get("max_steps"),
            dry_run=bool(d.get("dry_run")),
        )
        p.save(update_fields=["updated_at"])
        return Response(result, status=code)


class AgentRunsView(APIView):
    """GET the run history — what OCC actually did, not just what it said."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        p = _owned(request, pk)
        if not p:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        runs = AgentRun.objects.filter(project=p).select_related("project")[:25]
        return Response({"runs": [transcript(r) for r in runs]})
