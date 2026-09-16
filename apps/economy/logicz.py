"""LogicZ — every tab has an address, an icon, and something it says for itself.

Three rules from the spec, and each one fixes something real:

**Every tab opens on its own URL**, named after the tab with the trailing Z
dropped — `/post`, `/battle`, `/sing`, `/collab`. Until now the whole app lived
at `/` and switched tabs through a custom event, which meant no tab could be
linked, bookmarked, or reached by the back button. A screen with no address is
a screen you can only tell somebody how to find.

**Clicking a tab's icon opens a modal** that says what the tab is, in Corey's
voice, with the apps that live inside it. The tab list gave a name and an emoji
and nothing else; a member had to open a thing to learn what it was.

**The apps inside a tab are listed with whether they're BUILT.** A modal that
promises five apps and delivers one is worse than a modal that promises one —
so `built` is on every row, and the client shows the rest as what's coming
rather than as links that go nowhere.

The slug is derived, never typed: the tab key minus a trailing "z". Typing it
would let the address and the tab drift apart, and the address is the part
people paste to each other.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


def slug_for(key):
    """`battlez` → `battle`. Derived so an address can't drift from its tab."""
    key = (key or "").lower()
    return key[:-1] if key.endswith("z") and len(key) > 2 else key


def _app(name, emoji, desc, built=False, tab=""):
    return {"name": name, "emoji": emoji, "desc": desc, "built": built, "tab": tab}


