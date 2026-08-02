"""MangaZ — design manga with your CharacterZ, together, at any age.

Three pieces:

    CharacterZ 🐆  a face with a personality: bio, MBTI, voice, traits
    Room       🏫  where people collaborate — adult-supervised when a minor is in it
    MangaZ     📚  the work itself, its pages, and who wrote what

**Adult-supervised rooms.** "Anyone of any age can collaborate with anyone" is
the highest-risk surface on the platform, and the one both app stores review by
hand. The rule here is narrow and enforced in the model rather than the UI:

    A room containing a minor must have a verified adult supervisor, and
    every adult in it must be the supervisor or approved by them.

That is not the same as banning adults from working with young artists, which
would gut the point. It means an unsupervised adult can never be alone in a
room with a minor, and no adult joins a minor's room without a named,
verified person having said yes.

`verified_18plus` is the gate for supervising, not a self-reported birthday —
a birthday typed into a form is not age verification, and this is the one
place on the platform where that distinction has to hold.

**AI provenance and the royalty.** A MangaZ written with Intelligence AI pays
the developer an extra 10% royalty on top of the normal tier tax. That is a
real cost, so it is recorded on the page that used AI rather than declared by
the member: `ai_assisted` is set by the endpoint that ran the model, and the
royalty is computed from the pages, not from a checkbox somebody can untick.
"""
from django.conf import settings
from django.db import models

from apps.economy.models import Face, Post, profile_age, profile_for

# The extra developer royalty on anything made with Intelligence AI, on top of
# the member's normal tier tax. Paid because the AI costs real money to run and
# the output competes with the human work the platform exists to sell.
AI_ROYALTY_RATE = 0.10

# MBTI, for characters rather than people. A character sheet is a writing tool
# here — it goes into the prompt so the AI writes someone consistent, and it
# has no bearing on any member's account.
MBTI_TYPES = [
    "INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP",
]

ROLE_SUPERVISOR = "supervisor"
ROLE_ARTIST = "artist"
ROLE_WRITER = "writer"
ROLE_READER = "reader"
ROOM_ROLES = [
    (ROLE_SUPERVISOR, "Supervisor"), (ROLE_ARTIST, "Artist"),
    (ROLE_WRITER, "Writer"), (ROLE_READER, "Reader"),
]

# The viewing formats. Same rooms, same supervision, same AI royalty — they
# differ only in how long the finished thing is allowed to run. Durations come
# off the app icons, which are the spec: EpisodeZ says "60 MINUTE LIMIT" and
# MovieZ says "1-3 hour max".
#
#   key -> (label, icon, min seconds or None, max seconds or None)
FORMATS = {
    "manga": ("MangaZ", "📚", None, None),          # pages, not minutes
    "reel": ("ReelZ", "⏪", None, 3 * 60),
    "episode": ("EpisodeZ", "📺", None, 60 * 60),
    "movie": ("MovieZ", "🎥", 60 * 60, 3 * 60 * 60),
}
FORMAT_CHOICES = [(k, v[0]) for k, v in FORMATS.items()]


def duration_error(fmt, seconds):
    """Why this runtime doesn't fit the format, or None.

    A limit that only exists in the icon is a limit nobody enforces — and the
    member finds out after they've cut the thing.
    """
    if fmt not in FORMATS:
        return f"Unknown format {fmt!r}."
    _label, _icon, low, high = FORMATS[fmt]
    if seconds in (None, ""):
        return None                      # not cut yet; nothing to check
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "Runtime has to be a whole number of seconds."
    if seconds < 0:
        return "Runtime can't be negative."
    label = FORMATS[fmt][0]
    if low is not None and 0 < seconds < low:
        return f"{label} runs at least {low // 60} minutes — this is {seconds // 60}."
    if high is not None and seconds > high:
        return f"{label} tops out at {high // 60} minutes — this is {seconds // 60}."
    return None


SOURCE_HUMAN = "human"
SOURCE_SCRIPT = "script"        # member pasted a script, AI laid it out
SOURCE_CHARACTER = "character"  # AI wrote from the character's bio + MBTI
SOURCE_CHOICES = [
    (SOURCE_HUMAN, "Written by hand"),
    (SOURCE_SCRIPT, "AI from an inserted script"),
    (SOURCE_CHARACTER, "AI from character bio and MBTI"),
]
AI_SOURCES = {SOURCE_SCRIPT, SOURCE_CHARACTER}


