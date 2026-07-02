"""
LessonZ — skill lessons in collab fashion, with one-directional payment.

Rules (CollabZ-style, adapted):
- Only users whose rating for a skill is >= 6 can TEACH that skill.
- Any persona can teach any of the user's qualifying skillz.
- Student pays the teacher's price. The teacher NEVER pays the student
  (unlike CollabZ's two-way split) — payment flows one way only.
- Teacher and student agree on the pricing mode: per hour or per lesson.
- Offers carry a location (lat/lng + city) and a remote flag so lessons can be
  filtered by distance like CollabZ, or taken remotely.
- LessonZ is AGE-GATED at the view layer (platform child-safety model:
  paid 1:1 contact between users is adult-verified only, snapshot pattern
  preserved by the existing gate).

Rating source is pluggable: we try the platform's RateZ-style rating first
(apps.common.ratings.get_skill_rating), then a locally stored TeacherSkillRating,
then fall back to the SkillZ level for that skill's app_key. Highest wins.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models

APP_KEY = "lessonz"
MIN_TEACH_RATING = 6

MODE_HOUR = "per_hour"
MODE_LESSON = "per_lesson"
MODE_CHOICES = [(MODE_HOUR, "Per hour"), (MODE_LESSON, "Per lesson")]

STATUS_REQUESTED = "requested"
STATUS_ACCEPTED = "accepted"
STATUS_DECLINED = "declined"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"
STATUS_CHOICES = [
    (STATUS_REQUESTED, "Requested"),
    (STATUS_ACCEPTED, "Accepted"),
    (STATUS_DECLINED, "Declined"),
    (STATUS_COMPLETED, "Completed"),
    (STATUS_CANCELLED, "Cancelled"),
]


class TeacherSkillRating(models.Model):
    """Local rating store (0-10). Synced from RateZ later or set via admin."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lessonz_ratings"
    )
    skill = models.CharField(max_length=60, db_index=True)  # e.g. "mimez", "directz", "singz"
    rating = models.PositiveSmallIntegerField(default=0)  # 0-10
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "skill")

    def __str__(self):
        return f"{self.user}·{self.skill}={self.rating}"


def get_skill_rating(user, skill: str) -> int:
    """Best-known rating for user+skill. Defensive, highest source wins."""
    best = 0
    # 1) Platform RateZ-style source, if present
    try:  # pragma: no cover - environment dependent
        from apps.common.ratings import get_skill_rating as _ext

        best = max(best, int(_ext(user, skill) or 0))
    except Exception:
        pass
    # 2) Local store
    try:
        row = TeacherSkillRating.objects.filter(user=user, skill=skill).first()
        if row:
            best = max(best, row.rating)
    except Exception:
        pass
    # 3) SkillZ level fallback (level 6+ in that app's training == rating 6+)
    try:
        from apps.skillz.models import TrainingProfile

        prof = TrainingProfile.objects.filter(user=user, app_key=skill).first()
        if prof:
            best = max(best, prof.level)
    except Exception:
        pass
    return best


class LessonOffer(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_offers"
    )
    persona = models.CharField(max_length=60, blank=True, default="")  # any persona may teach
    skill = models.CharField(max_length=60, db_index=True)
    title = models.CharField(max_length=140)
    description = models.TextField(blank=True, default="")
    pricing_mode = models.CharField(max_length=12, choices=MODE_CHOICES, default=MODE_HOUR)
    price = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("25.00"))
    currency = models.CharField(max_length=8, default="USD")
    # location for distance filtering (CollabZ-style)
    city = models.CharField(max_length=80, blank=True, default="")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    remote_ok = models.BooleanField(default=True)
    in_person_ok = models.BooleanField(default=True)
    rating_snapshot = models.PositiveSmallIntegerField(default=0)  # rating at publish time
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.teacher}·{self.skill}·{self.price}/{self.pricing_mode}"


