"""Lilith's starters: the one-off tasks and the RoutineZ a member can add in one tap.

Every starter points at a REAL action or a real tab (`app_key` + `target` are the same data-tour anchors
`goToSpot` lands on), so each is a door and not a sentence.

The split is deliberate. Anything a member DOES on the platform on a rhythm — messaging someone, starting
a collab, taking a coach take, making a picture, entering a battle, a release, a lesson — is a RoutineZ:
kept once a day, week, month or year, with a streak the platform can verify when it has an action. A
TASK is for setting something up once: finishing a profile, verifying your age, bringing in a SoundCloud,
answering a collab that is waiting on you. A habit is never a task, and a task is never a habit in
disguise.

Two paths pay, and they are kept apart. A platform TASK pays XP only, because the action it points at
already has its own economy and Lilith never pays twice for one piece of work (`lilith_taskz.complete`).
A RoutineZ keeps a streak, and its milestone rungs are the consistency reward (`lilith_taskz.keep_routine`).
An automation's routine keeps its streak and pays nothing: automation may never mint.

The cadence decides what "kept" means — once a day, once a calendar week, once a calendar month, once a
calendar year — and the streak counts those periods.

One list, so the screen, the add endpoint and the tests cannot disagree about what exists. `app_key` must
be a real tab; `test_lilith_cta` checks that against the frontend's tab list when it can read it.
"""

# kind: quick | standard | deep | boss     bucket: where it lands when added
# One-off set-up steps. Nothing on this list recurs.
TASKS = [
    {"key": "pick_persona", "title": "Say what you are", "kind": "quick", "bucket": "today",
     "app_key": "profilez", "target": "personas",
     "note": "Pick a persona and the skills you actually have. It's how collaborators find you, and Lilith suggests better from it."},
    {"key": "finish_profile", "title": "Finish your profile", "kind": "standard", "bucket": "upcoming",
     "app_key": "profilez", "target": "profile-fields",
     "note": "A bio, your skills and a region. It is the first thing a collaborator reads."},
    {"key": "portfolio_links", "title": "Add your best links", "kind": "standard", "bucket": "anytime",
     "app_key": "profilez", "target": "portfolio-links",
     "note": "Tracks, videos, shops. They open right on the screen, so a visitor never has to leave."},
    {"key": "import_soundcloud", "title": "Bring in your SoundCloud", "kind": "standard", "bucket": "anytime",
     "app_key": "profilez", "target": "sc-import",
     "note": "Your existing tracks, playable here and rated here, without uploading anything twice."},
    {"key": "verify_18", "title": "Verify you're 18+", "kind": "standard", "bucket": "anytime",
     "app_key": "profilez", "target": "",
     "note": "Government ID and a selfie, handled by Stripe. It unlocks money battles, and the screen tells you exactly how the check ended."},
    {"key": "answer_collab", "title": "Answer a collab", "kind": "standard", "bucket": "today",
     "app_key": "collabz", "target": "collabz-deals",
     "note": "Someone put you on a deal or is waiting on you. Accept it, move it, or say no kindly."},
]

