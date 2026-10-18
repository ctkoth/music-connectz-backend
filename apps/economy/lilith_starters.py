"""Lilith's starter tasks and routines — names and descriptions a member can add in one tap.

Every starter points at a REAL action (`app_key` + `target` are the same data-tour anchors
`goToSpot` lands on), so each is a door and not a sentence, and each is `source="platform"`:
ticking it pays XP only, because the action it points at already has its own economy and Lilith
never pays twice for one piece of work (see `lilith_taskz.complete`). Nothing here mints.

The notes say what the action pays or doesn't, in the cost/gain spirit, and in Lilith's voice:
warm, certain, never chirpy and never a nag. A routine's `cadence` decides what "kept" means —
once a day, once a calendar week, once a calendar month — and its streak counts those periods.

One list, so the screen, the add endpoint and the tests cannot disagree about what exists.
`app_key` must be a real tab; `test_lilith_starters` checks that against the frontend's tab list
when it can read it and against the backend's own list otherwise.
"""

# kind: quick | standard | deep | boss     bucket: where it lands when added
TASKS = [
    {"key": "fix_weakest", "title": "Fix your weakest dimension", "kind": "deep", "bucket": "upcoming",
     "action": "skill_training", "goal": 1,
     "app_key": "singz", "target": "skillz-panel",
     "note": "Open your history, find what scored lowest, and complete one drill on it. The drills are free and waiting there."},
    {"key": "weekly_challenge", "title": "Answer this week's challenge", "kind": "standard", "bucket": "today",
     "app_key": "singz", "target": "weekly-open",
     "note": "Everyone gets the same genre and tempo this week, so your score means something next to theirs."},
    {"key": "rate_three", "title": "Rate three posts", "kind": "quick", "bucket": "today",
     "action": "rating_given", "goal": 3,
     "app_key": "ratez", "target": "ratez-queue",
     "note": "Listen properly, rate honestly. Each rating pays +1 ⚡ (up to the daily cap) and moves a real creator's numbers."},
    {"key": "leave_reason", "title": "Leave a reason with a rating", "kind": "quick", "bucket": "anytime",
     "app_key": "ratez", "target": "ratez-queue",
     "note": "One line on why. It reaches the performer only, and it is the part of a rating that teaches."},
    {"key": "post_finished", "title": "Post something finished", "kind": "standard", "bucket": "upcoming",
     "action": "post_made", "goal": 1,
     "app_key": "postz", "target": "post-compose",
     "note": "Not perfect — finished. A post is how anyone finds you, and how ratings start."},
    {"key": "check_results", "title": "See how your last post did", "kind": "quick", "bucket": "anytime",
     "app_key": "viewz", "target": "viewz-tracks",
     "note": "Views, who stayed, who came back. The numbers are yours at every tier; names are StatZ's."},
    {"key": "answer_collab", "title": "Answer a collab", "kind": "standard", "bucket": "today",
     "app_key": "collabz", "target": "collabz-deals",
     "note": "Someone put you on a deal or is waiting on you. Accept it, move it, or say no kindly."},
    {"key": "start_collab", "title": "Start a collab", "kind": "deep", "bucket": "upcoming",
     "action": "collab_started", "goal": 1,
     "app_key": "collabz", "target": "collabz-partner",
     "note": "Name a partner and what each of you brings. The price in ⚡ is shown before you confirm."},
    {"key": "message_member", "title": "Message someone you'd work with", "kind": "quick", "bucket": "anytime",
     "action": "message_sent", "goal": 1,
     "app_key": "messagez", "target": "messagez-compose",
     "note": "One specific sentence about their work beats a hundred 'nice'. Send it."},
    {"key": "write_hook", "title": "Write the hook", "kind": "deep", "bucket": "upcoming",
     "action": "sentence_written", "goal": 1,
     "app_key": "sentenceconnectz", "target": "sentencez-write",
     "note": "Give it the idea; it gives you something to argue with. Keep the part that is yours."},
    {"key": "share_card", "title": "Share a score card", "kind": "quick", "bucket": "anytime",
     "action": "card_shared", "goal": 1,
     "app_key": "singz", "target": "sz-recent",
     "note": "The card shows the result and the reason, never the work. Anyone who joins from it is a referral."},
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
    {"key": "breathe", "title": "Take two minutes to breathe", "kind": "quick", "bucket": "today",
     "action": "breath_session", "goal": 1,
     "app_key": "breathz", "target": "breathz-pacer",
     "note": "Paced breathing, free. It earns XP for turning up and never moves a rating."},
    {"key": "journal_one", "title": "Write one honest paragraph", "kind": "quick", "bucket": "today",
     "action": "journal_entry", "goal": 1,
     "app_key": "journalz", "target": "journalz-composer",
     "note": "What you made, what you're stuck on. A take can be attached, so the day has its evidence."},
    {"key": "enter_battle", "title": "Enter a battle", "kind": "boss", "bucket": "upcoming",
     "action": "battle_entered", "goal": 1,
     "app_key": "battlez", "target": "battlez-list",
     "note": "Judges outside the two of you decide the winner. Any stake is stated before you confirm."},
    {"key": "release_day", "title": "Release day", "kind": "boss", "bucket": "someday",
     "action": "release_made", "goal": 1,
     "app_key": "distributez", "target": "distributez-releases",
     "note": "Take one finished track all the way out the door. The big one — give it a real date."},
    {"key": "check_royalties", "title": "Check your royalties", "kind": "quick", "bucket": "anytime",
     "app_key": "royaltiez", "target": "",
     "note": "What your tracks earned and what their ratings did to it, shown before it pays out."},
    {"key": "book_lesson", "title": "Book a lesson, or offer one", "kind": "deep", "bucket": "someday",
     "action": "lesson_booked", "goal": 1,
     "app_key": "lessonz", "target": "",
     "note": "Learn from someone rated 6★ or better in the skill — or, at 6★ yourself, teach it."},
    {"key": "log_workout", "title": "Log a workout", "kind": "standard", "bucket": "today",
     "action": "workout_logged", "goal": 1,
     "app_key": "bodiez", "target": "",
     "note": "Weight first, then reps. A body that can sit through a long session plays longer."},
    {"key": "invite_musician", "title": "Invite one musician", "kind": "quick", "bucket": "anytime",
     "action": "invite_joined", "goal": 1,
     "app_key": "profilez", "target": "refer",
     "note": "Your handle is the code. Both of you are paid when they join — the amounts are on the screen."},
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
]

