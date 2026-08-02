"""BodieZ data model — Jefit's training metrics under Lilith's buckets.

Two ideas stacked, which is the whole blueprint:

* **Jefit's metrics** — routines of exercises with sets, reps, rest, target
  weight and superset groups; sessions that log every set with RPE/RIR; body
  measurements; progressive-overload coaching.
* **Lilith's organisation** — Inbox, Today, Upcoming, Anytime, Someday, Logbook,
  Trash. A training plan is a project, and the reason people abandon fitness apps
  is rarely the logging; it's that "the workout I keep meaning to try" has
  nowhere to live.

Money and tier rules live in the views, not here. Models stay dumb so the
gating is readable in one place.
"""
from django.conf import settings
from django.db import models

from .catalog import DIFFICULTY_KEYS, GOAL_KEYS, MUSCLE_KEYS

# ---------------------------------------------------------------- buckets
BUCKET_INBOX = "inbox"
BUCKET_TODAY = "today"
BUCKET_UPCOMING = "upcoming"
BUCKET_ANYTIME = "anytime"
BUCKET_SOMEDAY = "someday"
BUCKET_LOGBOOK = "logbook"
BUCKET_TRASH = "trash"
BUCKETS = [BUCKET_INBOX, BUCKET_TODAY, BUCKET_UPCOMING, BUCKET_ANYTIME,
           BUCKET_SOMEDAY, BUCKET_LOGBOOK, BUCKET_TRASH]
# Emoji are part of the tab name in this paradigm, not decoration.
BUCKET_LABELS = {
    BUCKET_INBOX: "Inbox 📥", BUCKET_TODAY: "Today 💪",
    BUCKET_UPCOMING: "Upcoming 📅", BUCKET_ANYTIME: "Anytime 🏋️",
    BUCKET_SOMEDAY: "Someday 🧠", BUCKET_LOGBOOK: "Logbook 🧾",
    BUCKET_TRASH: "Trash 🚮",
}


class Exercise(models.Model):
    """A movement. Seeded from catalog.EXERCISES; members may add their own.

    `owner` null = a catalog exercise everyone sees. Set = a private movement,
    because every gym has a machine the catalog has never heard of.
    """
    key = models.CharField(max_length=60, db_index=True)
    name = models.CharField(max_length=120)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              null=True, blank=True, related_name="bodiez_exercises")
    muscle = models.CharField(max_length=20, db_index=True)
    secondary = models.JSONField(default=list, blank=True)
    # Everything the movement might use, for display and search.
    equipment = models.JSONField(default=list, blank=True)
    # The real filter: a list of any-of groups. ["barbell"], ["flat-bench"] means
    # both are needed; [["kettlebell", "dumbbell"]] means either will do.
    requires = models.JSONField(default=list, blank=True)
    pattern = models.CharField(max_length=16, default="isolation")
    difficulty = models.CharField(max_length=16, default="beginner")
    instructions = models.TextField(blank=True, default="")
    media_url = models.CharField(max_length=300, blank=True, default="")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["muscle", "name"]
        unique_together = ("key", "owner")
        indexes = [models.Index(fields=["muscle", "pattern"])]

    def __str__(self):
        return self.name

    @property
    def is_catalog(self):
        return self.owner_id is None