ROUTINES = [
    # ------------------------------------------------------------- daily
    {"key": "breathe_first", "title": "Breathe First", "cadence": "daily",
     "action": "breath_session", "goal": 1,
     "app_key": "breathz", "target": "breathz-pacer",
     "note": "Two minutes of paced breathing before you play. Steadier air, steadier pitch."},
    {"key": "with_the_click", "title": "Ten With the Click", "cadence": "daily",
     "action": "practice_session", "goal": 1,
     "app_key": "metz", "target": "metz-bpm",
     "note": "Ten minutes against the metronome. Timing is the dimension that answers fastest to practice."},
    {"key": "three_ears", "title": "Three Ears", "cadence": "daily",
     "action": "rating_given", "goal": 3,
     "app_key": "ratez", "target": "ratez-queue",
     "note": "Rate three posts and give one a reason. Each rating pays +1 ⚡, up to the daily cap."},
    {"key": "one_paragraph", "title": "One Honest Paragraph", "cadence": "daily",
     "action": "journal_entry", "goal": 1,
     "app_key": "journalz", "target": "journalz-composer",
     "note": "A few true sentences about the work. Consistency is the one thing nobody can fake."},
    {"key": "move_body", "title": "Move Your Body", "cadence": "daily",
     "action": "workout_logged", "goal": 1,
     "app_key": "bodiez", "target": "",
     "note": "Any workout logged counts, a short one included."},
    # ------------------------------------------------------------ weekly
    {"key": "weekly_challenge", "title": "The Week's Challenge", "cadence": "weekly",
     "app_key": "singz", "target": "weekly-open",
     "note": "Answer the shared prompt — same genre and tempo as everyone — so your score has company."},
    {"key": "ship_one", "title": "Ship One Thing", "cadence": "weekly",
     "action": "post_made", "goal": 1,
     "app_key": "postz", "target": "post-compose",
     "note": "One finished post a week. A small cadence beats a big silence."},
    {"key": "read_the_room", "title": "Read the Room", "cadence": "weekly",
     "app_key": "viewz", "target": "viewz-tracks",
     "note": "Who listened, who stayed, who came back. Look once a week and decide one thing from it."},
    {"key": "move_a_collab", "title": "Move a Collab Forward", "cadence": "weekly",
     "app_key": "collabz", "target": "collabz-deals",
     "note": "Open your deals and push one a step: a file, a reply, a release."},
    {"key": "reach_out", "title": "Reach Out", "cadence": "weekly",
     "action": "message_sent", "goal": 1,
     "app_key": "messagez", "target": "messagez-compose",
     "note": "One message to a member whose work you'd want to be on. Specific, short, sincere."},
    {"key": "weak_spot", "title": "Train One Skill", "cadence": "weekly",
     "action": "skill_training", "goal": 1,
     "app_key": "singz", "target": "skillz-panel",
     "note": "One SkillZ drill a week, on whichever dimension your history says scored lowest."},
    {"key": "make_picture", "title": "Make a picture", "cadence": "weekly",
     "action": "image_made", "goal": 1,
     "app_key": "imageconnectz", "target": "imagez-make",
     "note": "Describe it, or start from a photo or a face. The price is on the button before you press it."},
    {"key": "save_picture", "title": "Save a finished picture", "cadence": "weekly",
     "action": "picture_saved", "goal": 1,
     "app_key": "imagez", "target": "",
     "note": "Layers, text and cut-outs, on your device and free. It counts once it's saved to FileZ."},
    {"key": "share_card", "title": "Share a score card", "cadence": "weekly",
     "action": "card_shared", "goal": 1,
     "app_key": "singz", "target": "sz-recent",
     "note": "The card shows the result and the reason, never the work. Anyone who joins from it is a referral."},
    {"key": "leave_a_reason", "title": "Leave a reason with a rating", "cadence": "weekly",
     "app_key": "ratez", "target": "ratez-queue",
     "note": "One line on why. It reaches the performer only, and it is the part of a rating that teaches."},
    # ----------------------------------------------------------- monthly
    {"key": "monthly_recap", "title": "The Monthly Recap", "cadence": "monthly",
     "app_key": "singz", "target": "sz-recent",
     "note": "Open your month: takes, personal bests, what moved. Share the card if it flatters you."},
    {"key": "count_the_coin", "title": "Count the Coin", "cadence": "monthly",
     "app_key": "royaltiez", "target": "",
     "note": "What your tracks earned, and what their ratings did to it — before it paid, not after."},
    {"key": "release_day", "title": "Release Day", "cadence": "monthly",
     "action": "release_made", "goal": 1,
     "app_key": "distributez", "target": "distributez-releases",
     "note": "Start one release a month. The finished track needs a date, and so does the next one."},
    {"key": "tidy_portfolio", "title": "Tidy the Portfolio", "cadence": "monthly",
     "app_key": "profilez", "target": "portfolio-links",
     "note": "Prune and reorder your links so the best work is first."},
    {"key": "skill_check", "title": "Skill Check", "cadence": "monthly",
     "app_key": "ratez", "target": "ratez-dashboard",
     "note": "See how listeners rated your skills and pick the one you'll raise next month."},
    {"key": "learn_from_someone", "title": "Learn From Someone", "cadence": "monthly",
     "action": "lesson_booked", "goal": 1,
     "app_key": "lessonz", "target": "",
     "note": "Book one lesson a month with someone ahead of you. The price is shown before you book."},
    {"key": "manga_page", "title": "Make a manga page", "cadence": "monthly",
     "action": "manga_page", "goal": 1,
     "app_key": "mangaz", "target": "mangaz-new",
     "note": "Panels, your characters' voices and faces, one page. A page is the start of a chapter, and an AnimeZ later."},
    {"key": "face_for_cast", "title": "Add a face for your cast", "cadence": "monthly",
     "action": "face_made", "goal": 1,
     "app_key": "facez", "target": "",
     "note": "A face you keep in FaceZ can be drawn into pictures and manga panels again and again."},
    {"key": "cut_video", "title": "Cut a video in VideoZ", "cadence": "monthly",
     "action": "video_saved", "goal": 1,
     "app_key": "videoz", "target": "videoz-add",
     "note": "Tracks, titles and crossfades on your device, free. It counts once the cut is saved to FileZ."},
    {"key": "make_video", "title": "Make a video with Video ConnectZ", "cadence": "monthly",
     "action": "video_made", "goal": 1,
     "app_key": "videoconnectz", "target": "",
     "note": "From a prompt, a picture or your own track. The price is on the button, and a failed render is not charged."},
    {"key": "make_instrumental", "title": "Make an instrumental", "cadence": "monthly",
     "action": "instrumental_made", "goal": 1,
     "app_key": "instrumentalconnectz", "target": "",
     "note": "A beat to write to, or one to sell. It's yours to post, battle on or send to a DAW."},
    {"key": "master_mix", "title": "Master a mix", "cadence": "monthly",
     "action": "mix_made", "goal": 1,
     "app_key": "mixconnectz", "target": "mixz-start",
     "note": "Free and on your device. Every move the master makes says why."},
    {"key": "start_collab", "title": "Start a collab", "cadence": "monthly",
     "action": "collab_started", "goal": 1,
     "app_key": "collabz", "target": "collabz-partner",
     "note": "Name a partner and what each of you brings. The price in ⚡ is shown before you confirm."},
    {"key": "enter_battle", "title": "Enter a battle", "cadence": "monthly",
     "action": "battle_entered", "goal": 1,
     "app_key": "battlez", "target": "battlez-list",
     "note": "Judges outside the two of you decide the winner. Any stake is stated before you confirm."},
    # ------------------------------------------------------------ yearly
    # Yearly rungs start at three (lilith_taskz.CADENCE_MILESTONES): the earliest a yearly streak can
    # pay is about a year after the first keep, never a day.
    {"key": "invite_musician", "title": "Invite one musician", "cadence": "yearly",
     "action": "invite_joined", "goal": 1,
     "app_key": "profilez", "target": "refer",
     "note": "Your handle is the code. Both of you are paid when they join — the amounts are on the screen."},
    {"key": "release_a_year", "title": "Put a release out this year", "cadence": "yearly",
     "action": "release_made", "goal": 1,
     "app_key": "distributez", "target": "distributez-releases",
     "note": "Start one release this calendar year and Lilith keeps it from the record. The big one gets a real date."},
    {"key": "year_in_review", "title": "The year in review", "cadence": "yearly",
     "app_key": "viewz", "target": "viewz-tracks",
     "note": "Once a year, look at what your work did: the takes, the people, the numbers. Keep the one that surprised you."},
    # ------------------------------------------------- rap pack
    {"key": "off_the_top", "title": "Off the Top", "cadence": "weekly",
     "action": "freestyle_posted", "goal": 1, "app_key": "postz", "target": "post-freestyle",
     "note": "One freestyle a week. Unwritten on purpose — it trains the part of you the page can't."},
    {"key": "write_sixteen", "title": "Sixteen on Paper", "cadence": "weekly",
     "action": "sentence_written", "goal": 1, "app_key": "sentenceconnectz", "target": "sentencez-write",
     "note": "Write sixteen bars a week, then take them to the coach. Flow, timing, breath, clarity, delivery."},
    {"key": "cypher_night", "title": "Cypher Night", "cadence": "monthly",
     "action": "freestyle_battle", "goal": 1, "app_key": "battlez", "target": "battlez-list",
     "note": "Once a month, put the bars in front of people who will judge them."},
    # ------------------------------------------------- HealthZ
    # HealthZ routines. Keeping your own care plan is worth turning up for, and these are the two ways
    # Lilith can say so honestly: sleep is VERIFIED (a night is logged in HealthZ), and medication and
    # treatment are SELF-reported because nothing here can see them. Self-reported health routines pay
    # XP and nothing else — never 🍥 or ⚡, so there is no money in claiming a dose (lilith_taskz.keep_routine).
    # The notes never tell anyone what to take: that is their prescriber's.
    {"key": "health_sleep", "title": "Log Last Night's Sleep", "cadence": "daily",
     "action": "sleep_logged", "goal": 1, "app_key": "healthz", "target": "healthz-sleep",
     "note": "A night logged in HealthZ — Lilith keeps it from the log, so you don't tick it. Private to you. XP only."},
    {"key": "health_meds", "title": "Take My Medication As Prescribed", "cadence": "daily",
     "app_key": "healthz", "target": "healthz-conditions",
     "note": "Follow your prescriber, always. Lilith can't see whether you did, so you tick it, and it earns XP and nothing else. A missed day isn't a failure — and never take extra to keep a run."},
    {"key": "health_treatment", "title": "Do My Treatment Or Therapy", "cadence": "daily",
     "app_key": "healthz", "target": "healthz-conditions",
     "note": "Whatever your plan is — exercises, a session, a routine. You tick it, it earns XP and nothing else, and a missed day isn't a failure."},
]

