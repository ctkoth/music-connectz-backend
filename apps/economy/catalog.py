"""Static economy config: SpecZ marketplace, per-tier limits, royalty cashout."""
import math

from .models import TIER_FREE, TIER_PREMIUM, TIER_STATZ, TIER_DEBUG

# ---- SpecZ: metadata a member writes and attaches to an app. ----
#
# This was a catalog of six analytics products — "Audience Demographics",
# "Engagement Heatmap", "Genre Intelligence" and so on, priced 499-1299 — and
# the catalog is gone because NOTHING PRODUCED ANY OF THEM. Nothing read
# `specz_purchases` except the endpoint that wrote it, and no code anywhere
# generated a demographics report. Buying one bought a row in a table.
#
# The tab, meanwhile, had built something that does work: pick an app, write a
# label and a value, attach it. That exists after purchase because the member
# typed it. It just never charged for it — `persist()` wrote to localStorage,
# no API call, no balance touched — while MembershipZ sold SpecZ as THE
# StatZ-only perk.
#
# So there were two SpecZ, one that charged for nothing and one that delivered
# for free, and the fix is not to connect them: wiring the tab to that catalog
# would have taken 999 real SpinaZ for a report that does not exist, which is
# the same bug with a working till attached. SpecZ is the thing that delivers,
# and it charges now.
SPECZ_PRICE_SPINAZ = 250          # flat — what the tab already told people

# Where a SpecZ can be attached. Keys are TAB keys, so a stored SpecZ can link
# back to the app it describes (`goToSpot(app_key)`) instead of naming one and
# leaving the member to go and find it.
SPECZ_APPS = [
    {"key": "postz", "name": "PostZ", "icon": "postz.png"},
    {"key": "battlez", "name": "BattleZ", "icon": "battlez.png"},
    {"key": "collabz", "name": "CollabZ", "icon": "collabz.png"},
    {"key": "singz", "name": "SingZ", "icon": "singz.png"},
    {"key": "rapz", "name": "RapZ", "icon": "rapz.png"},
    {"key": "labelz", "name": "LabelZ", "icon": "labelz.png"},
    {"key": "groupz", "name": "GroupZ", "icon": "groupz.png"},
    {"key": "social", "name": "Social ConnectZ", "icon": "social_connectz.png"},
    {"key": "lessonz", "name": "LessonZ", "icon": "lessonz.png"},
    {"key": "messagez", "name": "MessageZ", "icon": "messagez.png"},
]
SPECZ_APP_KEYS = {a["key"] for a in SPECZ_APPS}

# A label and a value are member-authored text, so they answer to a length the
# server states rather than to a column width — the same rule as everywhere
# else. These are short by design: a SpecZ is a fact about how you work, not a
# document, and the tier's char limit belongs to prose.
SPECZ_LABEL_MAX = 60
SPECZ_VALUE_MAX = 200

# A cap high enough that no human writes past it, while staying a plain int —
# so every `len(x) > cap` and `x[:cap]` in the codebase keeps working, and it
# still serializes to JSON. Clients should render `char_limit_unlimited` rather
# than printing this number.
UNLIMITED_CHARS = 10 ** 9

# Per-tier limits. Single-file uploads in MB (Free 100MB / Premium 1GB /
# StatZ 10GB), total vault storage in MB (Free 500MB / Premium 5GB /
# StatZ 100GB), char limits for messages/posts/comments/AI prompts.
#
# Corey's table set the single-file limits and raised every one of them. Two
# cells in it were read against his "nothing lower" instruction rather than
# literally, because taking them literally would have CUT a limit that is
# already live:
#
#   * Free vault read as 500MB, not the 50MB written. His other two rows are
#     both 5x their single-file limit (1GB→5GB, 10GB→50GB) and 5x100MB is
#     500MB; 50MB would also have been the only vault in the table SMALLER
#     than the file allowed into it, so a Free member could never store the
#     100MB file the same row grants them.
#   * StatZ vault held at 100GB rather than the 50GB written, because 100GB is
#     what StatZ members have today and halving it would strand whatever sits
#     above the new line.
#
# Nothing here is ever lowered without a migration plan for the members already
# over the new number — a quota that retroactively shrinks turns somebody's
# stored work into an error message they didn't cause.
TIER_LIMITS = {
    TIER_FREE: {"char_limit": 400, "upload_mb": 100, "storage_mb": 500},
    TIER_PREMIUM: {"char_limit": 1500, "upload_mb": 1024, "storage_mb": 5120},
    # StatZ writes without a character cap — the client already advertised this
    # ("StatZ char limit: Unlimited") while the server was still cutting at
    # 5000, so a StatZ member was told one thing and refused another.
    TIER_STATZ: {"char_limit": UNLIMITED_CHARS, "upload_mb": 10240, "storage_mb": 102400},
    # Owner god-mode: effectively unlimited.
    TIER_DEBUG: {"char_limit": UNLIMITED_CHARS, "upload_mb": 1048576, "storage_mb": 10485760},
}