class Routine(models.Model):
    """A training plan. Lives in a Lilith bucket like any other project."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="bodiez_routines")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    goal = models.CharField(max_length=20, default="general")
    split = models.CharField(max_length=24, default="custom")
    difficulty = models.CharField(max_length=16, default="beginner")
    days_per_week = models.PositiveSmallIntegerField(default=3)
    bucket = models.CharField(max_length=12, default=BUCKET_ANYTIME, db_index=True)
    scheduled_for = models.DateField(null=True, blank=True)
    # Shared routines are what StatZ members browse. Off by default: a half-built
    # plan in someone's Inbox is not a publication.
    is_public = models.BooleanField(default=False)
    # Snapshot of the equipment the routine was built against, so a member can
    # tell at a glance whether it fits the room they're standing in.
    equipment = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "bucket"]),
                   models.Index(fields=["is_public", "-updated_at"])]

    def __str__(self):
        return f"{self.owner}/{self.name}"

    @property
    def muscles(self):
        """Every muscle this routine touches, primary and secondary."""
        hit = []
        for re_ in self.exercises.select_related("exercise"):
            for m in [re_.exercise.muscle] + list(re_.exercise.secondary or []):
                if m not in hit:
                    hit.append(m)
        return hit

    @property
    def estimated_minutes(self):
        """Rough duration: working time plus rest. Rest dominates, which is why
        a "quick" 5-exercise session with 3-minute rests is 40 minutes."""
        total = 0
        for re_ in self.exercises.all():
            per_set = 45 + (re_.rest_seconds or 0)      # ~45s under the bar
            total += (re_.sets or 0) * per_set
        return round(total / 60) if total else 0


class RoutineExercise(models.Model):
    """One exercise inside a routine, with its targets.

    `superset_group` is the mechanic that makes supersets work without a second
    model: exercises sharing a non-empty group in the same routine are performed
    back to back, and only the last one in the group takes the rest.
    """
    routine = models.ForeignKey(Routine, on_delete=models.CASCADE, related_name="exercises")
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name="in_routines")
    order = models.PositiveSmallIntegerField(default=0)
    sets = models.PositiveSmallIntegerField(default=3)
    reps = models.PositiveSmallIntegerField(default=10)
    rest_seconds = models.PositiveSmallIntegerField(default=90)
    target_weight = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    tempo = models.CharField(max_length=16, blank=True, default="")
    superset_group = models.CharField(max_length=8, blank=True, default="")
    notes = models.CharField(max_length=300, blank=True, default="")
    is_warmup = models.BooleanField(default=False)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.routine_id}:{self.exercise.name} {self.sets}x{self.reps}"

    @property
    def target_volume(self):
        """sets x reps x weight — the number progressive overload moves."""
        if self.target_weight is None:
            return None
        return float(self.target_weight) * (self.sets or 0) * (self.reps or 0)


class WorkoutSession(models.Model):
    """One training session, live or finished."""

    STATUS_ACTIVE = "active"
    STATUS_DONE = "done"
    STATUS_ABANDONED = "abandoned"
    STATUSES = [STATUS_ACTIVE, STATUS_DONE, STATUS_ABANDONED]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="bodiez_sessions")
    routine = models.ForeignKey(Routine, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="sessions")
    name = models.CharField(max_length=120, blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, default=STATUS_ACTIVE, db_index=True)
    perceived_effort = models.PositiveSmallIntegerField(null=True, blank=True)  # 1-10
    notes = models.CharField(max_length=500, blank=True, default="")
    location = models.ForeignKey("GymLocation", on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="sessions")

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["user", "-started_at"])]

    def __str__(self):
        return f"{self.user}·{self.started_at:%Y-%m-%d}·{self.status}"

    @property
    def duration_minutes(self):
        if not self.ended_at:
            return None
        return round((self.ended_at - self.started_at).total_seconds() / 60)

    @property
    def total_volume(self):
        """Sum of weight x reps across every completed working set."""
        total = 0.0
        for s in self.sets.filter(completed=True, is_warmup=False):
            if s.weight is not None and s.reps:
                total += float(s.weight) * s.reps
        return round(total, 1)


class WorkoutSet(models.Model):
    """One set. The atom everything else is computed from."""

    session = models.ForeignKey(WorkoutSession, on_delete=models.CASCADE, related_name="sets")
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name="sets")
    set_number = models.PositiveSmallIntegerField(default=1)
    weight = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    reps = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    distance_m = models.PositiveIntegerField(null=True, blank=True)
    rpe = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    rir = models.PositiveSmallIntegerField(null=True, blank=True)
    rest_seconds = models.PositiveSmallIntegerField(null=True, blank=True)
    is_warmup = models.BooleanField(default=False)
    completed = models.BooleanField(default=True)
    note = models.CharField(max_length=200, blank=True, default="")
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["exercise_id", "set_number", "id"]
        indexes = [models.Index(fields=["session", "exercise"])]

    def __str__(self):
        return f"{self.exercise.name} #{self.set_number}: {self.weight}x{self.reps}"

    @property
    def volume(self):
        if self.weight is None or not self.reps:
            return 0.0
        return round(float(self.weight) * self.reps, 1)

    @property
    def estimated_1rm(self):
        """Epley: w x (1 + reps/30). Standard, and honest only to ~10 reps —
        past that it flatters you, which is why it's capped."""
        if self.weight is None or not self.reps or self.reps > 12:
            return None
        return round(float(self.weight) * (1 + self.reps / 30.0), 1)


