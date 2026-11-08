from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services as S
from .models import (GateSkillReq, MemberFacet, Skill, SkillGate, UserSkill,
                     WorkRating, WorkSkillTag)

RANGE_FIELDS = {"rating_min": float, "rating_max": float, "price_min": int, "price_max": int,
                "attr_min": float, "attr_max": float, "age_min": int, "age_max": int,
                "distance_min_km": float, "distance_max_km": float,
                "exp_min_months": int, "exp_max_months": int, "gauge_min": int, "gauge_max": int}


def _families(names):
    names = list(dict.fromkeys(str(n).strip() for n in (names or []) if str(n).strip()))
    found = set(Skill.objects.filter(family__in=names, active=True).values_list("family", flat=True))
    if set(names) - found:
        raise ValidationError(f"Unknown skill families: {sorted(set(names) - found)}")
    return names


def _active_ids(ids):
    """Gates/filters may name ANY catalog skill (poster requires by experience / rating)."""
    ids = list(dict.fromkeys(int(i) for i in (ids or [])))
    found = set(Skill.objects.filter(pk__in=ids, active=True).values_list("id", flat=True))
    if set(ids) - found:
        raise ValidationError(f"Unknown skills: {sorted(set(ids) - found)}")
    return ids


REQ_CAST = {"rating_min": float, "rating_max": float, "exp_min_months": int,
            "exp_max_months": int, "gauge_min": int, "gauge_max": int}


def _parse_reqs(data) -> dict:
    """Requirement units. skill_reqs rows: {skill_id | family, rating_min/max, exp_min_months/max, gauge_min/max}.
    `families: ["Rapping"]` adds family units with no bounds of their own (gate-level ranges apply).
    Keys: skill id (int) or "f:<Family>"."""
    out = {}
    rows = list(data.get("skill_reqs") or []) + [{"family": f} for f in (data.get("families") or [])]
    for row in rows:
        if row.get("family"):
            key = S.FAM + _families([row["family"]])[0]
        else:
            key = int(row["skill_id"])
        r = {f: (None if row.get(f) in (None, "") else c(row[f])) for f, c in REQ_CAST.items()}
        for lo, hi in [("rating_min", "rating_max"), ("exp_min_months", "exp_max_months"), ("gauge_min", "gauge_max")]:
            if r[lo] is not None and r[hi] is not None and r[lo] > r[hi]:
                raise ValidationError(f"{lo} is above {hi}")
        for f in ("rating_min", "rating_max"):
            if r[f] is not None and not 0 <= r[f] <= 10:
                raise ValidationError("rating must be 0-10")
        out[key] = r
    return out