def limits_for(tier):
    return TIER_LIMITS.get(tier, TIER_LIMITS[TIER_FREE])


# ---- The keyboard's voice: speaking to it, and it speaking back ----
#
# Gated the way translate is gated, and for the same stated reason. The
# wallpaper is Premium because it is DECORATION — nobody loses a capability by
# not having it, which is exactly what makes it fair to sell. Voice is not
# decoration:
#
# * Read-aloud is the second half of translate. Handing a Free member the
#   Portuguese for "where's the studio?" and then charging them to hear how to
#   SAY it is giving away half a capability and selling the other half, which
#   teaches members the free half was bait.
# * Speech input is what you use when typing is the hard part — a motor
#   impairment, a script your phone has no keyboard for, a language easier to
#   speak than to spell. The members who need it most are the least likely to
#   be on the top tier, so an access gate lands hardest on exactly the people
#   it should be helping.
#
# So the tier buys HOW OFTEN, not whether — the same answer BossTake's
# allowance ladder gives, and the same one that keeps translate free.
#
# Clips for listening, characters for reading, because that is the unit each
# action actually comes in: you speak in clips and you read text. One number
# per action, published by GET before either button is pressed.
KEY_TRANSCRIBE_DAILY_CLIPS = {
    TIER_FREE: 10,
    TIER_PREMIUM: 60,
    TIER_STATZ: 300,
    TIER_DEBUG: 10 ** 6,
}

# Only the SERVER voice is metered. The device's own voice costs us nothing,
# works offline and is unlimited at every tier — see keyconnectz.py. This
# allowance exists for the languages a phone has no voice for, which is
# Yorùbá, Igbo, Hausa and Amharic before it is anything else. Gating that
# behind a tier would mean English speakers read aloud free while Yorùbá
# speakers pay, which is the inverse of what this keyboard is for.
KEY_SPEAK_DAILY_CHARS = {
    TIER_FREE: 2_000,
    TIER_PREMIUM: 20_000,
    TIER_STATZ: 100_000,
    TIER_DEBUG: 10 ** 8,
}

# How far back your own ledger goes, by tier.
#
# LogZ used to be a Premium FEATURE — a Free member asking where their SpinaZ
# went got a 403. That is the "it may never say whether" rule broken on the
# worst possible surface: this is not a capability we are renting out, it is
# the member's own record of what the platform did to their balances. Worse,
# `occ_spec.py` had already published SpinaZ and Energy as things a FREE member
# opens IN LOGZ, so the app advertised a door and then locked it.
#
# So the ladder is DEPTH, which is a "how much": thirty days is enough to check
# a referral paid and to find yesterday's charge; a year is what you want when
# you are reconciling a quarter; everything is what an accountant wants. Nobody
# is ever unable to see today.
LOGZ_HISTORY_DAYS = {
    TIER_FREE: 30,
    TIER_PREMIUM: 366,
    TIER_STATZ: None,      # None = all of it
    TIER_DEBUG: None,
}


def logz_history_days(tier):
    """Days of ledger this tier can see. None means everything."""
    return LOGZ_HISTORY_DAYS.get(tier, LOGZ_HISTORY_DAYS[TIER_FREE])


# One clip is one thing said, not a recording session. Sixty seconds is a long
# sentence and a short voice note, and it is what keeps a clip inside a single
# request without anyone re-deriving the transport's limits.
KEY_VOICE_CLIP_MAX_SECONDS = 60
KEY_VOICE_CLIP_MAX_MB = 8


