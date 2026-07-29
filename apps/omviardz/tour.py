"""OmviardZ — the guided tour spec.

OmviardZ is the onboarding walkthrough: it points at ONE control at a time,
Corey explains it in his own voice, and the member answers with a single
character. Their answer decides which option gets spotlighted next, so the tour
is a conversation rather than a slideshow of tooltips.

Three things live here, and nothing else (no I/O, no models — so the spec is
trivially testable and safe to import from anywhere):

* ``STEPS``   — every step, its highlight geometry, and its options.
* ``TRACKS``  — ordered step keys per "what are you here for" answer, so a
                producer and a fan don't get the same 14 screens.
* ``design``  — mobile-first layout tokens the client renders coach-marks with.

Every option carries its OWN ``highlight`` — that is the whole mechanic. The
step spotlights the surface; picking an option spotlights the exact button
inside it and explains what it does. Options also carry a builtin ``explain``
string so the tour works with no LLM key, no network, and no charge.

Tier numbers are read from ``apps.economy.catalog`` at call time rather than
retyped here: the tutorial should never be able to promise a limit the server
doesn't actually give you.
"""

# ---------------------------------------------------------------- tracks
TRACK_MAKE = "make"
TRACK_DISCOVER = "discover"
TRACK_MONEY = "money"
TRACK_LEARN = "learn"
TRACK_DEFAULT = TRACK_MAKE

TRACK_LABELS = {
    TRACK_MAKE: "Make something",
    TRACK_DISCOVER: "Get discovered",
    TRACK_MONEY: "Get paid",
    TRACK_LEARN: "Learn the craft",
}


def _h(target, label, shape="rect", placement="below", screen=None, route=None, pulse=True):
    """One coach-mark: what to spotlight, what to call it, where the card sits.

    ``target`` is a CSS selector the client resolves. Use the stable
    ``[data-omviardz="…"]`` hooks rather than class names so a restyle can't
    silently break the tour (a missing target degrades to a centered card).
    """
    mark = {
        "target": target,
        "label": label,
        "shape": shape,          # rect | circle | pill — how the cutout is drawn
        "placement": placement,  # below | above | over — where the card lands
        "pulse": pulse,
        "scroll_into_view": True,
    }
    if screen:
        mark["screen"] = screen
    if route:
        mark["route"] = route
    return mark


# Mobile-first layout tokens. OmviardZ was designed for a phone held in one
# hand: the card is a bottom sheet inside the thumb zone, the spotlight sits
# above it, and copy is capped short enough to read without scrolling.
DESIGN = {
    "viewport": "mobile-first",
    "designed_for": {"min_width": 320, "reference_width": 390, "reference_height": 844},
    "card": {
        "placement": "bottom-sheet",
        "max_height": "46vh",
        "corner_radius": 20,
        "safe_area_inset": True,
        "dismiss": ["swipe-down", "backdrop-tap"],
        "drag_handle": True,
    },
    "spotlight": {
        "backdrop": "rgba(6,8,14,0.78)",
        "cutout_padding": 8,
        "ring_width": 3,
        "ring_color": "#7C4DFF",
        "pulse_ms": 1600,
    },
    "options": {
        # Options are tap targets first and keyboard shortcuts second — a
        # phone user taps the row, a desktop user types the character.
        "layout": "stacked",
        "min_tap_target": 48,
        "row_gap": 10,
        "reply_prefix": "#",
        "show_reply_chip": True,
    },
    "typography": {"body": 16, "title": 20, "line_height": 1.45, "min_body": 16},
    "motion": {"respect_reduced_motion": True, "step_transition_ms": 220},
    "copy_budget": {"blurb_chars": 240, "explain_chars": 700},
    "haptics": {"on_option": "light", "on_step_complete": "medium"},
}