# The tabs this app actually has, each with what it is and what's inside it.
# Descriptions are Corey's, kept in his voice rather than rewritten into
# product-speak, because the modal is where the app talks to the member.
LOGICZ_TABS = [
    {"key": "postz", "name": "PostZ", "emoji": "🪧", "icon": "postz.png",
     "desc": "Where the work goes up. One of each — a track, a video, a cover, "
             "the script — and the room rates it, likes it, argues with it.",
     "apps": [
         _app("Visibility", "👁️", "Public, members only, or just you.", True),
         _app("Mood", "🫥", "How you felt posting it.", False),
         # A member self-reports engagement their own SoundCloud track got and
         # earns Energy/SpinaZ for it — a different thing from the import
         # below, which brings the tracks THEMSELVES in. Neither had a row
         # here before this, so neither was discoverable from the one screen
         # whose job is saying what this app has.
         _app("SoundCloud Engagement", "📈",
              "Report a like, repost or comment your own track got, capped "
              "daily per kind.", True, tab="soundcloudengagementz"),
     ]},
    {"key": "collabz", "name": "CollabZ", "emoji": "🤝", "icon": "collabz.png",
     "desc": "PostZ is for show. This is where it becomes work — escrowed, so a "
             "stranger can take the first deal without either of you praying.",
     "apps": [
         _app("CoverZ", "🫴🏼", "Covers of songs, redraws of existing art.", False),
         _app("RemixeZ", "🔄", "Remixing posts and songs.", False),
     ]},
    {"key": "battlez", "name": "BattleZ", "emoji": "🪖", "icon": "battlez.png",
     "desc": "One post against another. Verified 18+ can bet money on themselves; "
             "everybody else bets SpinaZ.",
     "apps": [
         _app("1v1", "1️⃣", "One artist against one artist, whoever else helped.", True),
         # Both built: `BattleEnterView` accepts kind in (1v1, freestyle,
         # cypher) and BattleZ offers all three in its picker. They each have
         # their own drawn icon. The flag was the only thing saying otherwise.
         _app("Freestyle", "🆓", "Live, sporadic battles.", True, tab="battlez"),
         _app("Battle Cypher", "🧑‍🤝‍🧑", "More than one against more than one.",
              True, tab="battlez"),
     ]},
    {"key": "social", "name": "Social ConnectZ", "emoji": "💓", "icon": "social_connectz.png",
     "desc": "The room itself — who's here, who's rated, who's looking.",
     "apps": [
         # Spelled VybeZ, which is what the tab is called and what the member
         # will be looking for. It was "VibeZ" here and `built=False`, on a
         # screen whose entire job is telling somebody what this app has —
         # while VybeZ has been a mounted tab with its own icon. A live
         # feature labelled "not built yet" is worse than one nobody
         # mentioned: it tells people not to go looking.
         _app("VybeZ", "♥️", "Dating and collab, with what you're after stated plainly.",
              True, tab="vybez"),
         _app("Inferno", "❤️‍🔥", "The fast version of the same thing.", False),
         _app("BoardZ", "🪧", "Message boards.", False),
         # NOT "MBTI tests". Myers-Briggs is somebody's trademark and this
         # module is member-facing copy, so it was the one place on the
         # platform publishing it — while `personalityz.py`'s own docstring
         # says in as many words that we deliberately do not call it that. It
         # is four declared axes, it is built, and it lives in ProfileZ.
         _app("PersonalitieZ", "😶",
              "Four axes you declare yourself. Neither side is better, and it "
              "never moves a rating.", True, tab="profilez"),
         # Same shape as PersonalitieZ right above it, so it does not become
         # the next entry on the "told members it didn't exist" list: a
         # declared, filterable field, built, and it lives in ProfileZ.
         _app("ReligionZ", "🕊️",
              "One declared tradition out of fifty, grouped into families. "
              "No tradition outranks another, and it never moves a rating.",
              True, tab="profilez"),
         # Same shape again — multi-select this time, because a member
         # commonly speaks several, but the same declared-never-scored rule.
         _app("LanguageZ", "🗣️",
              "The languages you speak, so people who can actually talk to "
              "you can find you. Never moves a rating.", True, tab="profilez"),
     ]},
    {"key": "messagez", "name": "MessageZ", "emoji": "📨", "icon": "messagez.png",
     "desc": "Direct messages. In and out.",
     "apps": [_app("Inbox", "📥", "What came in.", True),
              _app("Outbox", "📤", "What you sent.", True)]},
    {"key": "playlistz", "name": "PlaylistZ", "emoji": "🎧", "icon": "playlistz.png",
     "desc": "Sets built from posts and outside links, together in one run.",
     "apps": [_app("Collaborators", "🤝", "Other members who can add to it.", True)]},
    {"key": "occ", "name": "OCC", "emoji": "👁️‍🗨️", "icon": "occ.png",
     "desc": "Ocular Code ConnectZ. Write it, track it, version it — and now run it.",
     "apps": [
         _app("TaskZ", "📑", "What OCC is doing, with an ETA and an undo window.", True),
         _app("WorkZ", "🧾", "What you gave it and what it gave back, ready to post.", True),
         _app("Settings", "⚙️", "AutomationZ and SuggestionZ live here.", True),
         _app("GitZ", "🔀", "Branches, commits and pushes — each one a task.", False),
     ]},
    {"key": "keyconnectz", "name": "KeyConnectZ", "emoji": "⌨️", "icon": "keyconnectz.png",
     "desc": "The keyboard. Premium buys the wallpaper; everybody gets to be understood.",
     "apps": [_app("Translate", "🗺️", "Any language to any other, as you type.", True)]},
    {"key": "singz", "name": "SingZ", "emoji": "👩🏼‍🎤", "icon": "singz.png",
     "desc": "Vocal training — range, quests, Boss SongZ. Voice health first.",
     "apps": [_app("Coach", "🤖", "What to practise next, and why.", True)]},
    {"key": "rapz", "name": "RapZ", "emoji": "👨🏼‍🎤", "icon": "rapz.png",
     "desc": "Breath control, flow, sixteen style tracks and a combo meter.",
     "apps": [_app("Coach", "🤖", "What to practise next, and why.", True)]},
    {"key": "labelz", "name": "LabelZ", "emoji": "🏷️", "icon": "labelz.png",
     "desc": "Public groups — a label anyone can find and ask to join.", "apps": []},
    {"key": "groupz", "name": "GroupZ", "emoji": "👥", "icon": "groupz.png",
     "desc": "Your own groupings of other members. Local to you, editable, private.",
     "apps": []},
    {"key": "directz", "name": "DirectZ", "emoji": "🎬", "icon": "directz.png",
     "desc": "Video work, filed and rated.", "apps": []},
    {"key": "mimez", "name": "MimeZ", "emoji": "🤡", "icon": "mimez.png",
     "desc": "Perform without saying anything.", "apps": []},
    {"key": "lessonz", "name": "LessonZ", "emoji": "🎓", "icon": "lessonz.png",
     "desc": "Guided paths, technique breakdowns, mini-courses.", "apps": []},
    {"key": "profilez", "name": "ProfileZ", "emoji": "👤", "icon": "personaz.png",
     "desc": "Who you are here — names, personas, the skills you claim and what "
             "they cost.",
     "apps": [
         _app("PersonaZ", "🎭", "Your creative personas and the skills they carry.", True),
         _app("SocialZ", "🌐", "Linked accounts, verified — the reach that pays Energy.", True),
         _app("BadgeZ", "🏅", "A title you wear and an effect you feel.", True),
         _app("SoundCloud Import", "🎧",
              "Bring your catalogue in as private drafts — free, and nothing "
              "is shown until you publish each one.", True, tab="profilez"),
     ]},
    {"key": "specz", "name": "SpecZ", "emoji": "📋", "icon": "specz.png",
     "desc": "What your device can take, and what the app will ask of it.", "apps": []},
    {"key": "membershipz", "name": "MembershipZ", "emoji": "💵", "icon": "money.png",
     "desc": "Free, Premium, StatZ — what each one costs and what it lifts.",
     "apps": [_app("Founding Fifty", "🏛️", "Half price for life, first fifty only.", True)]},
    {"key": "adz", "name": "AdZ", "emoji": "📺", "icon": "adz.png",
     "desc": "Watch and earn — when there's something to watch.", "apps": []},
    {"key": "offerz", "name": "OfferZ", "emoji": "🎁", "icon": "offerz.png",
     "desc": "Offers that pay SpinaZ for doing something outside the app.", "apps": []},
    {"key": "logz", "name": "LogZ", "emoji": "🪵", "icon": "logz.png",
     # "by day, week, month, or a range you pick" described filters LogZ does
     # not have — it narrows by resource and caps a page, and that is all. The
     # same claim was corrected in features.py when LogZ was unlocked and this
     # copy was left behind, which is how a member ends up reading a promise on
     # one screen and meeting a different app on the next.
     "desc": "Every move your balances made, and when. Narrow it to one resource.",
     "apps": []},
    {"key": "journalz", "name": "JournalZ", "emoji": "📔", "icon": "journalz.png",
     "desc": "The diary. Every other tab here publishes — this one keeps its mouth "
             "shut until you tell it not to. Tag people and a place like a post; "
             "on a private entry that tells nobody anything.",
     "apps": [
         _app("Entries", "📝", "A day, written down — mood, weather, tags, a place.", True),
         _app("On This Day", "🕰️", "The same date in every year you've kept. Premium.", True),
         _app("Export", "📦", "The whole journal as one file. Premium.", True),
         _app("Publish", "🪧", "Turn an entry into a PostZ — the one thing here that "
                               "tells anybody anything.", True),
     ]},
    {"key": "habitz", "name": "HabitZ", "emoji": "🎂", "icon": "habitz.png",
     "desc": "Something you repeat, noticed and kept.", "apps": []},
    {"key": "bugz", "name": "BugZ", "emoji": "🐞", "icon": "bugz.png",
     "desc": "Found something broken? Post it. Only an admin can close it.", "apps": []},
    {"key": "onboardz", "name": "OnboardZ", "emoji": "🛂", "icon": "onboardz.png",
     "desc": "Start here. Every step links to the control that finishes it.", "apps": []},
]


def tabs_payload():
    out = []
    for t in LOGICZ_TABS:
        out.append({**t, "slug": slug_for(t["key"]),
                    "url": f"/{slug_for(t['key'])}",
                    "built_apps": sum(1 for a in t["apps"] if a["built"]),
                    "total_apps": len(t["apps"])})
    return out


class LogicZView(APIView):
    """GET /api/economy/logicz/ — the tabs, their addresses, and what's in them.

    Served rather than hardcoded on the client for the same reason every other
    registry here is: the description a member reads and the thing they land on
    have to come from one place.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tabs = tabs_payload()
        return Response({
            "tabs": tabs,
            "slugs": {t["key"]: t["slug"] for t in tabs},
            "note": "Every tab has its own address — /post, /battle, /sing. "
                    "Paste one and it opens there.",
        })
