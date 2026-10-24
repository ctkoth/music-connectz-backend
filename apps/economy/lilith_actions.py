"""The things a member can DO that the platform already records — and so can be verified.

Corey: Lilith can make call-to-action routines — get a SkillZ score, make a post, send a message.
The audit behind this list is "which member actions leave a row of their own that nobody can
type in": each entry below is a table the app already writes when the action really happens,
read by user and by time.

That is the whole reason a routine built on one is allowed to be ticked by Lilith and not by the
member. A hand-typed tick is unverified (so it pays XP and a token coin at most); a row in
`TakeScore` is a performance that was scored. The streak built from them is the "you cannot
backdate a habit" claim made literally true, because Lilith counts only rows created AFTER the
routine or task existed.

Nothing here pays. The action pays whatever it already pays, through its own economy; Lilith adds
XP and the streak, and never a second reward for the same work.

NOT in the list, on purpose (no honest record to verify against):
  * profile edits — `Profile.updated_at` moves for reasons that are not the member's work
    (a zodiac recompute, a visibility merge), so it cannot count "did something";
  * reading or listening — heartbeats exist, but "listened to a track" is the easiest thing in
    the app to fake with a tab left open;
  * "was kind", "practised offline" and the like — a typed tick, and Lilith keeps those as
    ordinary self tasks with ordinary self-task rules.

Each entry's `qs(user)` is exercised against a fresh user by `test_lilith_actions`, so a renamed
field is a red test and not a routine that silently never ticks.
"""
from datetime import datetime  # noqa: F401  (documentation of the time type)

from django.utils import timezone

EVENT_CAP = 5000       # the most rows read for one action in one sweep


def _m():
    """Models, imported lazily: this module is imported by lilith_taskz at load time."""
    from . import models as M
    return M


# key → label (the call to action, imperative), unit (what one of them is), app_key/target (the
# control that does it, for goToSpot), qs(user) → queryset of that member's rows, time field.
def _specs():
    M = _m()
    from apps.lessonz import models as L
    from apps.skillz.models import TrainingEvent
    return {
        # ---- get scored / practise
        "take_scored": dict(label="Get a SkillZ score", unit="scored take", app_key="singz", target="bosstake-mic",
                            qs=lambda u: M.TakeScore.objects.filter(user=u, overall__isnull=False), time="created_at"),
        "drill_done": dict(label="Finish a pitch drill", unit="drill", app_key="tunerz", target="tunerz-drill",
                           qs=lambda u: M.DrillTake.objects.filter(user=u), time="created_at"),
        "practice_session": dict(label="Practise with MetZ, TunerZ, ChordZ or DrumZ", unit="session", app_key="metz", target="metz-bpm",
                                 qs=lambda u: M.PracticeSession.objects.filter(user=u), time="created_at"),
        "breath_session": dict(label="Do a breathing session", unit="session", app_key="breathz", target="breathz-pacer",
                               qs=lambda u: TrainingEvent.objects.filter(profile__user=u, profile__app_key="breathz", xp_awarded__gt=0),
                               time="created_at"),
        "skill_training": dict(label="Complete a SkillZ drill", unit="drill", app_key="singz", target="skillz-panel",
                               qs=lambda u: TrainingEvent.objects.filter(profile__user=u, xp_awarded__gt=0), time="created_at"),
        # ---- make something
        "post_made": dict(label="Make a post", unit="post", app_key="postz", target="post-compose",
                          qs=lambda u: M.Post.objects.filter(author=u), time="created_at"),
        "journal_entry": dict(label="Write a journal entry", unit="entry", app_key="journalz", target="journalz-composer",
                              qs=lambda u: M.JournalEntry.objects.filter(author=u), time="created_at"),
        "sentence_written": dict(label="Write something with Sentence ConnectZ", unit="piece", app_key="sentenceconnectz", target="sentencez-write",
                                 qs=lambda u: M.SentenceWork.objects.filter(user=u), time="created_at"),
        "instrumental_made": dict(label="Make an instrumental", unit="instrumental", app_key="instrumentalconnectz", target="",
                                  qs=lambda u: M.InstrumentalWork.objects.filter(user=u), time="created_at"),
        "video_made": dict(label="Make a video", unit="video", app_key="videoconnectz", target="",
                           qs=lambda u: M.VideoWork.objects.filter(user=u), time="created_at"),
        "mix_made": dict(label="Master a mix", unit="mix", app_key="mixconnectz", target="mixz-start",
                         qs=lambda u: M.MasterWork.objects.filter(user=u), time="created_at"),
        "release_made": dict(label="Start a release", unit="release", app_key="distributez", target="distributez-releases",
                             qs=lambda u: M.Release.objects.filter(user=u), time="created_at"),
        "playlist_made": dict(label="Make a playlist", unit="playlist", app_key="playlistz", target="playlistz-add",
                              qs=lambda u: M.Playlist.objects.filter(owner=u), time="created_at"),
        "upload_made": dict(label="Upload a file", unit="upload", app_key="postz", target="post-compose",
                            qs=lambda u: M.Upload.objects.filter(user=u), time="created_at"),
        # ---- people
        "message_sent": dict(label="Send a message", unit="message", app_key="messagez", target="messagez-compose",
                             qs=lambda u: M.Message.objects.filter(sender=u), time="created_at"),
        "rating_given": dict(label="Rate a post", unit="rating", app_key="ratez", target="ratez-queue",
                             qs=lambda u: M.ItemRating.objects.filter(user=u, created_at__isnull=False), time="created_at"),
        "comment_made": dict(label="Leave a comment", unit="comment", app_key="social", target="social-feed",
                             qs=lambda u: M.SocialComment.objects.filter(user=u), time="created_at"),
        "post_shared": dict(label="Share a post", unit="share", app_key="postz", target="feed",
                            qs=lambda u: M.PostShare.objects.filter(user=u), time="shared_at"),
        "card_shared": dict(label="Share a score card", unit="card", app_key="singz", target="sz-recent",
                            qs=lambda u: M.ScoreShare.objects.filter(user=u), time="created_at"),
        "follow_made": dict(label="Follow a member", unit="follow", app_key="social", target="social-feed",
                            qs=lambda u: M.Follow.objects.filter(follower=u), time="created_at"),
        "invite_joined": dict(label="Get someone to join from your invite", unit="member", app_key="profilez", target="refer",
                              qs=lambda u: M.Referral.objects.filter(referrer=u), time="created_at"),
        # ---- work together
        "collab_started": dict(label="Start a collab", unit="deal", app_key="collabz", target="collabz-partner",
                               qs=lambda u: M.CollabDeal.objects.filter(initiator=u), time="created_at"),
        "battle_entered": dict(label="Enter a battle", unit="entry", app_key="battlez", target="battlez-list",
                               qs=lambda u: M.BattleEntry.objects.filter(user=u), time="created_at"),
        "lesson_booked": dict(label="Book a lesson", unit="booking", app_key="lessonz", target="",
                              qs=lambda u: L.LessonBooking.objects.filter(student=u), time="created_at"),
        "lesson_offered": dict(label="Offer a lesson", unit="offer", app_key="lessonz", target="",
                               qs=lambda u: L.LessonOffer.objects.filter(teacher=u), time="created_at"),
        # ---- body
        "workout_logged": dict(label="Log a workout", unit="workout", app_key="bodiez", target="",
                               qs=lambda u: M.BodieZSession.objects.filter(user=u, ended_at__isnull=False), time="started_at"),
    }


