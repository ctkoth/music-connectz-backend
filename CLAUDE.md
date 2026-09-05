# Music ConnectZ — working notes

## The cost/gain paradigm (Corey's rule — applies everywhere)

**Every action that moves a resource states its cost and its gain UP FRONT,
before the member commits to it.** Never after, never only in the response.

Format: a red minus for what leaves, a green plus for what arrives, each with
its resource emoji.

```
−1 🏷️   +8 ⚡
```

- **Red / minus** — what it costs you
- **Green / plus** — what you get
- Always the **resource emoji**, never a bare number
- **Up front.** A price discovered by paying it is not a price, it's a bill.

### Resource emoji — use these, they are already established in the codebase

| Resource | Emoji | Where |
|---|---|---|
| Energy | ⚡ | mana; refills hourly at reach ÷ tier, toward a daily ceiling |
| SpinaZ | 🍥 | coin; earned by rating, referring, AdZ/OfferZ |
| PromptZ | 🏷️ | prepaid AI credits; daily free allowance is separate |
| Money | 💵 | real cash balance, in cents server-side |
| XP | ⭐ | SkillZ progression |

### What this means in practice

- A button that spends something says so **on the button or immediately beside
  it**, not in the result.
- Free actions that *earn* still show the gain — `+1 ⚡` on a rating is the
  reason people rate.
- If an action can fail, say whether a failed attempt is charged. (It usually
  should not be — see `vocalcoach.py`, which bills only after a usable result
  parses.)
- Both sides of a two-sided reward get stated: a referral is `+300 🍥` for the
  referrer and `+100 🍥` for the joinee, and both numbers belong on screen.

### Known violations, not yet fixed

- *(none open on this list.)* CallZ was here for the whole life of this file —
  no live 1:1 surface existed, LessonZ's "CallZ" was a delivery method on a
  booking priced the same as remote or in-person, so there was no per-minute
  rate to state because there was no call. It ships now: `apps/economy/callz.py`
  publishes the callee's rate, the caller's balance and the minutes they can
  afford BEFORE anything rings, the running cost is on screen during the call,
  and the receipt matches the quote. The rate is snapshot at ring so it cannot
  move under a call in progress.

Previously listed here and since fixed, client-side — BossTake's "Send it to
the coach", OCC chat, DirectZ craft, and KeyConnectZ translate all render the
price beside the control that spends it now, before it's pressed. Don't read
this list as exhaustive: a surface not named here was never audited, not
cleared.

---

## Substance before the game layer (Corey's third rule)

**Every skill, score and rating must measure the real thing.** The game layer —
XP, badges, ⭐, medians, leaderboards — is a way of SHOWING reality, never a
substitute for measuring it. Gamified reality, not gamified nothing.

The test for any number this app displays: **could a member get a good one
without getting good?** If yes, it is decoration wearing a measurement's
clothes, and it will be found out by the first person who tries.

Two things in this codebase, doing the opposite of each other:

- **`vocalcoach.py` — substance.** The take is sent to a model that actually
  listens, and comes back scored on pitch, timing and tone. The number moves
  because the singing moved. The dimensions come from the instrument's own
  profile, so a drummer isn't scored on breath.
- **`models.directz_ai_rating` — the failure.** It calls itself "a deterministic
  AI craft estimate" and measures contributor count, how many skills were
  listed, description length, sum of skill prices, and whether the duration fits
  the band. **None of that is craft.** A bad video with five contributors and a
  long description scores ~8; a brilliant one-person video with a terse
  description scores ~4. `directz_display_rating` then shows it as the rating
  until three real members rate it.

So the rule, in practice:

- A score derived from **form completeness** is not a score. Count of fields
  filled, length of text, number of collaborators, money spent — none of these
  are quality, and a rating built on them teaches members to pad.
- If the real thing genuinely cannot be measured yet, **say what the number is**
  rather than dressing it up. "Seeded from how staffed this work is" is honest;
  "AI craft estimate" is not.