# ---------------------------------------------------------------- steps
STEPS = {
    "welcome": {
        "screen": "home",
        "route": "/",
        "title": "🎤 Welcome — I'm Corey, I'll walk you through it",
        "blurb": (
            "🔥 This place is big on purpose — every Z is its own room. So we're not "
            "touring all of it. Tell me why you're here and I'll light up only the "
            "parts that get you there. 👀 Pick one:"
        ),
        "highlight": _h('[data-omviardz="nav"]', "Your app drawer", placement="above"),
        "input": {"kind": "choice", "allow_text": True,
                  "placeholder": "or just tell me in your own words…"},
        "options": [
            {
                "key": "1", "label": "🎧 Make something — tracks, art, video",
                "sets_track": TRACK_MAKE,
                "highlight": _h('[data-omviardz="app-distributez"]', "DistributeZ"),
                "explain": (
                    "🎧 Good — that's the shortest path to feeling like this app is yours. "
                    "We'll set up ProfileZ so your work has a face, then go straight to the "
                    "make tools: OCC for ideas and cover art, DistributeZ for the actual "
                    "audio. 💪 Everything else can wait."
                ),
            },
            {
                "key": "2", "label": "📣 Get discovered — audience, ratings",
                "sets_track": TRACK_DISCOVER,
                "highlight": _h('[data-omviardz="app-postz"]', "PostZ"),
                "explain": (
                    "📣 Then your feed presence matters more than your gear. We'll do "
                    "ProfileZ, PostZ, and the rating surfaces — because on here attention "
                    "is a score you can actually move, not a vibe. 👀"
                ),
            },
            {
                "key": "3", "label": "💸 Get paid — wallet, royalties, collabs",
                "sets_track": TRACK_MONEY,
                "highlight": _h('[data-omviardz="app-walletz"]', "WalletZ"),
                "explain": (
                    "💸 Straight to the money rooms then. WalletZ, the earn stack, royalty "
                    "cashout, and CollabZ escrow — and I'll be honest with you about the fees "
                    "at every stop. ⚖️ No surprises is the whole point."
                ),
            },
            {
                "key": "4", "label": "🧠 Learn the craft — courses, drills, lessons",
                "sets_track": TRACK_LEARN,
                "highlight": _h('[data-omviardz="app-skillz"]', "SkillZ"),
                "explain": (
                    "🧠 My favorite answer. I've been taught four college-level courses — "
                    "Digital Art, Music Theory, Marketing, and Music Legal — and SkillZ turns "
                    "practice into XP and streaks. 🏆 We'll start there."
                ),
            },
        ],
    },

    "profilez": {
        "screen": "profile",
        "route": "/profile",
        "title": "🎨 ProfileZ — this is what people judge",
        "blurb": (
            "👀 Nobody rates a track from a blank avatar. Three fields do most of the work "
            "here — photo, birthday, links. Which one do you want explained?"
        ),
        "highlight": _h('[data-omviardz="profile-card"]', "Your profile card"),
        "input": {"kind": "choice", "allow_text": True},
        "options": [
            {
                "key": "1", "label": "🖼️ Avatar — your photo",
                "highlight": _h('[data-omviardz="profile-avatar"]', "Avatar", shape="circle"),
                "explain": (
                    "🖼️ Tap the circle, pick a photo, done — and you can pull it back off "
                    "later without deleting your account. 💡 One thing: it has to be a real "
                    "image file and it counts against your storage, so a 12-megapixel "
                    "portrait is a waste. Crop it square before you upload. ✅"
                ),
            },
            {
                "key": "2", "label": "🎂 Birthday — unlocks the earn stack",
                "highlight": _h('[data-omviardz="profile-birthday"]', "Birthday"),
                "explain": (
                    "🎂 This one isn't cosmetic. Rewarded ads are 13+ by policy, and the gate "
                    "reads your birthday — no birthday, no AdZ. It also gives you your age and "
                    "zodiac on the profile. ⚖️ Set it once and the earn rooms open up."
                ),
            },
            {
                "key": "3", "label": "🔗 Links — Spotify, socials",
                "highlight": _h('[data-omviardz="profile-links"]', "Links"),
                "explain": (
                    "🔗 Drop your real ones — [Spotify](https://open.spotify.com) artist page, "
                    "socials, whatever you actually post to. Clicks get tallied, so this is "
                    "the one place on your profile that reports back. 📣 And a verified social "
                    "is worth more here than a follower count."
                ),
            },
        ],
    },

    "personaz": {
        "screen": "personaz",
        "route": "/personaz",
        "title": "🎭 PersonaZ — pick who you are today",
        "blurb": (
            "🎭 A PersonaZ is the hat you're wearing — producer, vocalist, artist, manager. "
            "It shapes what the apps put in front of you. And it's not a tattoo. 👀"
        ),
        "highlight": _h('[data-omviardz="persona-grid"]', "PersonaZ picker"),
        "input": {"kind": "choice", "allow_text": True},
        "options": [
            {
                "key": "1", "label": "🎛️ Pick one and move",
                "highlight": _h('[data-omviardz="persona-card"]', "A PersonaZ card"),
                "explain": (
                    "🎛️ Tap it and you're done. It reorders your drawer and colors what SkillZ "
                    "drills you get — nothing gets locked away. Switch it whenever the work "
                    "changes. 💪"
                ),
            },
            {
                "key": "2", "label": "🤔 Why do I need one?",
                "highlight": _h('[data-omviardz="persona-grid"]', "PersonaZ picker"),
                "explain": (
                    "🤔 Fair. Because 'show me everything' is how apps this wide get abandoned "
                    "on day two. 🧠 The persona is a filter, not a permission — you keep every "
                    "room, you just stop drowning in the ones you don't use."
                ),
            },
        ],
    },

    "occ": {
        "screen": "occ",
        "route": "/occ",
        "title": "🧠 OCC — that's me, and here's what I cost",
        "blurb": (
            "🧠 OCC is the assistant. Three voices, and I'm deliberately the cheapest one "
            "because I run on member input and the built-in courses. 💸 What do you want to "
            "know?"
        ),
        "highlight": _h('[data-omviardz="occ-composer"]', "Ask OCC", placement="above"),
        "input": {"kind": "choice", "allow_text": True,
                  "placeholder": "or ask me something right now…"},
        "options": [
            {
                "key": "1", "label": "🗣️ The three voices",
                "highlight": _h('[data-omviardz="occ-voice-picker"]', "Voice picker"),
                "explain": (
                    "🗣️ Corey GPT is me — opinionated, example-heavy, cheapest per message. "
                    "Standard is neutral and clean for anything you'll show a stranger. "
                    "Technical is code-first with no preamble. 💯 Same brain, different room "
                    "temperature — and you pay the model minimum either way, no markup."
                ),
            },
            {
                "key": "2", "label": "🎟️ Free prompts vs paying",
                "highlight": _h('[data-omviardz="occ-promptz"]', "PromptZ balance"),
                "explain": (
                    "🎟️ Every tier gets free prompts daily. Past that, a message costs a "
                    "cent or three from WalletZ — literally what the model run costs. 💡 If "
                    "you're burning through them, that's a signal to look at Premium, not to "
                    "top up twice a day."
                ),
            },
            {
                "key": "3", "label": "📚 Teach me something",
                "highlight": _h('[data-omviardz="occ-knowledge"]', "Teach OCC"),
                "explain": (
                    "📚 This is the underrated one. Anything you teach me here I treat as "
                    "authoritative and lead with next time — your chain, your gear, your "
                    "label's rules. 🧠 Same with CodeZ shorthand, so you stop retyping the "
                    "same context every session. ✅"
                ),
            },
            {
                "key": "4", "label": "🎨 Cover art and video",
                "highlight": _h('[data-omviardz="occ-image"]', "Image / video gen"),
                "explain": (
                    "🎨 Image ConnectZ does cover art, and you can hand it a reference photo "
                    "so a likeness stays yours. Video ConnectZ runs longer, so it hands you a "
                    "job you poll instead of freezing the screen. 🔥 Composition rules from the "
                    "Digital Art course apply — ask me and I'll critique the draft."
                ),
            },
        ],
    },

    "skillz": {
        "screen": "skillz",
        "route": "/skillz",
        "title": "💪 SkillZ — practice that actually scores",
        "blurb": (
            "💪 Drills, XP, streaks, badges, leaderboards — per app. It's the RPG loop applied "
            "to reps, and it's the only rating on here you fully control. 🏆"
        ),
        "highlight": _h('[data-omviardz="skillz-drills"]', "Today's drills"),
        "input": {"kind": "choice", "allow_text": True},
        "options": [
            {
                "key": "1", "label": "🎯 Start a drill",
                "highlight": _h('[data-omviardz="skillz-drill-card"]', "A drill card"),
                "explain": (
                    "🎯 Open it, do the rep, hit complete. XP lands immediately and your streak "
                    "ticks. 💡 Don't chase the big drill on day one — the streak is worth more "
                    "than any single session, same as training. Consistency compounds. 🔥"
                ),
            },
            {
                "key": "2", "label": "📈 What level buys me",
                "highlight": _h('[data-omviardz="skillz-level"]', "Your level"),
                "explain": (
                    "📈 Level isn't just a number — hit rating 6 in a skill and you can TEACH "
                    "it in LessonZ for real money. 💸 That's the cleanest earn path on the "
                    "platform: get genuinely good, then charge for it. 🧠"
                ),
            },
            {
                "key": "3", "label": "🏆 Leaderboards",
                "highlight": _h('[data-omviardz="skillz-leaderboard"]', "Leaderboard"),
                "explain": (
                    "🏆 Per app, so you're compared to people doing your thing. Brutal reality: "
                    "top of a small board beats invisible on a big one — and being visible here "
                    "is how collab offers start showing up in MessageZ. 👀"
                ),
            },
        ],
    },

    "postz": {
        "screen": "postz",
        "route": "/postz",
        "title": "📣 PostZ — the feed, and the ask",
        "blurb": (
            "📣 A post isn't only a flex here. It can be an open call people JOIN — which is "
            "how half the collabs on here start. 🎤 What do you want lit up?"
        ),
        "highlight": _h('[data-omviardz="postz-composer"]', "New post", placement="above"),
        "input": {"kind": "choice", "allow_text": True},
        "options": [
            {
                "key": "1", "label": "✍️ Write one",
                "highlight": _h('[data-omviardz="postz-composer"]', "Composer", placement="above"),
                "explain": (
                    "✍️ Say the thing, attach the file, post. Your tier sets your character "
                    "budget and your edit window — and that window is short on purpose, so the "
                    "feed can't be quietly rewritten after people react. ⚖️ Proofread once."
                ),
            },
            {
                "key": "2", "label": "🙌 Open it for joins",
                "highlight": _h('[data-omviardz="postz-join"]', "Join / submissions"),
                "explain": (
                    "🙌 This is the feature people sleep on. Post 'need a vocalist, 90 BPM, "
                    "two weeks' and let submissions come to you — then move the good one into "
                    "a CollabZ deal so the money's held in escrow. 🔥 Ask, don't scroll."
                ),
            },
            {
                "key": "3", "label": "🔗 Share it out",
                "highlight": _h('[data-omviardz="postz-share"]', "Share"),
                "explain": (
                    "🔗 Share generates a tracked link, so you find out which platform actually "
                    "sends you people instead of guessing. 📈 Two weeks of that data beats any "
                    "posting-schedule advice, mine included. 💯"
                ),
            },
        ],
    },

    "socialz": {
        "screen": "members",
        "route": "/members",
        "title": "👀 The rating rooms — read this before you post",
        "blurb": (
            "👀 Ratings are real on here: profiles, faces, works. That cuts both ways, so I'd "
            "rather you hear how it works from me than find out from a number. ⚖️"
        ),
        "highlight": _h('[data-omviardz="members-grid"]', "Members"),
        "input": {"kind": "choice", "allow_text": True},
        "options": [
            {
                "key": "1", "label": "⭐ How rating works",
                "highlight": _h('[data-omviardz="rate-control"]', "Rate"),
                "explain": (
                    "⭐ Members rate, the average shows, and your overall rating follows you "
                    "into the rooms that gate on it — LessonZ teaching, for one. 💡 Post work "
                    "you'd defend, not work you're testing. Test in DirectZ instead."
                ),
            },
            {
                "key": "2", "label": "✅ Verify a social",
                "highlight": _h('[data-omviardz="social-verify"]', "Verify"),
                "explain": (
                    "✅ Verifying a real off-platform account is the fastest credibility you "
                    "can get here, and it's free. 📣 A verified 200-follower artist reads more "
                    "real than an unverified 50k — because one of those is checkable. 👀"
                ),
            },
            {
                "key": "3", "label": "🛡️ Report / block",
                "highlight": _h('[data-omviardz="report-block"]', "Report or block"),
                "explain": (
                    "🛡️ Both are one tap from any profile or post, and you never owe anyone an "
                    "explanation for using them. 💪 Blocking is silent. Reporting goes to "
                    "moderation with the context attached — no screenshots needed."
                ),
            },
        ],
    },

    "messagez": {
        "screen": "messagez",
        "route": "/messages",
        "title": "📬 MessageZ — where the deals actually happen",
        "blurb": (
            "📬 Inbox and sent, straightforward. The part worth knowing is what NOT to do in "
            "here. 👀"
        ),
        "highlight": _h('[data-omviardz="messagez-inbox"]', "Inbox"),
        "input": {"kind": "choice", "allow_text": True},
        "options": [
            {
                "key": "1", "label": "✉️ Send one",
                "highlight": _h('[data-omviardz="messagez-compose"]', "Compose", placement="above"),
                "explain": (
                    "✉️ Pick a member, write, send — your tier sets the character budget. 💡 "
                    "Lead with what you're offering, not with 'hey'. The producers worth "
                    "reaching get twenty of those a day. 💯"
                ),
            },
            {
                "key": "2", "label": "🤝 Take it to a deal",
                "highlight": _h('[data-omviardz="collab-start"]', "Start a CollabZ deal"),
                "explain": (
                    "🤝 The moment money comes up, move it into CollabZ. Escrow holds the funds "
                    "and there's a dispute window — a DM promise has neither. ⚖️ 'I'll send it "
                    "after' is how people get burned, on every platform, every time."
                ),
            },
        ],
    },

    "walletz": {
        "screen": "walletz",
        "route": "/wallet",
        "title": "💰 WalletZ — one balance, everything comes out of it",
        "blurb": (
            "💰 AI messages, unlocks, merch, collab funding — all one balance. Top it up with "
            "card or PayPal. 💸 What do you want to see?"
        ),
        "highlight": _h('[data-omviardz="wallet-balance"]', "Balance"),
        "input": {"kind": "choice", "allow_text": True},
        "options": [
            {
                "key": "1", "label": "➕ Add funds",
                "highlight": _h('[data-omviardz="wallet-add"]', "Add funds"),
                "explain": (
                    "➕ Card via [Stripe](https://stripe.com) or "
                    "[PayPal](https://www.paypal.com) — whichever's switched on. It credits "
                    "once and only once, even if the page reloads mid-payment. 💡 Start small. "
                    "You can't spend what you haven't loaded, which is a feature. ✅"
                ),
            },
            {
                "key": "2", "label": "⚖️ The developer tax, honestly",
                "highlight": _h('[data-omviardz="wallet-tax"]', "Fees"),
                "explain": (
                    "⚖️ Money moving through the platform takes a cut, and it's lower on "
                    "higher tiers. I'd rather say it plainly than bury it: the free tier pays "
                    "the most. 💸 If you're moving real volume, the subscription mathematically "
                    "pays for itself — run your own numbers, don't take my word."
                ),
            },
            {
                "key": "3", "label": "🔄 Auto top-up",
                "highlight": _h('[data-omviardz="wallet-autotopup"]', "Auto top-up"),
                "explain": (
                    "🔄 Set a floor and it refills without you noticing. 👀 Genuinely useful if "
                    "you work in long sessions — and cancellable in one tap, so try it before "
                    "you decide it's a trap."
                ),
            },
        ],
    },

    "earnz": {
        "screen": "earnz",
        "route": "/earn",
        "title": "💸 Earn without spending — AdZ and OfferZ",
        "blurb": (
            "💸 You can fund a wallet with attention instead of cash. Both of these are 13+ "
            "and read your birthday, so ProfileZ has to be filled in first. ⚖️"
        ),
        "highlight": _h('[data-omviardz="earn-grid"]', "Earn options"),
        "input": {"kind": "choice", "allow_text": True},
        "options": [
            {
                "key": "1", "label": "📺 AdZ — rewarded video",
                "highlight": _h('[data-omviardz="adz-watch"]', "Watch to earn"),
                "explain": (
                    "📺 Watch a rewarded ad, get credited server-side once the ad network "
                    "verifies it — which is why the reward can land a beat after the video "
                    "ends. 💡 It's slow money. Good for topping off prompts, not a strategy. 👀"
                ),
            },
            {
                "key": "2", "label": "🎁 OfferZ — the offerwall",
                "highlight": _h('[data-omviardz="offerz-open"]', "Open OfferZ"),
                "explain": (
                    "🎁 Third-party tasks that pay more than an ad and take longer. Rewards are "
                    "verified by signed callback, so nothing credits on a fake redirect. ⚖️ "
                    "Read what an offer wants before you start — some want way more than "
                    "they're paying for. 😤"
                ),
            },
            {
                "key": "3", "label": "🚫 Not interested",
                "goto": "tierz",
                "explain": (
                    "🚫 Respect — plenty of people never touch these. Skipping straight to how "
                    "the tiers actually differ. 💯"
                ),
            },
        ],
    },

    "royaltiez": {
        "screen": "royaltiez",
        "route": "/royalties",
        "title": "🏦 Royalties — the cashout choice matters most",
        "blurb": (
            "🏦 Royalties accrue in their own bucket, and how fast you pull them decides how "
            "much you keep. ⚖️ This is the one page where patience is literally paid."
        ),
        "highlight": _h('[data-omviardz="royalties-balance"]', "Royalty balance"),
        "input": {"kind": "choice", "allow_text": True},
        "options": [
            {
                "key": "1", "label": "⚡ Instant — I want it now",
                "highlight": _h('[data-omviardz="cashout-instant"]', "Instant cashout"),
                "explain": (
                    "⚡ Fastest and by far the most expensive — the rate is set so speed has a "
                    "real price. 😤 Worth it for an emergency. Brutal as a habit. 💸"
                ),
            },
            {
                "key": "2", "label": "📅 Weekly / monthly",
                "highlight": _h('[data-omviardz="cashout-weekly"]', "Scheduled cashout"),
                "explain": (
                    "📅 Weekly's rate follows your tier, monthly is a flat sliver. 💯 For most "
                    "people monthly is the sweet spot — it's close to free and still lands "
                    "inside the same billing month you earned it."
                ),
            },
            {
                "key": "3", "label": "🧊 Quarterly — max keep",
                "highlight": _h('[data-omviardz="cashout-quarterly"]', "Quarterly cashout"),
                "explain": (
                    "🧊 Zero cut. You keep all of it and wait for it. 🧠 If this money isn't "
                    "rent, this is the correct answer and nobody talks you out of it. 🏆"
                ),
            },
        ],
    },

    "collabz": {
        "screen": "collabz",
        "route": "/collab",
        "title": "🤝 CollabZ — escrow, so nobody gets burned",
        "blurb": (
            "🤝 Fund the deal, the money sits in escrow, it releases when the work lands — or "
            "auto-releases so nobody's stuck waiting on an approval forever. ⚖️"
        ),
        "highlight": _h('[data-omviardz="collab-list"]', "Your deals"),
        "input": {"kind": "choice", "allow_text": True},
        "options": [
            {
                "key": "1", "label": "💵 Fund a deal",
                "highlight": _h('[data-omviardz="collab-fund"]', "Fund"),
                "explain": (
                    "💵 Money leaves your wallet into escrow — visibly held, not sent. That's "
                    "the whole trust mechanic: they can see it's real before they start. 🔥"
                ),
            },
            {
                "key": "2", "label": "📦 Deliver / release",
                "highlight": _h('[data-omviardz="collab-deliver"]', "Deliver"),
                "explain": (
                    "📦 Deliverer marks it delivered, payer releases. If the payer goes quiet, "
                    "auto-release protects the person who did the work. 💪 Nobody's leverage "
                    "is silence."
                ),
            },
            {
                "key": "3", "label": "⚖️ Something went wrong",
                "highlight": _h('[data-omviardz="collab-dispute"]', "Dispute"),
                "explain": (
                    "⚖️ Open a dispute inside the window and auto-release freezes while it's "
                    "reviewed. 💡 Do it early — a dispute filed on day two with the files "
                    "attached is a different conversation than one filed on day nine. 👀"
                ),
            },
        ],
    },

    "sellz": {
        "screen": "merchz",
        "route": "/merch",
        "title": "🛍️ Sell it — MerchZ, LessonZ, locked posts",
        "blurb": (
            "🛍️ Three ways to charge on here, and they suit different people. Which sounds "
            "like you? 💸"
        ),
        "highlight": _h('[data-omviardz="merch-grid"]', "MerchZ"),
        "input": {"kind": "choice", "allow_text": True},
        "options": [
            {
                "key": "1", "label": "👕 MerchZ — list an item",
                "highlight": _h('[data-omviardz="merch-new"]', "New item"),
                "explain": (
                    "👕 List it, price it, members buy from the wallet. 💡 Don't order a box of "
                    "shirts first — list, see if anyone bites, then produce. That mistake has "
                    "eaten more artist money than bad mixes. 😤"
                ),
            },
            {
                "key": "2", "label": "🎓 LessonZ — teach for money",
                "highlight": _h('[data-omviardz="lessonz-offer"]', "Publish an offer"),
                "explain": (
                    "🎓 Get a skill to rating 6 and you can publish lessons — per hour or per "
                    "lesson, remote or in person. Payment flows one way: student to teacher, "
                    "always. ⚖️ Live 1:1 bookings are adult-verified only, no exceptions, and "
                    "that's a child-safety rule not a paperwork one."
                ),
            },
            {
                "key": "3", "label": "🔒 Locked lesson posts",
                "highlight": _h('[data-omviardz="lessonz-post"]', "Post a recorded lesson"),
                "explain": (
                    "🔒 Record once, sell it forever — a post people pay to unlock. 🧠 This is "
                    "the leverage play: your Tuesday night explanation of sidechain compression "
                    "keeps earning while you sleep. 🚀"
                ),
            },
        ],
    },

    "tierz": {
        "screen": "tierz",
        "route": "/membership",
        "title": "🎟️ The tiers — what actually changes",
        "blurb": (
            "🎟️ Free, Premium, StatZ. Higher tiers write longer, upload bigger, pay lower "
            "fees, and get more free prompts. 💯 Which do you want the real numbers on?"
        ),
        "highlight": _h('[data-omviardz="tier-cards"]', "Tier cards"),
        "input": {"kind": "choice", "allow_text": True},
        "options": [
            {
                "key": "1", "label": "🆓 Free — is it usable?",
                "highlight": _h('[data-omviardz="tier-free"]', "Free"),
                "explain": (
                    "🆓 Genuinely, yes — you can post, train, collab, earn and get paid on free. "
                    "You just pay the highest cut and get the tightest limits. 💡 Stay here "
                    "until a limit actually annoys you. Then upgrade for a reason. ✅"
                ),
            },
            {
                "key": "2", "label": "⭐ Premium — the middle",
                "highlight": _h('[data-omviardz="tier-premium"]', "Premium"),
                "explain": (
                    "⭐ Lower fees, bigger uploads, more daily prompts, longer edit window. 🧠 "
                    "The honest test: if what you're paying in fees is close to the monthly, "
                    "it's already worth it. Annual is two months free."
                ),
            },
            {
                "key": "3", "label": "📊 StatZ — the top",
                "highlight": _h('[data-omviardz="tier-statz"]', "StatZ"),
                "explain": (
                    "📊 No character cap, the biggest storage, the lowest cut, and SpecZ — the "
                    "analytics and metadata reports nobody else can buy. 🔥 First 50 members "
                    "get a founding rate at half price, including a one-time lifetime seat. "
                    "That's a real deadline, not a fake urgency banner. 👀"
                ),
            },
        ],
    },

    "safetyz": {
        "screen": "settings",
        "route": "/settings",
        "title": "🛡️ Your data, your call",
        "blurb": (
            "🛡️ Two buttons most apps hide. I'd rather you know they're here on day one than "
            "find out you can't leave. ⚖️"
        ),
        "highlight": _h('[data-omviardz="settings-privacy"]', "Privacy"),
        "input": {"kind": "choice", "allow_text": True},
        "options": [
            {
                "key": "1", "label": "📤 Export my data",
                "highlight": _h('[data-omviardz="account-export"]', "Export"),
                "explain": (
                    "📤 One tap, you get your data. No support ticket, no waiting on me. 💯"
                ),
            },
            {
                "key": "2", "label": "🗑️ Delete my account",
                "highlight": _h('[data-omviardz="account-delete"]', "Delete account"),
                "explain": (
                    "🗑️ Also one tap, also no negotiation. 💪 An app that makes leaving hard is "
                    "telling you something about itself — so this one doesn't."
                ),
            },
            {
                "key": "3", "label": "🗣️ Turn on Corey's slang",
                "highlight": _h('[data-omviardz="settings-slang"]', "Colloquialisms"),
                "explain": (
                    "🗣️ Off by default so anything professional stays clean. Flip it and I talk "
                    "to you the way I actually talk. ✌🏽 Your call, changeable anytime."
                ),
            },
        ],
    },

    "finish": {
        "screen": "home",
        "route": "/",
        "title": "🏆 That's the tour — one move from here",
        "blurb": (
            "🏆 You've got the map. Don't try to use all of it this week — pick the one room "
            "that matches what you came for and go be busy in it. 🚀 Want anything else?"
        ),
        "highlight": _h('[data-omviardz="nav"]', "Your drawer", placement="above"),
        "input": {"kind": "choice", "allow_text": True,
                  "placeholder": "ask me anything before I get out of your way…"},
        "terminal": True,
        "options": [
            {
                "key": "1", "label": "🔁 Run the tour again",
                "goto": "welcome",
                "explain": "🔁 Back to the top — pick a different reason and you'll get a different route. 👀",
            },
            {
                "key": "2", "label": "🧠 Take me to OCC",
                "route": "/occ",
                "highlight": _h('[data-omviardz="occ-composer"]', "Ask OCC", placement="above"),
                "explain": (
                    "🧠 Come ask me the specific thing. That's what I'm actually good for — "
                    "the tour was just so you knew which words to use. 🔥"
                ),
            },
            {
                "key": "3", "label": "✅ I'm good",
                "explain": (
                    "✅ Good looks. I'm in OCC whenever the wall shows up — and it will, that's "
                    "the job. 💪 Go make something. ✌🏽"
                ),
            },
        ],
    },
}