def _err(e):
    return Response({"detail": "; ".join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)


class CatalogView(APIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def post(self, request):
        """CTA: a skill that isn't in the catalog yet. Dedupes by name; capped per day."""
        from django.utils import timezone
        from django.utils.text import slugify
        name = " ".join(str(request.data.get("name", "")).split())
        if not 2 <= len(name) <= 60:
            return Response({"detail": "Skill name must be 2-60 characters"}, status=400)
        slug = slugify(name)[:64]
        if not slug:
            return Response({"detail": "Invalid skill name"}, status=400)
        existing = Skill.objects.filter(slug=slug).first() or Skill.objects.filter(name__iexact=name).first()
        if existing:
            return Response({"id": existing.id, "slug": existing.slug, "name": existing.name,
                             "app_key": existing.app_key, "price_cents": existing.price_cents,
                             "created": False})
        today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if Skill.objects.filter(created_by=request.user, created_at__gte=today).count() >= 10:
            return Response({"detail": "Daily new-skill limit reached"}, status=429)
        s = Skill.objects.create(slug=slug, name=name, created_by=request.user,
                                 app_key=str(request.data.get("app_key", ""))[:40])
        return Response({"id": s.id, "slug": s.slug, "name": s.name, "app_key": s.app_key,
                         "price_cents": s.price_cents, "created": True}, status=201)

    def get(self, request):
        return Response([{"id": s.id, "slug": s.slug, "name": s.name, "app_key": s.app_key,
                          "family": s.family, "price_cents": s.price_cents}
                         for s in Skill.objects.filter(active=True)])


class MySkillsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(S.profile_skills(request.user))

    def post(self, request):
        try:
            skill = Skill.objects.get(pk=request.data.get("skill_id"), active=True)
            learned = date.fromisoformat(str(request.data.get("learned_at")))
        except (Skill.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "valid skill_id and learned_at (YYYY-MM-DD) required"}, status=400)
        if learned > date.today():
            return Response({"detail": "learned_at cannot be in the future"}, status=400)
        price = request.data.get("price_cents")
        us, _ = UserSkill.objects.update_or_create(
            user=request.user, skill=skill,
            defaults={"learned_at": learned, "price_cents": None if price in (None, "") else int(price)})
        return Response(S.skill_summary(us), status=201)

    def delete(self, request):
        UserSkill.objects.filter(user=request.user, skill_id=request.data.get("skill_id")).delete()
        return Response(status=204)


class ChoicesView(APIView):
    """The ONLY list the upload / skill-used picker may show."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response([{"id": us.skill_id, "slug": us.skill.slug, "name": us.skill.name,
                          "price_cents": us.effective_price} for us in S.choices_for(request.user)])


class PublicProfileView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, username):
        U = get_user_model()
        try:
            user = U.objects.get(**{U.USERNAME_FIELD: username})
        except U.DoesNotExist:
            return Response(status=404)
        return Response({"username": username, "skills": S.profile_skills(user)})


class TagWorkView(APIView):
    """Upload step: skills used must come from the uploader's registry list."""
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        d = request.data
        try:
            skills = S.validate_skill_ids(request.user, d.get("skill_ids") or [])
            wt, wid = str(d.get("work_type", ""))[:24], int(d.get("work_id"))
        except (ValidationError, TypeError, ValueError) as e:
            return _err(e) if isinstance(e, ValidationError) else Response({"detail": "work_type, work_id required"}, status=400)
        if not wt:
            return Response({"detail": "work_type required"}, status=400)
        tags = [WorkSkillTag.objects.update_or_create(
            owner=request.user, work_type=wt, work_id=wid, skill=s,
            defaults={"title": str(d.get("title", ""))[:200]})[0] for s in skills]
        return Response({"tags": [t.id for t in tags],
                         "post_cost_cents": S.post_cost_cents(request.user, skills)}, status=201)


class RateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            tag = WorkSkillTag.objects.get(pk=request.data.get("tag_id"))
            score = int(request.data.get("score"))
        except (WorkSkillTag.DoesNotExist, TypeError, ValueError):
            return Response({"detail": "tag_id and integer score required"}, status=400)
        if not 0 <= score <= 10:
            return Response({"detail": "score must be 0-10"}, status=400)
        if tag.owner_id == request.user.id:
            return Response({"detail": "You cannot rate your own work"}, status=403)
        WorkRating.objects.update_or_create(tag=tag, rater=request.user, defaults={"score": score})
        return Response({"ok": True})


def _gate_from(request, gate=None):
    d = request.data
    gate = gate or SkillGate(owner=request.user)
    for f, cast in RANGE_FIELDS.items():
        if f in d:
            setattr(gate, f, None if d[f] in (None, "") else cast(d[f]))
    gate.skill_match = d.get("skill_match", gate.skill_match or "any")
    gate.adults_only = bool(d.get("adults_only", gate.adults_only))
    gate.age_min, gate.age_max = S.clamp_age_range(
        S.age_of(S.facet_of(request.user)), gate.age_min, gate.age_max)
    S.validate_ranges(gate)
    return gate


class GateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, post_type, post_id):
        g = SkillGate.objects.filter(post_type=post_type, post_id=post_id).first()
        if not g:
            return Response(status=404)
        return Response({**{f: getattr(g, f) for f in RANGE_FIELDS},
                         "skill_ids": list(g.skills.values_list("id", flat=True)),
                         "skill_reqs": [{"skill_id": r.skill_id, "family": r.family, **{f: getattr(r, f) for f in REQ_CAST}}
                                        for r in g.reqs.all()],
                         "skill_match": g.skill_match, "adults_only": g.adults_only})

    @transaction.atomic
    def put(self, request, post_type, post_id):
        existing = SkillGate.objects.filter(post_type=post_type, post_id=post_id).first()
        if existing and existing.owner_id != request.user.id:
            return Response(status=403)
        try:
            gate = _gate_from(request, existing)
        except (ValidationError, ValueError) as e:
            return _err(e) if isinstance(e, ValidationError) else Response({"detail": str(e)}, status=400)
        try:
            reqs = _parse_reqs(request.data) if ("skill_reqs" in request.data or "families" in request.data) else None
            touched = "skill_ids" in request.data or reqs is not None
            ids = _active_ids(list(request.data.get("skill_ids") or []) + [k for k in (reqs or {}) if isinstance(k, int)]) if touched else None
        except (ValidationError, KeyError, ValueError, TypeError) as e:
            return _err(e) if isinstance(e, ValidationError) else Response({"detail": "invalid skill_reqs"}, status=400)
        gate.post_type, gate.post_id = post_type, post_id
        gate.save()
        if ids is not None:
            gate.skills.set(Skill.objects.filter(pk__in=ids, active=True))
        if reqs is not None:
            gate.reqs.all().delete()
            GateSkillReq.objects.bulk_create([
                GateSkillReq(gate=gate, **({"skill_id": k} if isinstance(k, int) else {"family": k[len(S.FAM):]}), **r)
                for k, r in reqs.items()])
        return Response({"ok": True, "age_min": gate.age_min, "age_max": gate.age_max})