# ---------------------------------------------------------------- per instrument
# One "record a take" task and one daily routine for EVERY coach, so a rapper is pointed at RapZ and
# a drummer at DrumZ, and each is verified against that coach's own scored takes. Generated from the
# coach list (lilith_actions.coaches) rather than typed seven more times, so a new coach gets both.
def _label(app):
    from .instruments import profile_for_app
    return profile_for_app(app)["label"]


def _build_per_coach():
    from . import lilith_actions as A
    for app in A.coaches():
        noun = A.COACH_NOUN.get(app, "Take")
        lab = _label(app)
        TASKS.append({"key": f"take_{app}", "title": f"Record a {lab} take", "kind": "standard", "bucket": "today",
                      "action": f"take_{app}", "goal": 1, "app_key": app, "target": "bosstake-mic",
                      "note": f"Send one take to the {lab} coach. The score is the reward; Lilith only keeps your place."})
        ROUTINES.append({"key": f"daily_{app}", "title": f"The Daily {noun}", "cadence": "daily",
                         "action": f"take_{app}", "goal": 1, "app_key": app, "target": "bosstake-mic",
                         "note": f"One {lab} take a day. The score pays itself; the run is what Lilith counts."})


# The rap pack, because a rapper's week is not a singer's: bars on paper, off the top, and a room.
TASKS.extend([
    {"key": "record_freestyle", "title": "Record a freestyle", "kind": "standard", "bucket": "today",
     "action": "freestyle_posted", "goal": 1, "app_key": "postz", "target": "post-freestyle",
     "note": "Off the top, unwritten. Mark it freestyle when you post and it keeps its own label."},
    {"key": "write_sixteen", "title": "Write sixteen bars", "kind": "deep", "bucket": "upcoming",
     "action": "sentence_written", "goal": 1, "app_key": "sentenceconnectz", "target": "sentencez-write",
     "note": "Sixteen on paper first. Punchlines, hooks and rhymes are one tap away; keep the lines that are yours."},
    {"key": "enter_cypher", "title": "Step into a cypher", "kind": "boss", "bucket": "upcoming",
     "action": "freestyle_battle", "goal": 1, "app_key": "battlez", "target": "battlez-list",
     "note": "A freestyle or cypher battle. Judges outside the room decide it, and any stake is stated first."},
])
ROUTINES.extend([
    {"key": "off_the_top", "title": "Off the Top", "cadence": "weekly",
     "action": "freestyle_posted", "goal": 1, "app_key": "postz", "target": "post-freestyle",
     "note": "One freestyle a week. Unwritten on purpose — it trains the part of you the page can't."},
    {"key": "write_sixteen", "title": "Sixteen on Paper", "cadence": "weekly",
     "action": "sentence_written", "goal": 1, "app_key": "sentenceconnectz", "target": "sentencez-write",
     "note": "Write sixteen bars a week, then take them to the coach. Flow, timing, breath, clarity, delivery."},
    {"key": "cypher_night", "title": "Cypher Night", "cadence": "monthly",
     "action": "freestyle_battle", "goal": 1, "app_key": "battlez", "target": "battlez-list",
     "note": "Once a month, put the bars in front of people who will judge them."},
])

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
}

# Starters about "my instrument" rather than a particular one: they open on the coach the member
# works on (a rapper's weekly challenge is in RapZ), defaulting to the starter's own.
INSTRUMENT_AWARE = {"weekly_challenge", "weak_spot", "monthly_recap", "fix_weakest", "share_card"}

TASK_KEYS = {t["key"] for t in TASKS}
ROUTINE_KEYS = {r["key"] for r in ROUTINES}
# Task and routine keys may overlap ("weekly_challenge"); the add endpoint names which it means.


def task_by_key(key):
    return next((t for t in TASKS if t["key"] == key), None)


def routine_by_key(key):
    return next((r for r in ROUTINES if r["key"] == key), None)