# Which steps each answer to "why are you here" walks through. Same step
# definitions, different route — a fan shouldn't sit through royalty cashout
# rates, and a producer shouldn't have to find DistributeZ on their own.
TRACKS = {
    TRACK_MAKE: ["welcome", "profilez", "personaz", "occ", "postz", "walletz", "tierz",
                 "safetyz", "finish"],
    TRACK_DISCOVER: ["welcome", "profilez", "personaz", "postz", "socialz", "messagez",
                     "tierz", "safetyz", "finish"],
    TRACK_MONEY: ["welcome", "profilez", "walletz", "earnz", "royaltiez", "collabz",
                  "sellz", "tierz", "safetyz", "finish"],
    TRACK_LEARN: ["welcome", "profilez", "skillz", "occ", "sellz", "messagez", "tierz",
                  "safetyz", "finish"],
}


def track_steps(track):
    return TRACKS.get(track, TRACKS[TRACK_DEFAULT])


def first_step():
    return TRACKS[TRACK_DEFAULT][0]


def next_step_key(track, step_key):
    """The step after ``step_key`` on this track, or None at the end."""
    keys = track_steps(track)
    if step_key not in keys:
        return keys[0]
    i = keys.index(step_key)
    return keys[i + 1] if i + 1 < len(keys) else None