def key_voice_limits(tier):
    """{clips, chars} — this tier's daily voice allowance."""
    return {
        "clips": KEY_TRANSCRIBE_DAILY_CLIPS.get(tier, KEY_TRANSCRIBE_DAILY_CLIPS[TIER_FREE]),
        "chars": KEY_SPEAK_DAILY_CHARS.get(tier, KEY_SPEAK_DAILY_CHARS[TIER_FREE]),
    }


def key_voice_ladder():
    """The whole ladder, for the client to show what a tier up would buy.

    Same shape as BossTake's: what tier buys here is frequency, and a member
    who has spent today's allowance deserves "a tier up gets you sixty" rather
    than a wall with nothing behind it.
    """
    return [{"tier": t,
             "clips": KEY_TRANSCRIBE_DAILY_CLIPS[t],
             "chars": KEY_SPEAK_DAILY_CHARS[t]}
            for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ)]


def chars_unlimited(tier):
    """True when this tier writes without a character cap."""
    return limits_for(tier)["char_limit"] >= UNLIMITED_CHARS


def over_char_limit(text, tier):
    """The cap `text` broke for this tier, or None if it fits.

    Every member-authored text field should run through this rather than
    hardcoding a number — a literal cap silently cuts a Premium member's 1,500
    characters and refuses a StatZ member the unlimited writing they paid for.
    """
    cap = limits_for(tier)["char_limit"]
    return None if len(text or "") <= cap else cap


# How long after posting a message/comment/post/rating you can still edit it, by
# tier: Free 4 min, Premium 40 min, StatZ 4 hours. (Owner/debug: no limit.)
EDIT_WINDOW_SECONDS = {
    TIER_FREE: 4 * 60,
    TIER_PREMIUM: 40 * 60,
    TIER_STATZ: 4 * 3600,
    TIER_DEBUG: 10 ** 9,
}


def edit_window_for(tier):
    return EDIT_WINDOW_SECONDS.get(tier, EDIT_WINDOW_SECONDS[TIER_FREE])


# JournalZ — what one entry can carry, by tier.
#
# Note what is NOT in here: how far back a member can read their own diary, and
# how many entries they may keep. Those were the obvious places to put a wall
# and they are the wrong ones — a journal that hides last year behind a payment
# is holding somebody's own words hostage, and nobody upgrades out of resentment.
# What a tier buys instead is ROOM: more attachments on a day, more people and
# tags on an entry, more entries in one day. The words are always free and
# always readable.
#
# The body length is NOT here either — it runs through `over_char_limit`, like
# every other member-authored field, so a Premium member gets their 1,500 and a
# StatZ member writes without a cap.
JOURNAL_LIMITS = {
    TIER_FREE: {"attachments": 1, "tags": 5, "people": 3, "per_day": 3},
    TIER_PREMIUM: {"attachments": 4, "tags": 20, "people": 10, "per_day": 10},
    TIER_STATZ: {"attachments": 10, "tags": 60, "people": 30, "per_day": 50},
    TIER_DEBUG: {"attachments": 10, "tags": 60, "people": 30, "per_day": 500},
}


def journal_limits_for(tier):
    return JOURNAL_LIMITS.get(tier, JOURNAL_LIMITS[TIER_FREE])


# Royalty cashout tax by plan. Weekly is its own per-tier schedule
# (Free 10% / Premium 5% / StatZ 3%) — matches the StatZ developer-tax rate.
# The others are flat.
CASHOUT_INSTANT = 0.15
CASHOUT_MONTHLY = 0.01
CASHOUT_QUARTERLY = 0.0
CASHOUT_WEEKLY = {TIER_FREE: 0.10, TIER_PREMIUM: 0.05, TIER_STATZ: 0.03, TIER_DEBUG: 0.0}


def cashout_rate(plan, tier):
    if plan == "instant":
        return CASHOUT_INSTANT
    if plan == "weekly":
        return CASHOUT_WEEKLY.get(tier, CASHOUT_WEEKLY[TIER_FREE])
    if plan == "monthly":
        return CASHOUT_MONTHLY
    if plan == "quarterly":
        return CASHOUT_QUARTERLY
    return None