- Prefer no number to a fake one. An empty rating invites a real one; a fake one
  ends the question.
- **XP and badges may reward effort. Ratings and skill levels may not.** Turning
  up is worth something; it is not worth being called good.

### Known violation — closed

- **`directz_ai_rating` is deleted.** This entry outlived the fix by some weeks,
  which is worth noticing on its own: a "not yet fixed" list nobody re-checks
  sends the next reader to fix something twice.

  What actually happened: `directz_craft.py` replaced it with a model that
  WATCHES the video and scores framing, editing, lighting, sound and story —
  none of which can be satisfied by filling in a form. Migration 0073 nulled
  every score the old formula had already written, because fixing the code that
  makes a number and leaving the number on screen fixes the future and keeps
  the past. And `directz_display_rating` has three states rather than two:
  users / ai / **nothing**, and when it is nothing the rating is None and
  callers render the absence.

  The function then sat deprecated, kept by a docstring saying old rows still
  carried its numbers — untrue from the moment 0073 ran. It is gone now, and
  `test_directz_craft` pins both its absence and that nothing calls it, because
  a discredited scoring function within reach of an import is one somebody will
  reach for.

---

## Cross-pollination (Corey's crux — applies to everything)

**Nothing is a dead end.** Something created, recorded or noticed in one app
opens in another to edit or analyse. A member should never hit a screen that
shows them a fact and gives them nowhere to take it.

In practice, anything that stores a thing also stores WHERE it came from:

```python
Observation(kind=..., key=..., app_key="singz", target="singz:coach")
```

and every row it serves carries `open_in` so the client can offer the jump.
`goto.js` (`goToSpot(tab, target)`) already lands on the exact control, so the
handoff is one call — not a tab switch that dumps you at the top of an app.

Existing examples to follow:

- OnboardZ steps link to the control that completes them, not just the tab.
- A Boss Take is scored in SingZ and its dimensions come from that app's
  profile, so the same recorder serves RapZ without inventing scores.
- LogZ rows carry the reason a resource moved, so a balance leads back to
  the action that changed it.
- A post carries `destinations` — every app that can do something with it, what
  each still needs, and what it costs before it is spent. `apps/economy/crosspost.py`
  is the one list; SingZ and RapZ take the post itself as a Boss Take, so a
  finished track can be coached without being uploaded a second time.

When adding a screen, ask what a member would want to DO with each row, and
give them the link. A read-only surface is usually an unfinished one.


---

## Deployment

**Both repos auto-deploy from `main`. Merging to `main` IS the deploy.**

- Backend is on Render with **auto-deploy ON**. A push to `main` builds and
  ships by itself — no Manual Deploy to press, and none to forget.
- **`build.sh` runs `migrate --no-input` on every deploy**, so a merge to
  `main` migrates production unattended. `render.yaml`'s `startCommand` runs
  gunicorn directly and never touches `start.sh`, which is why the build is the
  only reliable place to migrate. Nothing else runs it.
- **So develop on a branch, always.** The deliberate act is the merge, not a
  button afterwards. Anything sitting on `main` is either live or about to be.
- Frontend deploys itself too (Vercel / Cloudflare Pages), which means a
  frontend change can go live before the backend it depends on. When the UI
  needs a new endpoint, **merge the backend first** — the API may exist before
  anything calls it, but never the reverse.
- A failed build never replaces the running process, so a broken deploy leaves
  the previous version serving. There is nothing to roll back by hand.
- The tests run on SQLite and production is Postgres (see Testing below). With
  migrations now applying unattended, that gap is the one to respect: a
  migration touching field widths gets checked against real Postgres BEFORE it
  reaches `main`, not after.

## KeyConnectZ voice: the tier buys how many, never whether

`keyconnectz.py` had already written the rule down: the wallpaper is Premium
because it is **decoration** and nobody loses a capability without it; translate
is free at every tier because **being understood is not a luxury.** Transcribe
and read-aloud are on the capability side of that line, twice over —

