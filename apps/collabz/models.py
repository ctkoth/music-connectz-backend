"""CollabZ — collaborate with other members and manage collab projects.

Three kinds, matching the icons you sent:

    OriginalZ   something new, written together
    CoverZ  🫴🏼  a cover of a song, or a redraw of existing art
    RemixeZ 🔄   a remix of an existing post or song

The money side already exists: `economy.CollabDeal` is the escrow that holds
each payer's cash until release. This app is the *work* side — who's on it, what
they're contributing, and what it's built from. A project can point at a deal;
it does not reimplement escrow, because two escrows would eventually disagree
about who got paid.
"""
from django.conf import settings
from django.db import models

from apps.economy.models import CollabDeal, Post

KIND_ORIGINAL = "original"
KIND_COVER = "cover"
KIND_REMIX = "remix"
KIND_CHOICES = [
    (KIND_ORIGINAL, "OriginalZ"),
    (KIND_COVER, "CoverZ 🫴🏼"),
    (KIND_REMIX, "RemixeZ 🔄"),
]

# CoverZ and RemixeZ are derivative by definition — they need a source. An
# original doesn't, and demanding one would make the most common case the
# awkward one.
DERIVATIVE_KINDS = {KIND_COVER, KIND_REMIX}

STATUS_OPEN = "open"            # looking for collaborators
STATUS_ACTIVE = "active"        # working
STATUS_REVIEW = "review"        # waiting on sign-off
STATUS_RELEASED = "released"
STATUS_ARCHIVED = "archived"
STATUS_CHOICES = [
    (STATUS_OPEN, "Open"), (STATUS_ACTIVE, "Active"), (STATUS_REVIEW, "In review"),
    (STATUS_RELEASED, "Released"), (STATUS_ARCHIVED, "Archived"),
]

ROLE_OWNER = "owner"
ROLE_COLLABORATOR = "collaborator"
ROLE_INVITED = "invited"
ROLE_CHOICES = [
    (ROLE_OWNER, "Owner"), (ROLE_COLLABORATOR, "Collaborator"),
    (ROLE_INVITED, "Invited"),
]


class CollabProject(models.Model):
    kind = models.CharField(max_length=12, choices=KIND_CHOICES,
                            default=KIND_ORIGINAL, db_index=True)
    title = models.CharField(max_length=160)
    brief = models.TextField(blank=True, default="")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="collab_projects")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default=STATUS_OPEN, db_index=True)

    # What it's built from. Required for CoverZ and RemixeZ (see `clean`).
    source_post = models.ForeignKey(Post, on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name="collab_derivatives")
    # Free text for a cover of something not on the platform at all.
    source_credit = models.CharField(max_length=300, blank=True, default="")

    # What the collaboration produced.
    result_post = models.ForeignKey(Post, on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name="collab_results")

    # Personas being looked for, so the project shows up in searches.
    seeking = models.JSONField(default=list, blank=True)
    # The SKILLS the collab needs — required, not optional. A collab post with
    # no skill is unsearchable: nobody can be matched to "help me make a song".
    # Validated against the PersonaZ catalog so it's the 2.2 vocabulary rather
    # than free text nobody can filter on.
    skills = models.JSONField(default=list, blank=True)
    genres = models.JSONField(default=list, blank=True)
    # Who the owner will work with — the five search ranges, frozen at post
    # time. See economy.searchfilters. Applies to people joining themselves;
    # an owner's own invite is a deliberate choice and overrides the gate.
    requirements = models.JSONField(default=dict, blank=True)

    # The escrow, when there's money involved. Optional — plenty of collabs are
    # two people and no invoice.
    deal = models.OneToOneField(CollabDeal, on_delete=models.SET_NULL, null=True,
                                blank=True, related_name="collab_project")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"CollabProject<{self.id}> {self.kind} {self.title}"

    def skills_error(self):
        """A collab has to say what it needs. Returns a message or None."""
        if not self.skills:
            return ("Pick at least one skill — a collab with no skill can't be "
                    "matched to anyone.")
        return None

    def source_error(self):
        """A cover of nothing is not a cover. Returns a message or None."""
        if self.kind in DERIVATIVE_KINDS and not (self.source_post_id
                                                  or self.source_credit.strip()):
            label = dict(KIND_CHOICES)[self.kind]
            return (f"{label} needs a source — link the post it's built on, or "
                    f"credit the original if it isn't on Music ConnectZ.")
        return None

    def split_total(self):
        return sum(int(m.split_percent or 0) for m in self.members.all())

    def split_error(self):
        """Splits must land on 100 — or on 0 while it's still being worked out.

        Anything between is the dangerous case: it looks decided but doesn't add
        up, and somebody finds out when the money moves.
        """
        total = self.split_total()
        if total in (0, 100):
            return None
        return f"Splits add up to {total}%, not 100%."

    def is_member(self, user):
        return self.members.filter(user=user).exclude(role=ROLE_INVITED).exists()


class CollabMember(models.Model):
    project = models.ForeignKey(CollabProject, on_delete=models.CASCADE,
                                related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="collab_memberships")
    role = models.CharField(max_length=14, choices=ROLE_CHOICES,
                            default=ROLE_COLLABORATOR)
    # The persona they're on the project as — an artist on one, a mixer on another.
    persona = models.CharField(max_length=40, blank=True, default="")
    contribution = models.CharField(max_length=300, blank=True, default="")
    split_percent = models.PositiveIntegerField(default=0)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("project", "user")
        ordering = ["joined_at"]

    def __str__(self):
        return f"{self.user} on {self.project_id} ({self.split_percent}%)"