# AI model per-message cost in cents — the *minimum* to cover the model run
# (pass-through, no markup). Corey GPT is priced a touch under the cheapest other
# voice so it's always the value option; it's tuned on member input + the built-in
# curricula so it costs the least to serve.
# Per-message minimum to cover the model (pass-through, no markup). Corey GPT is
# deliberately the cheapest voice.
AI_MODEL_COSTS = {
    "corey-gpt": 1,
    "standard": 3,
    "technical": 3,
}


# ---- Subscription pricing.
#
# Two rules hold the ladder together, and both are load-bearing:
#
#   1. Annual is four months free (33% off) at EVERY tier. One discount to
#      explain, and the bigger commitment never gets the smaller reward.
#   2. StatZ is 2.5x Premium. The gap has to be wide enough that Premium is a
#      real choice — if StatZ costs a couple of dollars more and buys unlimited
#      characters, the whole AI layer, CallZ and SpecZ, nobody sane picks the
#      middle tier and it stops earning its place on the page.
#
# Everything below is derived, not typed twice, so the two rules can't drift.

# Premium — the mid subscription (lower fees, 2x energy, 5 daily prompts).
PREMIUM_MONTH_CENTS = 600                            # $6/mo
PREMIUM_YEAR_CENTS = PREMIUM_MONTH_CENTS * 8         # $48/yr — four months free
PREMIUM_PLANS = {
    "year": {"mode": "subscription", "cents": PREMIUM_YEAR_CENTS, "interval": "year", "kind": "premium_sub"},
    "month": {"mode": "subscription", "cents": PREMIUM_MONTH_CENTS, "interval": "month", "kind": "premium_sub"},
}

# StatZ — the top subscription (no character limit, the AI layer, CallZ, SpecZ).
STATZ_MONTH_CENTS = 1500                             # $15/mo
STATZ_YEAR_CENTS = STATZ_MONTH_CENTS * 8             # $120/yr — four months free
LIFETIME_PRICE_CENTS = 30000                         # $300 one-time, StatZ forever
STATZ_PLANS = {
    "lifetime": {"mode": "payment", "cents": LIFETIME_PRICE_CENTS, "interval": None, "kind": "lifetime"},
    "year": {"mode": "subscription", "cents": STATZ_YEAR_CENTS, "interval": "year", "kind": "statz_sub"},
    "month": {"mode": "subscription", "cents": STATZ_MONTH_CENTS, "interval": "month", "kind": "statz_sub"},
}

# Founding StatZ offer: the first 50 members get StatZ at 50% off — as a
# one-time lifetime seat, or grandfathered founding rates by year / month.
# Derived from the StatZ prices above so the discount is always genuinely half.
FOUNDING_TIER = TIER_STATZ
FOUNDING_LIMIT = 50
FOUNDING_DISCOUNT = 0.50              # first 50 pay half
_half = lambda cents: int(cents * (1 - FOUNDING_DISCOUNT))
FOUNDING_PRICE_CENTS = _half(LIFETIME_PRICE_CENTS)   # $150 lifetime
FOUNDING_YEAR_CENTS = _half(STATZ_YEAR_CENTS)        # $60/yr
FOUNDING_MONTH_CENTS = _half(STATZ_MONTH_CENTS)      # $7.50/mo
# Plan -> (Stripe mode, unit amount cents, recurring interval or None)
FOUNDING_PLANS = {
    "lifetime": {"mode": "payment", "cents": FOUNDING_PRICE_CENTS, "interval": None, "kind": "lifetime"},
    "year": {"mode": "subscription", "cents": FOUNDING_YEAR_CENTS, "interval": "year", "kind": "founding_sub"},
    "month": {"mode": "subscription", "cents": FOUNDING_MONTH_CENTS, "interval": "month", "kind": "founding_sub"},
}

# The founding discount must never price the top tier below the middle one.
# At Premium $10/mo this assertion fails: founding StatZ is $7.50, so the first
# 50 members would pay less for more. It is here so that can't ship unnoticed.
assert FOUNDING_MONTH_CENTS > PREMIUM_MONTH_CENTS, (
    f"Founding StatZ (${FOUNDING_MONTH_CENTS / 100:.2f}/mo) must cost more than "
    f"Premium (${PREMIUM_MONTH_CENTS / 100:.2f}/mo) — the ladder is inverted.")