- Read-aloud is the second half of translate. Hand a Free member the Portuguese
  and charge them to hear how to *say* it and you have sold half a capability.
- Speech input is how you type when typing is the hard part. An access gate
  lands hardest on exactly the members it should be helping.

— so both are available at every tier and the **allowance** is what ladders:
`catalog.KEY_TRANSCRIBE_DAILY_CLIPS` (clips) and `KEY_SPEAK_DAILY_CHARS`
(characters). Clips for listening and characters for reading, because that is
the unit each action comes in; one unit covering both would be a number nobody
could check. `GET /api/economy/keyz/` publishes both, plus the ladder, before
either button is pressed.

**The device voice never reaches the server and is never metered.** The client
tries `speechSynthesis` first — it costs us nothing, so metering it would be
counting something we do not pay for in order to charge for it. `keyz/speak/`
exists for the languages a handset has no voice for, which is Yorùbá, Igbo,
Hausa and Amharic before it is anything else. That is the reason it is not sold
by tier: a gate there would mean English speakers hear their translation read
back free while Yorùbá speakers pay for the same sentence.

Two things that must not rot:

- **A failed run never spends the allowance.** An empty transcript or an empty
  voice returns 502 and writes no `KeyVoiceUse`, exactly as a failed Boss Take
  is not billed and a failed translation is not metered.
- **TTS needs its own model chain.** `responseModalities: ["AUDIO"]` against
  `gemini-2.5-flash` is a 400, not a fallback, so `MODEL_CHAINS["tts"]` is
  separate. Gemini answers with raw PCM (`audio/L16;codec=pcm;rate=24000`) and
  no browser will play that — the RIFF header goes on in `_wav()`, server-side,
  rather than in three clients that would each get it slightly wrong.

Like the coach's upload path, **the TTS transport has never run against
Google** — CI has no key. `tools/keyvoice_live_check.sh` is the check that can.

## Uploads have to outlive a deploy, and there are two ways to make them

Render's web filesystem is part of the container, and the container is rebuilt
every time anything merges to `main`. With no bucket and no disk, `MEDIA_ROOT`
is a directory inside it — so **every track, video, cover and avatar any member
has uploaded is deleted by the next deploy.** The `Upload` rows are in Postgres
and survive, so the app carries on serving links to files that are not there:
the feed renders a player that 404s, and SingZ tells somebody their own take
"isn't on the server any more".

`storage_health.py` says so in the deploy log (`economy.W001`), in the running
service's log at startup, and in `GET /`. **A warning is not a fix.** Neither
option is a code change; both are wired, and **the disk is the one in force**:

- **A persistent disk — current.** `render.yaml` mounts `mcz-media` at
  `/var/mcz-media`, and `MEDIA_ROOT` + `MEDIA_DURABLE=1` sit beside it in the
  same file so the claim and the thing it claims cannot drift apart. No
  credentials and no external service. It pins the service to one instance,
  wants a paid instance type, and costs a few seconds of downtime per deploy
  instead of zero — that is the whole price.
- **A bucket** — `S3_BUCKET_NAME` + `S3_ACCESS_KEY_ID` + `S3_SECRET_ACCESS_KEY`
  (add `S3_ENDPOINT_URL` for R2). Scales, no instance pinning, needs an
  account. Setting these takes precedence over the disk, which can then go.

`MEDIA_DURABLE` is an assertion, not a measurement. A mounted disk is
indistinguishable from the container's own directory from inside the process,
so nothing but that variable will be taken as proof — anything short of it
(unset, empty, `0`) leaves the warning standing, because the cost of a false
"durable" is somebody's only copy of a take.

## A lost file gets written down, once, by whatever found it

The disk is mounted, so nothing new is lost. What was already lost is still
lost, and the app used to rediscover each one from scratch: the coach reached
for a take, got nothing, answered 410 — and forgot. The feed went on offering
a player and a "Coach it in SingZ" door for a file established as gone one
request earlier, and the next member to press it paid the same trip to learn
the same thing.