class GateCheckView(APIView):
    """Is the requester allowed in? Bool only; never reveals which gate or why."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, post_type, post_id):
        return Response({"allowed": S.assert_passes_gate(post_type, post_id, request.user)})


class SearchView(APIView):
    """Search/Socialize filter: same exclusive gates, ad hoc (not saved)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            gate = _gate_from(request)
            reqs = _parse_reqs(request.data)
            skill_ids = _active_ids(list(request.data.get("skill_ids") or []) + [k for k in reqs if isinstance(k, int)])
        except (ValidationError, ValueError, KeyError, TypeError) as e:
            return _err(e) if isinstance(e, ValidationError) else Response({"detail": str(e)}, status=400)
        found = S.search_candidates(gate, gate_ids=skill_ids, reqs=reqs)
        U = get_user_model()
        return Response([{"username": getattr(u, U.USERNAME_FIELD),
                          "skills": [{"name": x["skill"]["name"], "median": x["median"],
                                      "experience": x["experience"]["label"]}
                                     for x in S.profile_skills(u)]} for u in found])


class SplitPreviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, work_type, work_id):
        try:
            gross = int(request.query_params.get("gross_cents", 0))
            return Response(S.distribute(work_type, work_id, gross))
        except (ValidationError, ValueError) as e:
            return _err(e) if isinstance(e, ValidationError) else Response({"detail": str(e)}, status=400)


def _rng(d, lo, hi, cast=float):
    a, b = d.get(lo), d.get(hi)
    return (None if a in (None, "") else cast(a), None if b in (None, "") else cast(b))


class BrowsePostsView(APIView):
    """Members looking for posts: only posts whose gates admit the requester (default),
    optionally narrowed by the skills / rating / experience / gauge the post asks for."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        d = request.data
        try:
            res = S.browse_posts(
                request.user, post_type=d.get("post_type"), skill_ids=_active_ids(d.get("skill_ids")), families=_families(d.get("families")),
                rating=_rng(d, "rating_min", "rating_max"),
                exp_months=_rng(d, "exp_min_months", "exp_max_months", int),
                gauge_range=_rng(d, "gauge_min", "gauge_max", int),
                only_qualified=bool(d.get("only_qualified", True)))
        except ValidationError as e:
            return _err(e)
        except (TypeError, ValueError) as e:
            return Response({"detail": str(e)}, status=400)
        return Response(res)


class SearchWorksView(APIView):
    """Content search by registry skill or whole family, gated on the creator's experience/rating/gauge."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        d = request.data
        if not (d.get("skill_ids") or d.get("families")):
            return Response({"detail": "skill_ids or families required"}, status=400)
        try:
            res = S.search_works(
                _active_ids(d.get("skill_ids")), families=_families(d.get("families")), work_type=d.get("work_type"),
                creator_rating=_rng(d, "rating_min", "rating_max"),
                creator_exp=_rng(d, "exp_min_months", "exp_max_months", int),
                creator_gauge=_rng(d, "gauge_min", "gauge_max", int),
                work_rating=_rng(d, "work_rating_min", "work_rating_max"))
        except ValidationError as e:
            return _err(e)
        except (TypeError, ValueError) as e:
            return Response({"detail": str(e)}, status=400)
        return Response(res)