class LessonBooking(models.Model):
    offer = models.ForeignKey(LessonOffer, on_delete=models.CASCADE, related_name="bookings")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_bookings"
    )
    pricing_mode = models.CharField(max_length=12, choices=MODE_CHOICES)
    hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.00"))
    agreed_total = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=8, default="USD")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_REQUESTED)
    note = models.CharField(max_length=280, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def compute_total(self) -> Decimal:
        if self.pricing_mode == MODE_HOUR:
            return (self.offer.price * self.hours).quantize(Decimal("0.01"))
        return self.offer.price.quantize(Decimal("0.01"))


class LessonPayment(models.Model):
    """One-directional: student -> teacher. Teacher never pays the student.

    This records the charge; actual money movement hooks into the platform
    wallet/Stripe defensively (apps.common.wallet.charge) when available.
    """

    booking = models.OneToOneField(
        LessonBooking, on_delete=models.CASCADE, related_name="payment"
    )
    payer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_payments_made"
    )
    payee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_payments_received"
    )
    amount = models.DecimalField(max_digits=9, decimal_places=2)
    currency = models.CharField(max_length=8, default="USD")
    settled = models.BooleanField(default=False)
    external_ref = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.payer} -> {self.payee}: {self.amount} {self.currency}"


# ------------------------------------------------------------ Lesson Posts
# Recorded lessons uploaded as POSTS. Owner sets visibility; anyone who can see
# a post may pay to unlock it. TEACHERS MUST BE ADULTS (enforced at the view
# layer with the platform adult gate). STUDENTS MAY BE MINORS here because a
# post is one-to-many recorded content with no contact channel — unlike live
# 1:1 bookings, which remain adult-only (ScoutZ rule: no adult-to-minor
# contact channels).

VIS_PUBLIC = "public"
VIS_PREMIUM = "premium"
VIS_STATZ = "statz"
VIS_PRIVATE = "private"
VISIBILITY_CHOICES = [
    (VIS_PUBLIC, "Public"),
    (VIS_PREMIUM, "Premium tier"),
    (VIS_STATZ, "StatZ tier"),
    (VIS_PRIVATE, "Only me"),
]


def get_user_tier(user) -> str:
    """Defensive tier lookup (free/premium/statz). Falls back to 'free'."""
    try:  # pragma: no cover - platform dependent
        from apps.common.tiergate import get_tier as _t

        return (_t(user) or "free").lower()
    except Exception:
        pass
    try:  # pragma: no cover
        from apps.common.models import UserFlags

        f = UserFlags.objects.filter(user=user).first()
        if f and getattr(f, "tier", None):
            return str(f.tier).lower()
    except Exception:
        pass
    return "free"


class LessonPost(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_posts"
    )
    persona = models.CharField(max_length=60, blank=True, default="")
    skill = models.CharField(max_length=60, db_index=True)
    title = models.CharField(max_length=140)
    description = models.TextField(blank=True, default="")
    media_ref = models.CharField(
        max_length=255, blank=True, default="",
        help_text="Reference id from the platform upload pipeline.",
    )
    preview_ref = models.CharField(max_length=255, blank=True, default="")
    price = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("5.00"))
    currency = models.CharField(max_length=8, default="USD")
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default=VIS_PUBLIC)
    rating_snapshot = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def visible_to(self, user) -> bool:
        if self.teacher_id == getattr(user, "id", None):
            return True
        if not self.is_active:
            return False
        if self.visibility == VIS_PUBLIC:
            return True
        if self.visibility == VIS_PRIVATE:
            return False
        tier = get_user_tier(user)
        if self.visibility == VIS_PREMIUM:
            return tier in ("premium", "statz")
        if self.visibility == VIS_STATZ:
            return tier == "statz"
        return False

    def __str__(self):
        return f"post:{self.teacher}·{self.skill}·{self.title[:24]}"


class LessonPostPurchase(models.Model):
    """Student pays to unlock a post. One-directional: student -> teacher."""

    post = models.ForeignKey(LessonPost, on_delete=models.CASCADE, related_name="purchases")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_post_purchases"
    )
    amount = models.DecimalField(max_digits=9, decimal_places=2)
    currency = models.CharField(max_length=8, default="USD")
    settled = models.BooleanField(default=False)
    external_ref = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("post", "student")

    def __str__(self):
        return f"{self.student} unlocked {self.post_id} for {self.amount}"