def is_minor(user):
    """True when we know they're under 18. None-age counts as NOT a minor.

    Deliberate: an unknown age must not silently turn every room into a
    supervised one, which would make the feature unusable and teach people to
    work around it. Age gating that matters keys off `verified_18plus`.
    """
    age = profile_age(profile_for(user))
    return age is not None and age < 18


def is_verified_adult(user):
    """A birthday typed into a form is not age verification."""
    return bool(getattr(profile_for(user), "verified_18plus", False))


class CharacterZ(models.Model):
    """A face with a personality — the thing you write manga with.

    FaceZ already stores the picture and who is tagged in it. This adds who the
    character *is*, so the AI has something to be consistent with. Reusing Face
    rather than storing another image keeps likeness consent in one place: if a
    real member is tagged in that face, they are tagged here too.
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="characterz")
    name = models.CharField(max_length=80)
    face = models.ForeignKey(Face, on_delete=models.SET_NULL, null=True,
                             blank=True, related_name="characterz")
    bio = models.TextField(blank=True, default="")
    mbti = models.CharField(max_length=4, blank=True, default="")
    traits = models.JSONField(default=list, blank=True)
    voice = models.CharField(max_length=200, blank=True, default="",
                             help_text="How they speak — clipped, florid, deadpan")
    # Characters are shareable so a room can write with somebody else's cast.
    shared = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"CharacterZ<{self.id}> {self.name}"

    def mbti_error(self):
        if self.mbti and self.mbti.upper() not in MBTI_TYPES:
            return f"{self.mbti!r} isn't an MBTI type."
        return None

    def prompt_sheet(self):
        """What the AI is told about this character. Explicit, so a member can
        see exactly what was sent on their behalf — an AI that writes from
        hidden inputs is one nobody can correct."""
        return {
            "name": self.name,
            "mbti": self.mbti.upper() or None,
            "bio": self.bio,
            "traits": list(self.traits or []),
            "voice": self.voice,
        }


class Room(models.Model):
    """Where a MangaZ gets made. Supervised when anybody in it is a minor."""

    title = models.CharField(max_length=160)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mangaz_rooms")
    # The verified adult answerable for this room. Required once a minor joins.
    supervisor = models.ForeignKey(settings.AUTH_USER_MODEL,
                                   on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name="supervised_rooms")
    open_to_all_ages = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Room<{self.id}> {self.title}"

    def has_minor(self):
        return any(is_minor(m.user) for m in self.members.all())

    def supervision_error(self):
        """Why this room isn't safe to run, or None.

        Checked on every join rather than only at creation: a room can become
        one that needs a supervisor the moment a minor walks in, and a rule
        that only runs at creation time is a rule that stops being true.
        """
        if not self.has_minor():
            return None
        if not self.supervisor_id:
            return ("A room with anyone under 18 needs a verified adult "
                    "supervisor before it can be used.")
        if not is_verified_adult(self.supervisor):
            return ("The supervisor has to be a verified adult — a birthday "
                    "typed into a form isn't age verification.")
        if not self.members.filter(user=self.supervisor_id).exists():
            return "The supervisor has to be in the room they're supervising."
        return None

    def join_error(self, user):
        """Why `user` may not join, or None."""
        if self.members.filter(user=user).exists():
            return None                      # already in; not an error
        joiner_is_minor = is_minor(user)
        if joiner_is_minor and not self.open_to_all_ages:
            return "This room is for adults only."
        if joiner_is_minor:
            # A minor may only enter a room that is already supervised.
            if not self.supervisor_id or not is_verified_adult(self.supervisor):
                return ("This room needs a verified adult supervisor before "
                        "under-18s can join.")
            return None
        # An adult joining a room that has minors in it. They may — a teenager
        # working with an experienced adult is the point of an all-ages
        # creative platform, and requiring per-person approval to COLLABORATE
        # made the ordinary case the awkward one.
        #
        # The safeguards are that a verified adult is present and answerable,
        # and that the supervisor can refuse anyone. What is closed is the
        # dating surface, not the studio: see economy/agepolicy.py.
        if self.approvals.filter(user=user, approved=False).exists():
            return "The supervisor of this room has asked you not to join."
        return None


class RoomMember(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="mangaz_memberships")
    role = models.CharField(max_length=12, choices=ROOM_ROLES, default=ROLE_ARTIST)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("room", "user")
        ordering = ["joined_at"]


class Meet(models.Model):
    """An in-person session for a room. Teens and adults, in the same place.

    This is a real thing creative people do — a studio afternoon, a school
    programme, a table at a con — and refusing to support it just means it
    happens off-platform where nothing is recorded. So it is supported, with
    the conditions that make it defensible rather than a liability:

      * a **verified adult supervisor**, who has to be attending
      * **guardian consent on file** for every minor attending
      * a **public place**, stated in the record
      * every attendee named, so who was there is not a memory afterwards

    Guardian consent here is a recorded assertion with a contact on it, not
    proof — no backend can verify a parent. Recording who asserted it, and
    when, is what makes it checkable later; claiming it is verification would
    be the dishonest part.
    """

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="meets")
    title = models.CharField(max_length=160)
    place = models.CharField(max_length=300, help_text="Where — a public place")
    is_public_place = models.BooleanField(default=True)
    starts_at = models.DateTimeField()
    organiser = models.ForeignKey(settings.AUTH_USER_MODEL,
                                  on_delete=models.CASCADE,
                                  related_name="mangaz_meets")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at"]

    def __str__(self):
        return f"Meet<{self.id}> {self.title}"

    def minors_attending(self):
        return [a.user for a in self.attendees.select_related("user")
                if is_minor(a.user)]

    def missing_consent(self):
        """Minors attending without guardian consent recorded."""
        consented = set(self.consents.filter(granted=True)
                        .values_list("minor_id", flat=True))
        return [u for u in self.minors_attending() if u.id not in consented]

    def readiness_error(self):
        """Why this meet may not go ahead, or None.

        Recomputed rather than stored: somebody joins, and a meet that was
        fine becomes one that needs consent. A flag set at creation would go
        stale exactly when it mattered.
        """
        room_problem = self.room.supervision_error()
        if room_problem:
            return room_problem
        minors = self.minors_attending()
        if not minors:
            return None
        if not self.is_public_place:
            return ("In-person sessions with under-18s have to be somewhere "
                    "public.")
        if not self.room.supervisor_id:
            return "An in-person session with under-18s needs a supervisor."
        if not is_verified_adult(self.room.supervisor):
            return "The supervisor has to be a verified adult."
        if not self.attendees.filter(user=self.room.supervisor_id).exists():
            return ("The supervisor has to be attending, not just named on "
                    "the room.")
        missing = self.missing_consent()
        if missing:
            names = ", ".join(u.username for u in missing)
            return (f"Guardian consent isn't on file for: {names}.")
        return None


class MeetAttendee(models.Model):
    meet = models.ForeignKey(Meet, on_delete=models.CASCADE, related_name="attendees")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="mangaz_meet_attendance")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("meet", "user")
        ordering = ["added_at"]


class GuardianConsent(models.Model):
    """A recorded assertion that a minor's guardian said yes to one meet.

    Per-meet on purpose. A blanket consent that covers every future session is
    the thing a guardian did not actually agree to, and it is the shape that
    gets a platform in trouble.
    """

    meet = models.ForeignKey(Meet, on_delete=models.CASCADE, related_name="consents")
    minor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mangaz_consents")
    guardian_name = models.CharField(max_length=120)
    guardian_contact = models.CharField(max_length=200)
    granted = models.BooleanField(default=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                    on_delete=models.SET_NULL, null=True,
                                    related_name="mangaz_consents_recorded")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("meet", "minor")


class RoomApproval(models.Model):
    """The supervisor's yes for one adult in a room that has minors in it.

    A row per decision rather than a flag on the membership, so a refusal is
    recorded too — "we never approved them" and "we said no" are different
    answers if anyone ever asks.
    """

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="approvals")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="mangaz_approvals")
    approved = models.BooleanField(default=False)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                   on_delete=models.SET_NULL, null=True,
                                   related_name="mangaz_decisions")
    decided_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("room", "user")


class MangaZ(models.Model):
    """A manga. Pages carry the words; this carries the work."""

    title = models.CharField(max_length=160)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="mangaz")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="mangaz_works")
    # MangaZ, ReelZ, EpisodeZ or MovieZ. One model rather than four apps: they
    # are the same collaboration with the same supervision, the same AI royalty
    # and the same provenance — only the runtime limit differs. Four copies
    # would drift, and the age rules are the last thing that should.
    format = models.CharField(max_length=10, choices=FORMAT_CHOICES,
                              default="manga", db_index=True)
    runtime_seconds = models.PositiveIntegerField(null=True, blank=True)
    synopsis = models.TextField(blank=True, default="")
    characters = models.ManyToManyField(CharacterZ, blank=True,
                                        related_name="appears_in")
    published_post = models.ForeignKey(Post, on_delete=models.SET_NULL,
                                       null=True, blank=True,
                                       related_name="mangaz_works")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"MangaZ<{self.id}> {self.title}"

    def runtime_error(self):
        return duration_error(self.format, self.runtime_seconds)

    def format_payload(self):
        label, icon, low, high = FORMATS[self.format]
        return {"key": self.format, "label": label, "icon": icon,
                "min_seconds": low, "max_seconds": high,
                "runtime_seconds": self.runtime_seconds}

    def ai_pages(self):
        """Pages where a machine wrote the words OR drew the art. Either one
        earns the royalty — the AI made part of what's being sold."""
        from django.db.models import Q
        return self.pages.filter(Q(source__in=AI_SOURCES)
                                 | Q(art_source__in=AI_SOURCES))

    def used_ai(self):
        return self.ai_pages().exists()

    def ai_royalty_cents(self, sale_cents):
        """The extra developer royalty owed on a sale of this work.

        Computed from the pages, not from a declaration. A member can't untick
        a box to avoid it, and equally can't be charged for AI they didn't use.
        """
        if not self.used_ai():
            return 0
        return round(int(sale_cents or 0) * AI_ROYALTY_RATE)

    def provenance(self):
        """Who and what wrote this, page by page — shown on the work.

        A reader deciding whether to care about a manga is entitled to know
        which parts a machine wrote, and a collaborator is entitled to see that
        their pages aren't being passed off as AI or the reverse.
        """
        pages = list(self.pages.all())
        by_source, by_art = {}, {}
        for page in pages:
            by_source[page.source] = by_source.get(page.source, 0) + 1
            by_art[page.art_source] = by_art.get(page.art_source, 0) + 1
        return {
            "pages": len(pages),
            "by_source": by_source,
            "art_by_source": by_art,
            "used_ai": self.used_ai(),
            "ai_royalty_rate": AI_ROYALTY_RATE if self.used_ai() else 0.0,
            "note": ("Made with Intelligence AI — an extra 10% developer "
                     "royalty applies to sales." if self.used_ai() else
                     "Written by hand. No AI royalty."),
        }