`Upload.missing_since` is where that goes now. Three rules about it:

- **Only something that WENT AND LOOKED may stamp it.** The coach's 410 path,
  and `manage.py reconcile_uploads`. A read path must never guess — "we could
  not play it" is not "it is not there", which is the exact mistake the Boss
  Take card made with an `<audio>` element.
- **Null means "no reason to think so", not "checked and present."** Nothing
  walks storage to serve a feed; 100 posts must not become 100 stat calls, or
  100 HEAD requests once uploads are in a bucket.
- **The row survives; only the bytes are gone.** It is the record of what was
  lost and the thing that lets a post name it. `storage_used_bytes` stops
  counting it, because charging somebody quota for a recording the platform
  lost is billing them for our own failure.

`crosspost.take_state_for` reads the size and the state off the same row in
**one** query for the whole feed (the query-count test holds that), so the post
carries `take_missing`/`take_kind`, PostZ replaces that player with the truth
and a way to re-attach, and every door that hands over a recording — the coach,
BattleZ — closes on the row instead of one jump away.

`manage.py reconcile_uploads [--write]` is the deliberate sweep, and the only
thing in the codebase that walks storage. It **clears** the mark for files that
came back, and a storage backend that cannot answer is never treated as a file
that is gone — marking on an unreachable bucket would tell every member on the
platform their music was lost, which is worse than the bug it exists for.

## Nothing stores a storage URL — `/api/economy/media/<id>/<name>` does

The app **writes the URL it hands out into the database**: `uploadWork.js`
uploads a blob, takes the `url` that comes back and puts it in `Post.media_url`,
the post's `items`, a collab deal, a battle entry. It stays there for the life
of the post.

Harmless while uploads sit on a local disk. It stops being harmless at exactly
the moment somebody fixes the paragraph above — a bucket hands out **signed**
URLs (`S3_QUERYSTRING_AUTH` defaults on, `S3_URL_EXPIRE` an hour), and freezing
one into a post means the track goes silent sixty minutes after it is posted.
Worse: every one of those columns is `max_length=500` and every writer
truncates to it, and a signed URL is routinely longer than that — so the stored
link would have been cut in half on the way in and been wrong from the first
second. **The fix for losing everyone's music would have shipped as a new way
to lose it.**

So `_upload_dict` hands out `/api/economy/media/<id>/<filename>` and that is
what gets stored. It resolves the address freshly on every request: a new
signature each time on a bucket, the plain media path on disk. Two things about
its shape are load-bearing and neither is decoration:

- **The filename is last, and there is no trailing slash.**
  `upload_behind()` and `take_bytes_for()` find the `Upload` behind a post by
  the *tail* of its URL, because `MEDIA_URL` differs between disk, Render and a
  CDN and a whole-URL comparison matches in exactly one environment. Ending the
  route with the stored basename keeps every one of those lookups working; a
  trailing slash makes `rsplit("/", 1)[-1]` the empty string and they all miss,
  silently, with the coach no longer finding the take on a post.
- **It is unauthenticated, like the `/media/` route it replaces.** `<audio src>`
  sends no `Authorization` header, so auth here would break the thing it exists
  for. The id and the filename must agree, which is what stops the id range
  being walked for a list of everybody's filenames.

## Testing

- The suite runs on SQLite by default, but production is PostgreSQL, and
  **SQLite ignores varchar length**. A column-width bug is invisible locally.
  For anything touching field widths, run against a real Postgres:
  `DATABASE_URL=postgres://... python manage.py test`
- Member-authored text answers to the **tier's character limit**, never to a
  column width. Use `catalog.over_char_limit(text, tier)`.

## The coach's ceiling is a judgement now, not a transport limit

`vocalcoach.MAX_MB` was 14 because the take was base64'd into the
`generateContent` body and that request caps at 20MB. It is **200MB** now, and
the reason matters: big takes are uploaded to Google's Files API first
(`gemini_files.py`) and read by URI, which takes 2GB a file, free. So the
number is no longer "what fits in a request" — it is a judgement about what one
take IS, and it can move (`COACH_MAX_MB`) without anyone re-deriving base64
overhead.

