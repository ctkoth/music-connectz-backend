from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.economy import searchfilters
from apps.economy.models import Post
from apps.economy.personaz import (PERSONAZ, is_v22_skill,
                                   normalize_persona_key, skill_key_for)

from .models import (KIND_CHOICES, ROLE_COLLABORATOR, ROLE_INVITED, ROLE_OWNER,
                     STATUS_CHOICES, STATUS_OPEN, CollabMember, CollabProject)

ICONS = {"original": None, "cover": "🫴🏼", "remix": "🔄"}


def _clean_skills(raw, limit=30):
    """Canonical skill keys from anything the client sends, across every persona.

    Resolves decorated labels the same way persona keys do, because a picker
    sends back what it displayed — "Acoustic Guitar 🎸", not "Acoustic Guitar".
    """
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for value in raw:
        for persona_key in PERSONAZ:
            # skill_key_for resolves a key OR a stored label, which is what a
            # picker sends back — "Acoustic Guitar 🎸", not "Acoustic Guitar".
            found = skill_key_for(persona_key, value)
            if found:
                if found not in out:
                    out.append(found)
                break
        if len(out) >= limit:
            break
    return out


def _unknown_skills(raw):
    """What the client sent that isn't a skill — reported rather than dropped."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    unknown = []
    for value in raw:
        if not any(skill_key_for(k, value) for k in PERSONAZ):
            unknown.append(str(value)[:60])
    return unknown


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
    out["skills"] = p.skills
    out["requirements"] = p.requirements or {}
    out["requirements_text"] = searchfilters.describe(
        searchfilters.load(p.requirements))
    if full:
        out["members"] = [_member_dict(m) for m in p.members.select_related("user")]
        out["split_warning"] = p.split_error()
    return out


class CatalogView(APIView):
    """GET the CollabZ vocabulary. Public — it's a picker.

    `?since=2.2` serves ONLY the five personas and 131 skills the 2.2 build
    shipped, for a form that has to match 2.2 exactly. Without it you get the
    full catalog, which is a superset — every 2.2 skill is still in there.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        only_v22 = str(request.query_params.get("since", "")).strip() == "2.2"

        def categories(key, persona):
            for cat, skills in persona["categories"].items():
                picked = [{"key": sk, "label": label,
                           "v22": is_v22_skill(key, cat, sk)}
                          for sk, label in skills.items()
                          if not only_v22 or is_v22_skill(key, cat, sk)]
                if picked:
                    yield {"name": cat, "skills": picked}

        personas = []
        for key, p in PERSONAZ.items():
            cats = list(categories(key, p))
            if only_v22 and not cats:
                continue
            personas.append({"key": key, "label": f"{p['emoji']} {p['name']}",
                             "categories": cats,
                             "skill_count": sum(len(c["skills"]) for c in cats)})

        return Response({
            "kinds": [{"key": k, "label": v, "icon": ICONS.get(k),
                       "needs_source": k in ("cover", "remix")}
                      for k, v in KIND_CHOICES],
            "statuses": [{"key": k, "label": v} for k, v in STATUS_CHOICES],
            "roles": ["owner", "collaborator", "invited"],
            # The picker's options. Skills are REQUIRED on a post, so the form
            # needs the real vocabulary rather than a free-text box — which is
            # what "Skill (optional)" was, and nothing could filter on it.
            "skills_required": True,
            "since": "2.2" if only_v22 else None,
            "personas": personas,
            "skill_count": sum(p["skill_count"] for p in personas),
            "ranges": searchfilters.catalog(),
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

        # Skills first — a collab nobody can be matched to is not a collab.
        skills = _clean_skills(d.get("skills"))
        p = CollabProject(
            owner=request.user, title=title[:160], kind=kind,
            skills=skills,
            brief=str(d.get("brief", ""))[:2000],
            source_post=source,
            source_credit=str(d.get("source_credit", ""))[:300],
            seeking=[str(s)[:60] for s in (d.get("seeking") or [])][:20],
            genres=[str(g)[:60] for g in (d.get("genres") or [])][:20],
            requirements=searchfilters.store(d),
            status=STATUS_OPEN,
        )
        problem = p.skills_error() or p.source_error()
        if problem:
            return Response({"detail": problem,
                             "unrecognised_skills": _unknown_skills(d.get("skills"))},
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
        problem = p.skills_error() or p.source_error()
        if problem:
            return Response({"detail": problem,
                             "unrecognised_skills": _unknown_skills(d.get("skills"))},
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
            # Joining yourself has to clear the owner's range gates. An invite
            # doesn't: the owner picked that person on purpose, and a filter
            # overruling a deliberate choice is the filter being wrong.
            already_on = p.members.filter(user=request.user).exists()
            if not already_on:
                refused = searchfilters.entry_error(request.user, p.requirements,
                                                    viewer=p.owner)
                if refused:
                    return Response({"detail": refused,
                                     "requirements": p.requirements},
                                    status=status.HTTP_403_FORBIDDEN)

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


class MatchView(APIView):
    """GET members who fit a collab, gated by the five ranges.

        ?skills=Mixing,Trap&age=18-30&distance_max=50&skill_rating_min=7

    The ranges are exclusive gates — outside means excluded, not ranked lower.
    Members with no value for a gated range come back under `unknown` instead of
    being dropped, so a new member with no ratings yet is still reachable.

    Used by CollabZ, and the same shape serves VenueZ, BattleZ and the Social
    ConnectZ search, which is why the gates live in economy/searchfilters.py
    rather than here.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.contrib.auth import get_user_model

        from apps.economy.models import profile_for

        wanted = _clean_skills(
            [s for s in (request.query_params.get("skills") or "").split(",") if s.strip()])
        ranges = searchfilters.parse(request.query_params)

        candidates = []
        for user in get_user_model().objects.exclude(pk=request.user.pk)[:2000]:
            if wanted:
                have = set()
                for entry in (profile_for(user).personas or []):
                    key = entry.get("key") if isinstance(entry, dict) else entry
                    canonical = normalize_persona_key(key)
                    if not canonical:
                        continue
                    for sk in (entry.get("skills") or []) if isinstance(entry, dict) else []:
                        name = sk.get("name") if isinstance(sk, dict) else sk
                        found = skill_key_for(canonical, name)
                        if found:
                            have.add(found)
                if not set(wanted) <= have:
                    continue
            candidates.append(user)

        split = searchfilters.apply(candidates, ranges, viewer=request.user)

        def row(user):
            _, detail = searchfilters.evaluate(user, ranges, viewer=request.user)
            return {"username": user.username, "gates": detail}

        return Response({
            "skills": wanted,
            "ranges": {k: r.payload() for k, r in ranges.items()},
            "matches": [row(u) for u in split["matches"][:100]],
            # Separate and labelled: "outside your range" and "we don't know yet"
            # are different answers, and only one is worth acting on.
            "unknown": [row(u) for u in split["unknown"][:25]],
            "excluded_count": len(split["excluded"]),
        })