def ai_cost(model):
    return AI_MODEL_COSTS.get(model, AI_MODEL_COSTS["corey-gpt"])


# ---- Which engine runs the AI, who may pick it, and what it costs.
#
# The bill for every model run in this app lands on ONE Anthropic account — the
# platform's. A member spending their PromptZ is reimbursing that account, so a
# per-message price below the real cost is the platform paying people to use it.
#
# Two things were tangled together before this and are now separate:
#
#   * VOICE is tone. Corey / standard / technical are system prompts. Tone is
#     free — a Free member gets the founder's voice, same as anyone.
#   * MODEL is the engine. It has a real per-token price, so it is what gets
#     charged for and what tier gates.
#
# Keeping them tangled is how Corey GPT — the cheapest voice at 1c — ended up
# running on Fable 5, the most expensive model in the catalogue. The app was
# losing money fastest on the option it advertised as the value pick.
#
# `cost_cents` is the per-message minimum for a TYPICAL OCC turn: about 10,000
# input tokens (voice prompt + courses + eight turns of history) and about 800
# output. Published per-million rates, rounded up, because history grows:
#
#     Haiku 4.5   $1/$5    ->  1.0c + 0.4c  =  1.4c  ->  2c
#     Sonnet 5    $3/$15   ->  3.0c + 1.2c  =  4.2c  ->  5c
#     Opus 5      $5/$25   ->  5.0c + 2.0c  =  7.0c  ->  8c
#     Fable 5     $10/$50  -> 10.0c + 4.0c  = 14.0c  -> 15c
#
# These are minimums to cover a run, not a margin. If the model prices move,
# this table moves — it is the only place they are written down.
# `cost_cents` is the flat price of one CHAT message — a single call, where a
# fixed price is close enough and simple to state.
#
# `in_cents_mtok` / `out_cents_mtok` are the real API rates, in cents per
# million tokens, and they are what an AGENT RUN is billed on. A run is 20-80
# calls with a project in context; a flat per-message price there is a promise
# the data doesn't support, which is the exact failure this codebase keeps
# having to fix. See `ai_run_cost_cents`.
AI_MODELS = {
    "haiku": {
        "id": "claude-haiku-4-5", "name": "Haiku", "emoji": "⚡",
        "tier": TIER_FREE, "cost_cents": 2,
        "in_cents_mtok": 100, "out_cents_mtok": 500,       # $1 / $5
        # Haiku 4.5 predates both controls and returns 400 for either. Declared
        # per model rather than assumed, because "every model takes effort" is
        # true of the three below and false of the one the FREE tier uses — so
        # assuming it would break the agent for exactly the members least able
        # to work around it.
        "effort": False, "task_budget": False,
        "blurb": "Fast and cheap. Plenty for chat, translation and quick answers.",
    },
    "sonnet": {
        "id": "claude-sonnet-5", "name": "Sonnet", "emoji": "🎼",
        "tier": TIER_PREMIUM, "cost_cents": 5,
        # List price, not the introductory rate. The intro expires and a price
        # built on it would quietly start losing money on the day it does.
        "in_cents_mtok": 300, "out_cents_mtok": 1500,      # $3 / $15
        "effort": True, "task_budget": True,
        "blurb": "The balanced one. Near-flagship work at a fraction of the price.",
    },
    "opus": {
        "id": "claude-opus-5", "name": "Opus", "emoji": "🎹",
        "tier": TIER_PREMIUM, "cost_cents": 8,
        "in_cents_mtok": 500, "out_cents_mtok": 2500,      # $5 / $25
        "effort": True, "task_budget": True,
        "blurb": "Flagship. Long-horizon work, code, and anything that has to be right.",
    },
    "fable": {
        "id": "claude-fable-5", "name": "Fable", "emoji": "📖",
        "tier": TIER_STATZ, "cost_cents": 15,
        "in_cents_mtok": 1000, "out_cents_mtok": 5000,     # $10 / $50
        "effort": True, "task_budget": True,
        "blurb": "The most capable model there is. The hardest problems, at the highest price.",
    },
}