- `INLINE_MAX_MB = 14` still governs the inline path and still has to stay
  under the 20MB request cap. `test_vocalcoach` pins that separately now.
- Small takes still go inline on purpose: one round trip, nothing to clean up.
- The switch is built so a Files API failure can never be worse than the old
  behaviour — that is the property that made it shippable without being able to
  reach the live API from CI.
- **The ceiling is per-member now.** `vocalcoach.cap_for(user)` returns the
  smaller of MAX_MB and the member's own `upload_mb`, plus whose limit that is.
  While the coach's cap was 14 it was under every tier and the app could say
  "this isn't your tier's limit" and always be right — which is why
  `max_mb_is_tier_limit` was a hardcoded False. At 200MB a Free member (100MB)
  is bound by their tier, so the flag is computed and the copy follows it.
  Read the cap ONCE per request and pass it down (`coach_cap`), like the price:
  it reads the membership row, and the feed's query-count test catches a
  per-card read.

## The coach's live path has one check, and it isn't a test

`gemini_files.py` (the Files API upload) and `gemini.MODEL_CHAINS` (the model
fallback) both shipped **without ever running against Google.** CI has no key
and neither does a dev box, so every test of them stubs `requests` — which pins
the protocol we BELIEVE in and cannot tell us we believed the wrong thing.

`tools/coach_live_check.sh` is the check that can. It walks the real upload,
the ACTIVE poll, a `file_data` generateContent and the delete, in the same
order and with the same headers as the code, and it generates its own ~29MB
take so nothing has to be found first:

    GEMINI_API_KEY=... ./tools/coach_live_check.sh

Run it after touching the upload path or the chain, and after a key rotation.
It costs one generateContent call. A stubbed suite going green is not evidence
the transport works; this is.

## A limit that stops a member doing anything is not a limit, it's a door out

`catalog.py` and `models.py` hold about a dozen ladders, and the audit that
produced this section found three of them answering "nothing" to somebody on
the day they arrived. The rule they broke is the one to check every new limit
against:

**A tier limit says how MUCH, how OFTEN or how FAST. It may never say whether.**
A member who cannot do a thing at all does not upgrade — they leave, and they
leave believing the app is broken rather than that it is paid.

The three, and what each looked like from the inside:

- **`PROMPT_ALLOWANCE["free"]` was 1** — one AI run a day across the coach, OCC,
  DirectZ and every Gemini surface combined. The ANONYMOUS trial door hands a
  stranger the same one (`TRIAL_PER_IP_HOURS`), so registering bought literally
  nothing on the axis people arrive for. It is 3.
- **Passive Energy was `reach_median // divisor` with no floor**, and
  `reach_median` is 0 until an external account is VERIFIED — so the app
  published "⚡ regenerates hourly at reach ÷ tier", showed a new member their
  rate, and the rate was 0. `ENERGY_FLOOR_PER_HOUR` is the floor; reach still
  decides how fast it goes, the floor decides that it goes.
- **PromptZ could be bought with cash and nothing else.** Every free way to earn
  here — rating, referring, AdZ, OfferZ, OnboardZ — pays in 🍥, and 🍥 could not
  reach the AI. `catalog.SPINAZ_PER_PROMPTZ` (10:1) is the door; cash stays the
  fast lane and the subscription stays the shortcut.

And the inverse failure, in the same audit, which is what makes the first one
affordable to fix:

- **The allowance capped the COUNT and not the PRICE.** `charge_ai_usage` let a
  free daily prompt cover whatever the run cost, and the run's cost is the
  member's own engine choice — so StatZ's 10/day on Fable (15c) was $45/mo of
  model spend against a $15/mo subscription, while the margin comment beside
  `PROMPT_ALLOWANCE` reasoned at the 3c floor and described a ladder that did
  not exist. `DAILY_PROMPT_MAX_CENTS` is what one free prompt is worth. Dearer
  engines are paid for, which is what PromptZ is for.

