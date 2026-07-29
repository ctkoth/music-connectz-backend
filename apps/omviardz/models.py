"""OmviardZ progress — one row per member, so the tour survives a reinstall.

Deliberately one row and not an event log: the client needs "where was I and
what did they say", not analytics. Answers are kept because they're the whole
point of a guided tour — Corey referring back to what you told him at step one
is what makes it feel like a person walked you through it.
"""
from django.conf import settings
from django.db import models

from .tour import TRACK_DEFAULT, TRACKS, first_step, track_steps

TRACK_CHOICES = [(k, k) for k in TRACKS]


class TourProgress(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="omviardz_progress"
    )
    track = models.CharField(max_length=16, choices=TRACK_CHOICES, default=TRACK_DEFAULT)
    step_key = models.CharField(max_length=32, default=first_step)
    # Step keys already answered, in order.
    done_keys = models.JSONField(default=list, blank=True)
    # {step_key: {"choice": "1", "label": "…", "text": "…"}} — what they told us.
    answers = models.JSONField(default=dict, blank=True)
    skipped = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "tour progress"

    def __str__(self):
        state = "done" if self.completed_at else ("skipped" if self.skipped else self.step_key)
        return f"{self.user}·{self.track}·{state}"

    # ---------------------------------------------------------------- helpers
    @property
    def total_steps(self):
        return len(track_steps(self.track))

    @property
    def done_count(self):
        """How many steps on the CURRENT track are answered.

        Switching tracks mid-tour (which is exactly what answering step one
        does) leaves behind keys that aren't on the new route, so count the
        intersection rather than len(done_keys) — otherwise the progress bar
        can read 7/9 on a track you just started.
        """
        keys = set(track_steps(self.track))
        return len([k for k in self.done_keys if k in keys])

    def record(self, step_key, choice="", label="", text=""):
        if step_key not in self.done_keys:
            self.done_keys = list(self.done_keys) + [step_key]
        answers = dict(self.answers or {})
        answers[step_key] = {"choice": choice, "label": label, "text": text}
        self.answers = answers

    def as_dict(self):
        return {
            "track": self.track,
            "step": self.step_key,
            "done": list(self.done_keys),
            "done_count": self.done_count,
            "total": self.total_steps,
            "answers": dict(self.answers or {}),
            "skipped": self.skipped,
            "completed": bool(self.completed_at),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


def progress_for(user):
    """This member's progress row, created on first look."""
    row, _ = TourProgress.objects.get_or_create(
        user=user, defaults={"track": TRACK_DEFAULT, "step_key": first_step()}
    )
    return row