# What the API charges for cached input, as a multiple of the normal input rate.
# Worth modelling rather than ignoring: an agent re-sends the whole project on
# every turn, so most of a run's input is a cache READ at a tenth of the price.
# Billing those at full rate would overcharge a long run by roughly ten times.
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25

# Cheapest first — the order the picker renders, and the order a fallback walks.
AI_MODEL_ORDER = ("haiku", "sonnet", "opus", "fable")

# PromptZ are sold at a bonus: `pay_cents * PROMPTZ_BONUS` credits. It lived as a
# bare 1.25 inside PromptzBuyView, which is how its effect on agent pricing went
# unnoticed — a pricing relationship nobody could see from the code that priced
# against it. Named here so the two can be reasoned about together.
PROMPTZ_BONUS = 1.25

# What one PromptZ actually cost the member, in cents. The number that makes
# pass-through pricing a loss: sell at 0.8c, owe Anthropic 1c.
PROMPTZ_CENTS_PER_UNIT = 1 / PROMPTZ_BONUS

# SpinaZ buy PromptZ, at ten to one.
#
# Before this, PromptZ could be bought with CASH and nothing else — so every
# free way to earn on this platform (rating, referring, AdZ, OfferZ, finishing
# OnboardZ) paid out in a currency that could not reach the thing members
# actually come here for. A member could rate two hundred takes, hold 🍥 they
# had genuinely worked for, and still be told the coach costs money. That is a
# dead end, and this codebase's own rule is that nothing is a dead end.
#
# Ten to one, not one to one, and the ratio is the whole design: AdZ pegs 🍥 to
# cents, so parity would make watching an ad strictly better than paying and
# nobody would ever pay. At 10:1 the grind is real but slow — 150 🍥 from
# OnboardZ is 15 🏷️, about seven Haiku runs, a genuine welcome and not a
# living. Cash stays the fast lane and the subscription stays the shortcut.
# What changes is that a member without either is no longer stuck.
SPINAZ_PER_PROMPTZ = 10

# What an agent run is CHARGED, as a multiple of what it COST to serve.
#
# This exists because pass-through pricing loses money here, and it took the
# arithmetic to see it. PromptZ are sold at a 25% bonus — `PromptzBuyView` grants
# `pay_cents * 1.25`, so 80c buys 100 PromptZ. Charge a run its raw cost and the
# platform collects 80c for every 100c it owes Anthropic: a 20% loss that grows
# with usage, which is precisely backwards.
#
# So 1.25 is BREAK-EVEN, not margin — it recovers the bonus and funds nothing.
# 1.6 collects 128c per 100c of cost (1.6 x 0.8), a ~28% net margin, which is
# what pays for the platform's own runs rather than merely surviving members'.
#
# The rest of the AI surface — chat, translation, the small per-message actions —
# keeps the plain bonus and stays pass-through. This multiplier applies to agent
# runs only, because agent runs are the only place where one action can cost
# real money.
AGENT_PRICE_MULTIPLIER = 1.6

# The most a single agent run may CHARGE, by tier, in PromptZ (1 PromptZ = 1c).
#
# This is a CEILING the member is told before they press anything — not an
# estimate. An estimate of a thing nobody can predict (how many turns a task
# takes) is a guess wearing a number's clothes; a ceiling is a promise. The run
# stops when it reaches this, and the member is charged what it actually used,
# which is nearly always less.
#
# Charged, not cost: this is the number on the button, so it has to be the number
# that leaves the member's wallet.
AI_RUN_BUDGET_CENTS = {
    TIER_FREE: 25,          # a small fix, or a look around a project
    TIER_PREMIUM: 200,
    TIER_STATZ: 1_000,
    TIER_DEBUG: 100_000,
}