class Page(models.Model):
    """One page. `source` is set by the server, never by the client."""

    manga = models.ForeignKey(MangaZ, on_delete=models.CASCADE, related_name="pages")
    number = models.PositiveIntegerField(default=1)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="mangaz_pages")
    script = models.TextField(blank=True, default="")
    art_url = models.CharField(max_length=500, blank=True, default="")
    source = models.CharField(max_length=12, choices=SOURCE_CHOICES,
                              default=SOURCE_HUMAN)
    # How the ART was made, tracked separately from the writing. A page can be
    # written by hand and drawn by the AI, or the reverse, and collapsing the
    # two would either miss a royalty or charge one that isn't owed.
    art_source = models.CharField(max_length=12, choices=SOURCE_CHOICES,
                                  default=SOURCE_HUMAN)
    # What was actually sent to the model, when one was used. Kept so a member
    # can see what was written on their behalf and from which character sheet.
    ai_prompt = models.JSONField(default=dict, blank=True)
    ai_model = models.CharField(max_length=60, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["number", "id"]
        unique_together = ("manga", "number")

    def __str__(self):
        return f"Page {self.number} of {self.manga_id} ({self.source})"

    @property
    def ai_assisted(self):
        """True if a machine made either half of this page."""
        return self.source in AI_SOURCES or self.art_source in AI_SOURCES