# ---------------------------------------------------------------- per instrument
# One daily routine for EVERY coach, so a rapper is pointed at RapZ and a drummer at DrumZ, and each
# is verified against that coach's own scored takes. Generated from the coach list (lilith_actions.coaches)
# rather than typed a dozen times, so a new coach gets one. (Its take is a routine now, not a task: a
# take is something a member does on a rhythm.)
def _label(app):
    from .instruments import profile_for_app
    return profile_for_app(app)["label"]


def _build_per_coach():
    from . import lilith_actions as A
    for app in A.coaches():
        noun = A.COACH_NOUN.get(app, "Take")
        lab = _label(app)
        ROUTINES.append({"key": f"daily_{app}", "title": f"The Daily {noun}", "cadence": "daily",
                         "action": f"take_{app}", "goal": 1, "app_key": app, "target": "bosstake-mic",
                         "note": f"One {lab} take a day. The score pays itself; the run is what Lilith counts."})


_build_per_coach()

# Which starters a member working on each coach is shown first (routines only; the suggester
# reads this). Everything else in ROUTINES stays available to everybody.
INSTRUMENT_PACKS = {
    "rapz": ["daily_rapz", "off_the_top", "write_sixteen", "breathe_first", "weekly_challenge", "cypher_night"],
    "singz": ["daily_singz", "breathe_first", "with_the_click", "weekly_challenge"],
    "guitarz": ["daily_guitarz", "with_the_click", "weekly_challenge"],
    "bassz": ["daily_bassz", "with_the_click", "weekly_challenge"],
    "keyz": ["daily_keyz", "with_the_click", "weekly_challenge"],
    "drumz": ["daily_drumz", "with_the_click", "weekly_challenge"],
    "violinz": ["daily_violinz", "with_the_click", "weekly_challenge"],
    "flutez": ["daily_flutez", "breathe_first", "with_the_click"],
    "saxz": ["daily_saxz", "breathe_first", "with_the_click"],
    "clarinetz": ["daily_clarinetz", "breathe_first", "with_the_click"],
    "trumpetz": ["daily_trumpetz", "breathe_first", "with_the_click"],
    "producez": ["daily_producez", "weekly_challenge"],
}

