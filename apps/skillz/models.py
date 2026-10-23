"""
SkillZ — shared gamification models for Music ConnectZ creator apps.

Every creator app (MimeZ, DirectZ, AnimatorZ, ...) shares ONE engine keyed
by `app_key`. That keeps XP / streaks / badges / leaderboards consistent across
the whole platform while letting each app define its own drills.

Design notes:
- One TrainingProfile per (user, app_key).
- Drills are data, not code — apps seed their own via management/seed helpers.
- Badges auto-award off simple rules (xp / streak / drill-count thresholds).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


def _level_for_xp(xp: int) -> int:
    """Smooth-ish curve: every 500 XP = a level, starting at 1."""
    return 1 + (max(0, int(xp)) // 500)



# XP tier bonus (Corey's numbers). Applied wherever XP lands, so every "+N ⭐" a screen
# quotes and every XP row agree.
XP_TIER_MULTIPLIER = {"free": 1.0, "premium": 1.25, "statz": 1.5, "debug": 1.5}


def tier_xp(user, base) -> int:
    base = max(0, int(base or 0))
    if not base or not user:
        return base
    try:
        from apps.economy.models import membership_for
        tier = membership_for(user).tier
    except Exception:
        tier = "free"
    return int(round(base * XP_TIER_MULTIPLIER.get(tier, 1.0)))

class TrainingProfile(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="training_profiles",
    )
    app_key = models.CharField(max_length=40, db_index=True)
    xp = models.PositiveIntegerField(default=0)
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    last_active = models.DateField(null=True, blank=True)
    drills_completed = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "app_key")
        ordering = ("-xp", "-current_streak")
        indexes = [models.Index(fields=["app_key", "-xp"])]

    def __str__(self):
        return f"{self.user} · {self.app_key} · {self.xp}xp"

    @property
    def level(self) -> int:
        return _level_for_xp(self.xp)

    @property
    def xp_into_level(self) -> int:
        return self.xp % 500

    @property
    def xp_to_next_level(self) -> int:
        return 500 - self.xp_into_level

    def touch_streak(self):
        """Update streak counters based on today's activity."""
        today = timezone.localdate()
        if self.last_active == today:
            pass  # already counted today
        elif self.last_active == today - timezone.timedelta(days=1):
            self.current_streak += 1
        else:
            self.current_streak = 1
        self.longest_streak = max(self.longest_streak, self.current_streak)
        self.last_active = today

    def add_xp(self, amount: int) -> int:
        """Add XP with the member's tier bonus applied, and return what landed. XP
        rewards effort, never quality, so a tier may make you level faster — it never
        touches a rating or a skill level."""
        landed = tier_xp(self.user, amount)
        self.xp = (self.xp or 0) + landed
        return landed


class Drill(models.Model):
    """A single trainable activity inside an app (e.g. a MimeZ lipsync drill)."""

    app_key = models.CharField(max_length=40, db_index=True)
    key = models.SlugField(max_length=80)
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=60, blank=True, default="")
    xp = models.PositiveIntegerField(default=50)
    icon = models.CharField(max_length=80, blank=True, default="")
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("app_key", "key")
        ordering = ("app_key", "order", "id")

    def __str__(self):
        return f"{self.app_key}:{self.key}"


class Badge(models.Model):
    RULE_XP = "xp"
    RULE_STREAK = "streak"
    RULE_DRILLS = "drills"
    RULE_CHOICES = [
        (RULE_XP, "Total XP"),
        (RULE_STREAK, "Day streak"),
        (RULE_DRILLS, "Drills completed"),
    ]

    app_key = models.CharField(max_length=40, db_index=True)
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=240, blank=True, default="")
    icon = models.CharField(max_length=80, blank=True, default="")
    rule = models.CharField(max_length=12, choices=RULE_CHOICES, default=RULE_XP)
    threshold = models.PositiveIntegerField(default=100)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("app_key", "code")
        ordering = ("app_key", "order", "threshold")

    def __str__(self):
        return f"{self.app_key}:{self.code}"

    def is_met_by(self, profile: "TrainingProfile") -> bool:
        if self.rule == self.RULE_XP:
            return profile.xp >= self.threshold
        if self.rule == self.RULE_STREAK:
            return profile.longest_streak >= self.threshold
        if self.rule == self.RULE_DRILLS:
            return profile.drills_completed >= self.threshold
        return False


class EarnedBadge(models.Model):
    profile = models.ForeignKey(
        TrainingProfile, on_delete=models.CASCADE, related_name="earned_badges"
    )
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE, related_name="earned_by")
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("profile", "badge")
        ordering = ("-earned_at",)


class TrainingEvent(models.Model):
    """Audit log of a completed drill — powers history + anti-cheat later."""

    profile = models.ForeignKey(
        TrainingProfile, on_delete=models.CASCADE, related_name="events"
    )
    drill_key = models.CharField(max_length=80)
    score = models.PositiveIntegerField(default=0)
    xp_awarded = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