def get_step(step_key):
    return STEPS.get(step_key)


def get_option(step_key, choice):
    """Find an option by the character the member replied with.

    Accepts "1", "#1", " #1 " and "🎧 Make something…" (the label), because a
    phone user taps the row while a desktop user types the character, and both
    land in the same field.
    """
    step = STEPS.get(step_key)
    if not step:
        return None
    want = str(choice or "").strip().lstrip("#").strip().lower()
    if not want:
        return None
    for opt in step.get("options", []):
        if want == opt["key"].lower() or want == opt["label"].strip().lower():
            return opt
    return None


def tier_facts():
    """The live numbers behind the tier copy, read from the economy catalog.

    The tour talks about limits in prose ("the tightest limits") and hands the
    client these to render — so the tutorial can't drift out of sync with what
    the server actually enforces. Defensive: OmviardZ still works if the
    economy app isn't installed.
    """
    try:
        from apps.economy.catalog import (
            AI_MODEL_COSTS, CASHOUT_INSTANT, CASHOUT_MONTHLY, CASHOUT_QUARTERLY,
            CASHOUT_WEEKLY, EDIT_WINDOW_SECONDS, FOUNDING_LIMIT, TIER_LIMITS,
            chars_unlimited,
        )
        from apps.economy.models import DEV_TAX, TIER_FREE, TIER_PREMIUM, TIER_STATZ
    except Exception:  # pragma: no cover - economy app absent
        return {}

    tiers = {}
    for tier in (TIER_FREE, TIER_PREMIUM, TIER_STATZ):
        limits = TIER_LIMITS.get(tier, {})
        tiers[tier] = {
            "char_limit": None if chars_unlimited(tier) else limits.get("char_limit"),
            "char_limit_unlimited": chars_unlimited(tier),
            "upload_mb": limits.get("upload_mb"),
            "storage_mb": limits.get("storage_mb"),
            "edit_window_seconds": EDIT_WINDOW_SECONDS.get(tier),
            "dev_tax": DEV_TAX.get(tier),
            "cashout_weekly": CASHOUT_WEEKLY.get(tier),
        }
    return {
        "tiers": tiers,
        "cashout": {
            "instant": CASHOUT_INSTANT,
            "monthly": CASHOUT_MONTHLY,
            "quarterly": CASHOUT_QUARTERLY,
        },
        "ai_cost_cents": dict(AI_MODEL_COSTS),
        "founding_limit": FOUNDING_LIMIT,
    }