So, when adding or moving a limit:

- **State it in a unit the member can check** — clips, characters, runs a day,
  MB. `KEY_TRANSCRIBE_DAILY_CLIPS` and `KEY_SPEAK_DAILY_CHARS` are two numbers
  rather than one on purpose.
- **A number that gates a capability needs a floor, not just a formula.** Any
  ladder derived from something a new member cannot have yet — reach, ratings,
  followers, history — starts at zero for everyone who has just arrived, which
  is precisely the audience it is supposed to be recruiting.
- **Anything metered by a cost must cap the cost, not only the count.** Or the
  ladder is whatever the most expensive path happens to be.
- **Check the free tier against the logged-out door.** If the anonymous trial
  gives as much as an account does, the account is not a step up, and the
  signup form is a wall in front of nothing.
- **Never lower a live limit without a plan for the members already over it** —
  the `TIER_LIMITS` note says this about storage and it is true of all of them.

### Energy is a refill, not a savings account

The constant said so from the start — "it regenerates like mana" — and the code
did the opposite: passive Energy accrued every hour forever with **no ceiling**.
A member who left a tab open for a month came back to thousands, and nothing on
the platform costs enough to spend that on. An unbounded resource stops being a
resource, and every price denominated in it stops meaning anything.

`ENERGY_DAILY_HOURS` × the hourly rate is the ceiling (`energy_daily_cap`), and
`settle_energy` tops up TOWARD it.

**The day turns at 04:20 America/New_York, for everybody, everywhere.** A
rolling 24-hour window means every member has a different reset, so "when does
my ⚡ come back" has a different answer for each of them and no screen can
print it — and two people comparing notes get different numbers with nothing
wrong. `energy_day_start` / `energy_next_reset` are that one moment, and
`/api/auth/stats/` publishes it. The zone is NAMED, not a fixed offset: EST and
EDT are both `America/New_York`, and pinning −05:00 makes it 3:20 or 5:20
depending on the season — a bug that ships in spring and gets reported in
November by somebody who can't describe it.

**Crossing the boundary RESETS; inside a day it drips.** "Your ⚡ comes back at
4:20 Eastern" has to be true at 4:21, or it is not a reset, it is a slow refill
with a start time nobody can see — so a member who crosses the boundary is
topped straight to the ceiling. Within a day the hourly rate still governs, so
reach and tier still decide how fast a spent tank refills. Both sentences the
app prints are true at once.

Three more rules, and the third is the one that protects members rather than
the economy:

- **The clock advances either way.** Returning early without moving
  `energy_accrued_at` would bank the same hours to be granted twice.
- **Idle does not earn.** A refill needs `Membership.last_seen` inside
  `ENERGY_ACTIVE_WINDOW_HOURS`; a tab left open in a drawer is not a session.
- **The cap NEVER takes anything.** Energy earned by rating, QuestZ, shares or
  OnboardZ sits above the ceiling untouched — `granted` is clamped to the room
  under the cap and floors at zero. Lowering a live limit without a plan for
  the members already over it is the one thing the limits note forbids, and
  "delete their balance" is not a plan.

## ViewZ — the first question anybody asks, answered honestly

A creator had ratings (which need somebody to act) and comments (which need
somebody to care) and **no answer at all to "did anyone see it?"** Silence
reads as "nobody", and "nobody" is why people stop posting.

`viewz.py`. The number is held to the same test as every other number here —
*could somebody get a good one without getting good?* A hit counter fails it in
one refresh, so:

- **A view is a viewer-day.** `ViewSession` is unique on
  (target, viewer, anon_key, day). Refreshing bumps `beats` and moves no count;
  coming back tomorrow does move it, because that genuinely is more attention.
- **The author's own looks never count.** Checking your own post is not reach,
  and letting it count makes the first number every creator sees a lie told by
  their own thumb.