# What a take is called for each coach — the noun a member recognises, used in the routine's name.
COACH_NOUN = {"singz": "Vocal", "rapz": "Verse", "guitarz": "Riff", "bassz": "Groove", "keyz": "Keys",
              "drumz": "Pattern", "violinz": "Phrase", "flutez": "Line", "saxz": "Line",
              "clarinetz": "Line", "trumpetz": "Line"}


def coaches():
    """The instruments that have a coach, in the app's own order."""
    from .instruments import INSTRUMENTS
    return list(INSTRUMENTS)


def specs():
    out = _specs()
    M = _m()
    # Freestyle is a way of making the thing, not a genre (Post.freestyle), so it is verified from
    # the flag the composer sets; a freestyle battle from the battle's own kind.
    out["freestyle_posted"] = dict(label="Post a freestyle", unit="freestyle", app_key="postz", target="post-freestyle",
                                   qs=lambda u: M.Post.objects.filter(author=u, freestyle=True), time="created_at")
    out["freestyle_battle"] = dict(label="Enter a freestyle or cypher battle", unit="entry", app_key="battlez", target="battlez-list",
                                   qs=lambda u: M.BattleEntry.objects.filter(user=u, battle__kind__in=("freestyle", "cypher")),
                                   time="created_at")
    # One per coach, so "get a RapZ score" is its own verified action and a rapper's streak is not
    # kept alive by a SingZ take.
    from .instruments import profile_for_app
    for app in coaches():
        out[f"take_{app}"] = dict(
            label=f"Get a {profile_for_app(app)['label']} score", unit="scored take",
            app_key=app, target="bosstake-mic",
            qs=(lambda a: (lambda u: M.TakeScore.objects.filter(user=u, app_key=a, overall__isnull=False)))(app),
            time="created_at")
    return out


def catalogue():
    """What the screen offers when a member builds their own call-to-action."""
    return [{"key": k, "label": v["label"], "unit": v["unit"], "app_key": v["app_key"], "target": v["target"]}
            for k, v in specs().items()]


def events(user, action, since):
    """When this member did `action` at or after `since` — newest first, capped. Aware datetimes."""
    spec = specs().get(action)
    if not spec:
        return []
    field = spec["time"]
    qs = spec["qs"](user).filter(**{f"{field}__gte": since}).order_by(f"-{field}")
    return list(qs.values_list(field, flat=True)[:EVENT_CAP])


def localdate(dt):
    return timezone.localtime(dt).date() if timezone.is_aware(dt) else dt.date()