# Starters about "my instrument" rather than a particular one: they open on the coach the member
# works on (a rapper's weekly challenge is in RapZ), defaulting to the starter's own.
INSTRUMENT_AWARE = {"weekly_challenge", "weak_spot", "monthly_recap", "share_card"}

# Starter TASKS that became ROUTINES (the same habit, now kept on a cadence). A member who still has one
# of these open on their board gets the routine instead: `manage.py lilith_platform_routines`. A task
# keyed the same as its routine needs no entry; `take_<coach>` tasks are `daily_<coach>` (see below).
RETIRED_TASKS = {
    "fix_weakest": "weak_spot", "rate_three": "three_ears", "leave_reason": "leave_a_reason",
    "post_finished": "ship_one", "check_results": "read_the_room", "message_member": "reach_out",
    "write_hook": "write_sixteen", "breathe": "breathe_first", "journal_one": "one_paragraph",
    "check_royalties": "count_the_coin", "book_lesson": "learn_from_someone", "log_workout": "move_body",
    "release_day": "release_day", "make_image": "make_picture", "edit_picture": "save_picture",
    "make_face": "face_for_cast", "cut_video": "cut_video", "make_video": "make_video",
    "make_instrumental": "make_instrumental", "master_mix": "master_mix", "manga_page": "manga_page",
    "enter_cypher": "cypher_night", "record_freestyle": "off_the_top", "write_sixteen": "write_sixteen",
    "weekly_challenge": "weekly_challenge", "share_card": "share_card", "start_collab": "start_collab",
    "enter_battle": "enter_battle", "invite_musician": "invite_musician",
}


def routine_for_retired(key):
    """The routine a retired task became, or None when the task is still a task."""
    if str(key or "").startswith("take_"):
        return f"daily_{key[len('take_'):]}"
    return RETIRED_TASKS.get(key)


TASK_KEYS = {t["key"] for t in TASKS}
ROUTINE_KEYS = {r["key"] for r in ROUTINES}
# Task and routine keys may overlap ("weekly_challenge" was both once); the add endpoint names which it means.


def task_by_key(key):
    return next((t for t in TASKS if t["key"] == key), None)


def routine_by_key(key):
    return next((r for r in ROUTINES if r["key"] == key), None)