- **`watching` is live and separate.** It is the number that changes behaviour
  — "3 people are here right now" is an invitation; "128 total" is a receipt.
- **Logged-out viewers count once per browser**, keyed by `X-MCZ-Viewer`. That
  id is clearable, so the count is a FLOOR, and the response says so in `note`
  rather than presenting a floor as a total. Presenting a floor as a total is
  the same class of dishonesty as an "AI craft estimate" computed from how many
  form fields somebody filled in.
- **The timeline reports the quiet hours.** `lanes_for` returns every bucket
  including the empty ones: a timeline with the silence removed lies about the
  shape of the day, and the flat stretch is half of what makes the spike
  legible.

Two performance rules it inherits from the feed: `views_for_posts` counts a
whole page in one query (the feed's query-count test is why), and the client
beats on a TAB, never per card — thirty cards each holding a heartbeat is
thirty requests every half minute, and "it scrolled past on your screen" is an
impression, not a view.

The day it buckets on is `local_day` — the same 04:20 clock Energy resets on.
Two different day boundaries would mean a member's views and their ⚡ reset at
different times and nobody would ever work out why.

### The gate that was hiding a member's own record

**LogZ was Premium-only.** A Free member asking "where did my SpinaZ go" got a
403 with an upsell in it — and `occ_spec.py` had *already* published SpinaZ and
Energy as things a Free member opens IN LOGZ, so the app advertised the door
and locked it. That is "it may never say whether" broken on the one surface
that is not a capability we rent out: it is the member's own account of what
the platform did to their balances.

`catalog.LOGZ_HISTORY_DAYS` replaced the gate. Everyone sees their ledger;
**depth** is the ladder — Free 30 days, Premium 366, StatZ everything — which
is a "how much" and allowed. Three things about it that are load-bearing:

- The response says `history_label` ("the last 30 days") and `hidden_by_tier`
  (how many rows are outside the window). **A limit that hides rows must say it
  hid them** — silence reads as "nothing happened", which is a different and
  worse claim than "there is more, further back".
- The totals are computed over the VISIBLE window, not the whole ledger. A
  running total over rows the member is not shown is a number nobody can check.
- `logz` is gone from `features.FEATURES` entirely, and `test_logz` pins its
  absence. A stale row there would put the lock back on the client's tile even
  though the endpoint answers everybody.

### A balance leads back to the action that changed it — now literally

`Transaction.open_in` (migration 0085) carries the same `"tab"` / `"tab:anchor"`
shape `goToSpot` takes, and `award_spinaz` / `award_energy` / `log_resource`
all accept it. A referral row opens EarnZ, a rating reward opens PostZ, a
BattleZ wager opens BattleZ.

**Blank means "we don't know", and renders as a plain row.** Deriving a
destination from the note text would send somebody to the wrong app, which is
worse than not offering the trip — the same rule `Upload.missing_since` follows
about only something that WENT AND LOOKED being allowed to stamp it.

### Members were listable and nothing listed them

`/api/economy/members/` — filters, range gates, distance, badges — had **no
caller in the mounted frontend at all.** Social ConnectZ rendered six invented
creators from a hardcoded array. Two things followed from nobody using it:

- It answered in one fixed order. `MEMBER_ORDERS` is the viewer's choice now
  (nearest / active / newest / rated / followers / experience / A–Z), published
  WITH the results so a client cannot offer a sort the server can't do, and
  every key sorts "no value" LAST — a member with no rating is not a member
  rated zero.
- It was about **seven queries a member**: two medians and three Follow queries
  per card, on up to 500 rows. `follow_counts_by_user` and `medians_by_user`
  do the page in one and three queries respectively, and `_profile_card` takes
  them pre-loaded exactly as it already did for badges. `test_members_order`
  pins a ceiling rather than an exact count, because what matters is that no
  query runs once per member.

`matched` and `scanned` ship beside `members` for the same reason as
`hidden_by_tier`: a count that only ever equals the page length would tell a
member the platform has exactly one hundred people on it.

### Known limit still owed a decision (Corey's, not the code's)

**Premium's allowance is pinned by Premium's price, and Premium's price is
pinned by the founding discount.** The founding seat is half of StatZ
($7.50/mo), and `catalog.py` asserts founding StatZ must cost more than
Premium — so Premium cannot exceed $7.50, and at $6/mo its AI allowance cannot
widen much past 5/day before the model cost eats the subscription (5/day at
`DAILY_PROMPT_MAX_CENTS` is $4.50/mo of the $6). Free went to 3 and Premium
stayed at 5, which is a thin gap. Making the founding discount LIFETIME-ONLY
would unpin the monthly ladder. That is a pricing decision, so the code
records it here rather than making it.

## A profile field has two writers, and only one of them used to clean

`POST /api/economy/profile/` wrote every name in `social.PROFILE_FIELDS`
**straight off the request body** — `setattr(p, f, d[f])`, with `substances`
the single exception — while `PATCH /api/auth/me/` normalized the same fields
properly. Two writers for one column, one of them a passthrough.

That is where `"{'name': 'Independent Artist', 'emoji': '🎤', 'skills': []}"`
came from: a persona reached the profile as the **printed form of a dict**,
58 characters, which fits under the 60-character cap a persona name is
truncated to — so it was stored whole and served back verbatim, and the
member's own card rendered machine noise where a persona should be.

**It broke quietly, and that is the part worth remembering.** Every consumer of
`profile.personas` guards with `if not isinstance(persona, dict): continue` —
postz's skill pricing, questz's rate check, occ_suggest, social's rate range
and experience metric, publicz's public card. Those guards are correct and are
why nothing ever 500'd. They are also why nobody noticed: a member in this
state saw no error, just a persona that read as noise, their priced skills
silently absent from what a post costs, their experience metric blank, and
their public card one persona short. **Nothing to report, so nothing got
reported.** A defensive `continue` over member data hides the corruption it
protects you from — so the guard belongs in a normalizer that repairs, not at
each call site that skips.

Three more things rode in through the same gap:

- **`links` was unvalidated**, and it is rendered as `<a href>` on the member
  card *and* on the logged-out public profile. A stored `javascript:` there is
  executable on a page a stranger can open — React warns about one and puts it
  in the DOM anyway.
- **Nothing capped a list**, so a profile row could be made arbitrarily large,
  and that row is serialized into every member card and search result.
- **`birthday` skipped the zodiac recompute and the explicit-voice revocation**
  that the same edit performs on `/api/auth/me/`. The read path re-applies the
  age gate (`test_voice`), which is why that one was contained rather than
  exploitable — but a second writer that forgets what the first one does stays
  contained by luck.

So:

- **`apps/economy/personaz.py` is the one shape.** `clean_persona`, `clean_link`
  and the `personas_of` / `links_of` read helpers live together, and
  `accounts.views` imports the same `clean_persona` rather than defining a
  second one. A field with two endpoints gets one cleaner, not two.
- **Repair on read, not only on write.** Fixing a writer does nothing for what
  it already wrote, and a member stays broken until they happen to save again.
  `socialData.js` already says this about localStorage; it is just as true of a
  column. Links especially: a refused URL must not be one un-run command away
  from being served.
- **`manage.py repair_profiles [--write]`** is the sweep that makes the
  read-side repair stop being needed. Dry by default, like `reconcile_uploads`,
  and it NAMES each link it refused rather than binning it silently.
- **Recovery parses, it never evaluates.** `ast.literal_eval` handles literals
  only, so a persona name cannot become code execution on a profile save.
  A name that merely looks like a dict is kept as typed.

## Tier limits live on the server

`apps/economy/catalog.py` is the source of truth for char limits, upload and
storage sizes, and prices. The frontend reads them from
`/api/economy/limits/`. Never hardcode a tier number in UI copy — that is how
the "20 free prompts" figure drifted into nine places.