def ai_run_cost_cents(model_key, usage):
    """What one agent run actually cost, in whole cents, rounded up.

    `usage` is the accumulated token counts for the WHOLE run — every call in
    the loop added together — not one message. Rounding once at the end matters:
    rounding each of forty turns up to a cent would bill 40c for a run that
    genuinely cost 8.

    Accepts either an Anthropic usage object or a plain dict, because the tests
    use dicts and the loop passes the real thing.
    """
    spec = AI_MODELS.get(model_key) or AI_MODELS[AI_MODEL_ORDER[0]]

    def field(name):
        value = (usage.get(name) if isinstance(usage, dict)
                 else getattr(usage, name, 0))
        return int(value or 0)

    fresh_in = field("input_tokens")
    cache_read = field("cache_read_input_tokens")
    cache_write = field("cache_creation_input_tokens")
    out = field("output_tokens")

    micros = (
        fresh_in * spec["in_cents_mtok"]
        + cache_read * spec["in_cents_mtok"] * CACHE_READ_MULTIPLIER
        + cache_write * spec["in_cents_mtok"] * CACHE_WRITE_MULTIPLIER
        + out * spec["out_cents_mtok"]
    )
    cents = micros / 1_000_000
    if cents <= 0:
        return 0
    # Round UP, so a run that cost a fraction of a cent still costs something —
    # a free tier of tiny runs is a hole somebody eventually drives a loop
    # through. One cent is the smallest honest charge.
    return max(1, math.ceil(cents))


def ai_run_charge_cents(model_key, usage):
    """What the member PAYS for a run, in whole cents — cost plus margin.

    Deliberately a second function rather than a parameter on the first. Cost is
    a fact about what Anthropic billed; charge is a decision about what to sell
    it for. Collapsing the two into one number is exactly how a 25% PromptZ bonus
    quietly turned every agent run into a 20% loss — nothing in the code
    distinguished the money owed from the money taken, so nothing could disagree.

    Never less than the cost. A run cheap enough to round to nothing still can't
    charge below what it cost to serve.
    """
    cost = ai_run_cost_cents(model_key, usage)
    if cost <= 0:
        return 0
    return max(cost, math.ceil(cost * AGENT_PRICE_MULTIPLIER))


def ai_run_budget(tier):
    """The charge ceiling for this tier's agent runs."""
    return {"max_cents": AI_RUN_BUDGET_CENTS.get(tier, AI_RUN_BUDGET_CENTS[TIER_FREE])}


# Which tiers can reach which rung. A tier gets its own rung and every rung
# below it, so upgrading only ever adds.
_TIER_RANK = {TIER_FREE: 0, TIER_PREMIUM: 1, TIER_STATZ: 2, TIER_DEBUG: 3}


def ai_models_for(tier):
    """The model keys this tier may pick, cheapest first."""
    rank = _TIER_RANK.get(tier, 0)
    return [k for k in AI_MODEL_ORDER
            if _TIER_RANK.get(AI_MODELS[k]["tier"], 0) <= rank]


def default_ai_model(tier):
    """What a member gets before they choose: the best rung their tier owns.

    The top rung rather than the bottom because the tier was paid for. A StatZ
    member who never opens the picker should not be quietly served Haiku.
    """
    allowed = ai_models_for(tier)
    return allowed[-1] if allowed else "haiku"


def ai_model_for(key, tier):
    """Resolve a member's stored choice against what their tier can reach.

    Returns (key, spec). A choice above the member's tier falls back rather than
    refusing — a lapsed StatZ member's saved 'fable' becomes their best current
    rung instead of an error on a screen they didn't come to fix.
    """
    allowed = ai_models_for(tier)
    if key not in allowed:
        key = default_ai_model(tier)
    return key, AI_MODELS[key]


def ai_model_cost(key, tier):
    """What one message on this member's model costs them, in cents."""
    return ai_model_for(key, tier)[1]["cost_cents"]


