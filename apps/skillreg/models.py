"""SkillReg: the single skill registry for MCZ.

One catalog (Skill) -> what a member holds (UserSkill) -> what work used it
(WorkSkillTag) -> how that work was rated (WorkRating). Everything that asks
"which skills?" (uploads, profiles, filters, gates) reads this list only.
"""
from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models

USER = settings.AUTH_USER_MODEL


class Skill(models.Model):
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    app_key = models.CharField(max_length=40, blank=True)  # PERSONA_APPS key
    family = models.CharField(max_length=80, blank=True, db_index=True)  # e.g. "Rapping"; groups specific skills
    price_cents = models.PositiveIntegerField(default=0)  # catalog price ($1 = 100)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="skillreg_created")  # member-added; curate in admin
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserSkill(models.Model):
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="skillreg_skills")
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name="holders")
    learned_at = models.DateField()  # experience runs from here to today
    price_cents = models.PositiveIntegerField(null=True, blank=True)  # own ask; None = catalog
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "skill")]
        ordering = ["learned_at"]

    @property
    def effective_price(self):
        return self.skill.price_cents if self.price_cents is None else self.price_cents


class WorkSkillTag(models.Model):
    """A piece of work (post/collab/battle/venue/...) tagged with a registry skill."""
    owner = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="skillreg_tags")
    work_type = models.CharField(max_length=24)
    work_id = models.PositiveBigIntegerField()
    title = models.CharField(max_length=200, blank=True)
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name="tags")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("owner", "work_type", "work_id", "skill")]
        indexes = [models.Index(fields=["work_type", "work_id"])]


class WorkRating(models.Model):
    tag = models.ForeignKey(WorkSkillTag, on_delete=models.CASCADE, related_name="ratings")
    rater = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="skillreg_ratings_given")
    score = models.PositiveSmallIntegerField(validators=[MaxValueValidator(10)])  # 0-10
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("tag", "rater")]


class MemberFacet(models.Model):
    """Gate inputs. Point facet_of() in services.py at existing User fields if they exist."""
    user = models.OneToOneField(USER, on_delete=models.CASCADE, related_name="skillreg_facet")
    birth_date = models.DateField(null=True, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    attractiveness_opt_in = models.BooleanField(default=False)
    attractiveness_score = models.FloatField(null=True, blank=True)  # 0-10, adults only


class SkillGate(models.Model):
    """Post owner's exclusive gates for a CollabZ / VenueZ / BattleZ / Socialize post.
    Every bound that is set must be met; anything outside is excluded."""
    MATCH_ANY, MATCH_ALL = "any", "all"

    owner = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="skillreg_gates")
    post_type = models.CharField(max_length=24)
    post_id = models.PositiveBigIntegerField()
    skills = models.ManyToManyField(Skill, blank=True, related_name="gates")
    skill_match = models.CharField(max_length=3, default=MATCH_ANY)
    rating_min = models.FloatField(null=True, blank=True)
    rating_max = models.FloatField(null=True, blank=True)
    price_min = models.PositiveIntegerField(null=True, blank=True)
    price_max = models.PositiveIntegerField(null=True, blank=True)
    attr_min = models.FloatField(null=True, blank=True)
    attr_max = models.FloatField(null=True, blank=True)
    age_min = models.PositiveSmallIntegerField(null=True, blank=True)
    age_max = models.PositiveSmallIntegerField(null=True, blank=True)
    distance_min_km = models.FloatField(null=True, blank=True)
    distance_max_km = models.FloatField(null=True, blank=True)
    exp_min_months = models.PositiveIntegerField(null=True, blank=True)  # per required skill
    exp_max_months = models.PositiveIntegerField(null=True, blank=True)
    gauge_min = models.PositiveSmallIntegerField(null=True, blank=True)  # 0 Novice .. 4 Expert
    gauge_max = models.PositiveSmallIntegerField(null=True, blank=True)
    adults_only = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("post_type", "post_id")]


class GateSkillReq(models.Model):
    """Per-skill OR per-family requirement on a post, by experience and/or median rating.
    Unset fields fall back to the gate-level ranges."""
    gate = models.ForeignKey(SkillGate, on_delete=models.CASCADE, related_name="reqs")
    skill = models.ForeignKey(Skill, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    family = models.CharField(max_length=80, null=True, blank=True)  # set INSTEAD of skill = whole family
    rating_min = models.FloatField(null=True, blank=True)
    rating_max = models.FloatField(null=True, blank=True)
    exp_min_months = models.PositiveIntegerField(null=True, blank=True)
    exp_max_months = models.PositiveIntegerField(null=True, blank=True)
    gauge_min = models.PositiveSmallIntegerField(null=True, blank=True)
    gauge_max = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        unique_together = [("gate", "skill"), ("gate", "family")]