class BodyMetric(models.Model):
    """A body check-in. One per member per day; a re-check overwrites."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="bodiez_metrics")
    date = models.DateField(db_index=True)
    weight = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    body_fat = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    neck = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    shoulders = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    chest = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    waist = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    hips = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    arms = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    thighs = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    calves = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    note = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-date"]
        unique_together = ("user", "date")


class FitnessGoal(models.Model):
    """A target with a number on it. Without one, "get in shape" never completes."""

    TYPE_WEIGHT = "bodyweight"
    TYPE_LIFT = "lift"
    TYPE_HABIT = "habit"
    TYPE_MEASURE = "measurement"
    TYPES = [TYPE_WEIGHT, TYPE_LIFT, TYPE_HABIT, TYPE_MEASURE]

    STATUS_ACTIVE = "active"
    STATUS_HIT = "hit"
    STATUS_MISSED = "missed"
    STATUS_ABANDONED = "abandoned"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="bodiez_goals")
    goal_type = models.CharField(max_length=16, default=TYPE_HABIT)
    title = models.CharField(max_length=140)
    target_value = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    current_value = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=16, blank=True, default="")
    exercise = models.ForeignKey(Exercise, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="goals")
    deadline = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, default=STATUS_ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def progress_pct(self):
        if self.target_value in (None, 0) or self.current_value is None:
            return None
        return round(min(100.0, float(self.current_value) / float(self.target_value) * 100), 1)


class GymLocation(models.Model):
    """A room and what's in it. PREMIUM — see the views for the gate.

    The point isn't a map pin; it's that "what can I actually do here" is a
    different answer in a hotel gym than in your usual place, and re-picking your
    equipment every time you travel is the friction that stops people logging.
    """
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="bodiez_locations")
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=250, blank=True, default="")
    equipment = models.JSONField(default=list, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "name"]
        unique_together = ("owner", "name")

    def __str__(self):
        return self.name

    @property
    def muscle_coverage(self):
        """Which muscle groups this room can actually train, from its equipment.

        This is the Jefit-style metric worth having: a location isn't "has 12
        machines", it's "you cannot train back here".
        """
        from .catalog import EXERCISES, can_perform

        # Bodyweight is always on hand — see catalog.exercises_for for why.
        have = set(self.equipment or []) | {"bodyweight"}
        covered = set()
        for _k, _n, primary, secondary, needs, _p, _d in EXERCISES:
            # can_perform, NOT set(needs).issubset(have): a requirement can be a
            # tuple meaning "any of these", and issubset would compare the tuple
            # itself against the equipment set and always miss.
            if can_perform(needs, have):
                covered.add(primary)
                covered.update(secondary)
        return [m for m in MUSCLE_KEYS if m in covered]

    @property
    def gaps(self):
        return [m for m in MUSCLE_KEYS if m not in self.muscle_coverage and m != "full-body"]


class BodieZItem(models.Model):
    """Anything captured before it becomes a routine — the Lilith layer.

    A workout idea, an exercise to try, a note, a meal thought. It lands in
    Inbox 📥 and gets sorted, which is the difference between a training app and
    a training *system*.
    """
    KIND_IDEA = "idea"
    KIND_EXERCISE = "exercise"
    KIND_NOTE = "note"
    KIND_GOAL = "goal"
    KIND_MEAL = "meal"
    KINDS = [KIND_IDEA, KIND_EXERCISE, KIND_NOTE, KIND_GOAL, KIND_MEAL]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="bodiez_items")
    bucket = models.CharField(max_length=12, default=BUCKET_INBOX, db_index=True)
    kind = models.CharField(max_length=12, default=KIND_IDEA)
    title = models.CharField(max_length=200)
    note = models.CharField(max_length=1000, blank=True, default="")
    due_at = models.DateField(null=True, blank=True)
    routine = models.ForeignKey(Routine, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="items")
    done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "bucket"])]

    def __str__(self):
        return f"{self.bucket}:{self.title[:40]}"