# ---- How big one AI message is allowed to be.
#
# These are the other half of the prices above, and without them those prices
# are fiction. `cost_cents` is worked out for a turn of roughly 10,000 input
# tokens; nothing enforced that, so every field the client sends — the prompt,
# the taught knowledge, the CodeZ acronyms, the conversation history — went into
# the model unbounded while the charge stayed flat.
#
# The ceiling that existed was Django's default 2.5MB request body. At Fable's
# $10 per million input tokens that is about $6 of tokens for a 15c charge, on
# the platform's own Anthropic account, repeatable by anyone with a login.
#
# So: a cap per field for sanity, and a TOTAL budget that holds the price
# honest. ~4 characters to a token, so 40,000 characters is the ~10,000 the
# prices were built on.
OCC_MAX_PROMPT_CHARS = 8_000        # one message from the member
OCC_MAX_KNOWLEDGE_ITEMS = 20        # things they've taught OCC
OCC_MAX_KNOWLEDGE_CHARS = 2_000     # per taught item
OCC_MAX_ACRONYMS = 60               # CodeZ shorthand entries
OCC_MAX_ACRONYM_CHARS = 120         # per entry
OCC_MAX_HISTORY_TURNS = 8           # turns of conversation carried back
OCC_MAX_HISTORY_CHARS = 4_000       # per turn
OCC_MAX_TOTAL_CHARS = 40_000        # the whole assembled prompt
# The vision image, as base64 inside a data URL. Missed on the first pass of
# this cap and found while writing the tests for it — same hole, different
# field. ~1.5MB of base64 is a ~1.1MB image, more than enough for a photo of a
# pedalboard or a screenshot.
OCC_MAX_IMAGE_B64 = 1_500_000
# What the model will actually accept. The media type used to be whatever the
# client wrote in its own data URL header and it went straight through to the
# API — the same passthrough that made the coach refuse every Chrome recording.
OCC_IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")

# ---- FileZ: what OCC may keep between turns ----
#
# The editor held one string in React state, so nothing OCC wrote survived the
# reply that wrote it. These are the caps on the store that replaces it.
#
# A path cap and a per-file cap stop one runaway write; the per-project counts
# stop a thousand small ones, which is the same lesson the prompt budget above
# had to learn twice. Files are member-authored text, so the CONTENT cap is the
# only one that scales with tier — a Free member gets fewer files, not shorter
# lines, because a 400-character source file is not a source file.
OCC_MAX_PATH_CHARS = 200            # "src/apps/BossTake.jsx" and then some
OCC_MAX_FILE_CHARS = 200_000        # one file; matches modal_sandbox.MAX_SOURCE_CHARS
OCC_MAX_PROJECT_NAME_CHARS = 80
OCC_PROJECT_FILES = {               # files per project, by tier
    TIER_FREE: 40,
    TIER_PREMIUM: 400,
    TIER_STATZ: 4_000,
    TIER_DEBUG: 40_000,
}
OCC_PROJECTS = {                    # projects per member, by tier
    TIER_FREE: 3,
    TIER_PREMIUM: 20,
    TIER_STATZ: 200,
    TIER_DEBUG: 2_000,
}


def occ_file_limits(tier):
    """The FileZ ceilings for a tier, published so the client states them first.

    Returned per-tier rather than as one table because the member only needs
    their own numbers, and a screen that renders every tier's limits next to a
    Save button is telling them about a purchase, not about their file.
    """
    return {
        "path_chars": OCC_MAX_PATH_CHARS,
        "file_chars": OCC_MAX_FILE_CHARS,
        "project_name_chars": OCC_MAX_PROJECT_NAME_CHARS,
        "files_per_project": OCC_PROJECT_FILES.get(tier, OCC_PROJECT_FILES[TIER_FREE]),
        "projects": OCC_PROJECTS.get(tier, OCC_PROJECTS[TIER_FREE]),
    }


def occ_limits():
    """Published so the composer can stop a member BEFORE they lose the typing.

    A cap discovered by hitting it is the same mistake as a price discovered by
    paying it.
    """
    return {
        "prompt_chars": OCC_MAX_PROMPT_CHARS,
        "knowledge_items": OCC_MAX_KNOWLEDGE_ITEMS,
        "knowledge_chars": OCC_MAX_KNOWLEDGE_CHARS,
        "acronyms": OCC_MAX_ACRONYMS,
        "acronym_chars": OCC_MAX_ACRONYM_CHARS,
        "history_turns": OCC_MAX_HISTORY_TURNS,
        "history_chars": OCC_MAX_HISTORY_CHARS,
        "total_chars": OCC_MAX_TOTAL_CHARS,
        "image_b64": OCC_MAX_IMAGE_B64,
        "image_types": list(OCC_IMAGE_TYPES),
    }
