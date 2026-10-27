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
| Energy | ⚡ | mana; regenerates hourly at reach ÷ tier |
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

### ZodiacZ bonuses — the substance rule applied to a horoscope

`apps/economy/signbonus.py` is twelve bonuses, one per star sign, and the
obvious version of it breaks the substance rule in the first line. "Leos get
free SpinaZ" pays a **birthday** — nobody earned one, nobody can change one,
and the test the rule gives ("could a member get a good number without getting
good?") answers itself.

So **every bonus pays an ACTION, and the sign only decides WHICH action you
are nudged at.** A Leo and a Capricorn are pushed at different doors into the
same building and both still have to walk through one. That lands it on the
right side of the line CLAUDE.md already draws — *XP and badges may reward
effort. Ratings and skill levels may not* — because 🍥 is exactly the resource
effort is allowed to move.

Four properties hold it, and each is here because dropping it turns the
feature into a problem:

- **All twelve are worth the same** — `BASE` 20 🍥, `STRETCH` 50 🍥, one pair
  of numbers, not a table. A birthday is the one attribute a member cannot
  change, so it must never be the reason somebody earns less. There is a test
  asserting no bonus carries an amount of its own, because a per-sign number
  is the change that would look harmless.
- **It never touches a measurement.** No rating, no median, no skill level, no
  leaderboard position moves. The sign flavours what you are nudged toward,
  never what you are called.
- **Once each, plus a daily cap.** `unique_together = (user, sign, tier)` caps
  a member at 70 🍥 for life; `DAILY_CAP` is belt and braces for whoever adds
  a thirteenth.
- **The stretch is the SAME action, harder** — never a second action, and
  never the base reworded. Aries's base is going first and its stretch is
  going first *within the hour*; "first while it's empty" would have been the
  same sentence twice and a stretch nobody can miss is not one.

`try_award` swallows: a battle entry, a post and a rating all have to succeed
whether or not the bonus does. And **only actions that already exist** get a
bonus — every hook fires from a live call site (`postz.create_post`,
`battlez.BattleEnterView`, `models.record_referral`, `models.reward_for_rating`,
`skillz.training`, `venuez.VenueBookView`, `collab.CollabDealsView`), because a
bonus for something nobody can do is decoration and this codebase already
knows how those end up.

#### The other zodiac — twelve more, somewhere else in the app

`ANIMALS` is the same engine with the same two numbers, and what makes it
worth adding rather than doubling the first list is that the two zodiacs
disagree on a **different axis**: a star sign is a month and an animal is a
year, so the pairing is 144 combinations rather than 12. Two members born five
weeks apart share a sign and rarely an animal; two born eleven months apart
share an animal and never a sign. Nobody is nudged at the same pair as the
person beside them — and a push everybody gets is a push nobody notices.

**The animal actions are deliberately elsewhere in the app.** The star signs
cluster on posting, battling and being scored, because that is what a sign's
character is about — how you show up. The animals sit on the parts a member
can go a month without finding: escrow (`collab_deliver`, `collab_fund`),
the journal, the bug queue, curation, translation, OCC, external verification,
and the wallet's own 🍥 → 🏷️ door. A second zodiac aimed at the same twelve
buttons would be a louder copy of the first; aimed at twelve different ones it
is a map of the app. `test_signbonus` pins that: most of the animal tabs must
be tabs no star sign names.

Three things hold the two lists together:

- **One column addresses both.** `SignBonusAward.sign` takes a star sign OR an
  animal, and no name appears in both lists (no Aries is a Rat) — which is why
  `unique_together (user, sign, tier)` still means once-each. There is a test
  asserting the non-overlap, because it is load-bearing rather than a happy
  accident.
- **`_BY_ACTION` carries the KIND.** An action resolves to `("sign", key)` or
  `("animal", key)`, so a star sign can never answer an animal's action, and
  only one of the two lookups runs per call. A duplicated action key would
  silently make one of the twenty-four unreachable, so the module asserts on
  import rather than letting it ship.
- **The daily cap spans both.** Still 3, deliberately, now the board is twice
  the size — the cap's job is to stop somebody clearing it in one afternoon,
  and raising it because there is more to clear would undo the only thing it
  does. Once-each fixes the lifetime total at 140 🍥.

**The stretch pays the base with it.** Every one of the twenty-four is built
so the harder version includes the easier one — rating five today means you
rated one; being challenged by name to a 1v1 means somebody was already there
— so clearing the stretch first pays 70, not 50. Without that, a member whose
FIRST attempt clears the stretch is left owed 20 until they happen to do a
smaller version of the same thing, which reads as a punishment for doing well
and lands hardest on whoever engages most.

Two call sites are worth knowing about because they are the ones easy to get
backwards:

- **`social_verify._dragon` pays the LINK'S OWNER, never `request.user`.** On
  the manual-approval path the person pressing the button is the platform
  owner, and paying them for approving somebody else's account would be the
  feature exactly inverted. It fires from three places because verification
  has three genuinely different endings and no single line all of them cross.
- **`keyconnectz` and `occ_run` fire BEHIND their own meters.** A run not real
  enough to bill for is not real enough to pay for, which is the same rule
  `vocalcoach` already follows in the other direction.


`GET /api/economy/signbonus/` publishes **both of yours and all twenty-four**,
and both halves are the point: yours because the cost/gain rule is about the
gain being readable BEFORE you go and do the thing, and the other twenty-two
because the fairness of this is only checkable by seeing them. Each row carries
`tab`, so the screen offers the jump rather than naming an app and leaving you
to find it.

**The animal keys were added, never substituted.** `mine` and `all` keep the
names they shipped with and `mine_animal` / `all_animals` sit beside them,
because the screen reading this is in the other repo and the two deploy
independently — renaming `mine` would blank a live panel for however long the
frontend took to follow. An endpoint may grow keys ahead of its client; it may
never lose one, and `test_signbonus` holds the old ones in place.

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
- A post carries `destinations` — every app that can do something with it, what
  each still needs, and what it costs before it is spent. `apps/economy/crosspost.py`
  is the one list; SingZ and RapZ take the post itself as a Boss Take, so a
  finished track can be coached without being uploaded a second time.

When adding a screen, ask what a member would want to DO with each row, and
give them the link. A read-only surface is usually an unfinished one.

### Known violation, not yet fixed

- **LogZ was this rule's own counter-example, and it's fixed now.** This
  section used to say `Transaction.note` was free text with nowhere to go —
  true when it was written. `Transaction` carries `app_key`/`target`/`ref`
  now (the same shape `Observation` already used), threaded through
  `spend_spinaz`/`award_spinaz`/`award_energy`/`log_resource`, and
  `LogZ.jsx` renders real `goToSpot` links off `open_in`. See "Credits buy
  outcomes" below for the current state — `ref` (which resolves to a
  rating/report/file via `logz_outcomes.outcomes_for`) is still only set by
  the coach and Sentence ConnectZ, so most spends carry `app_key`/`target`
  but not yet a `ref`. That's the real remaining gap, not a free-text note.


---

## PartnerZ gets a benefit, never a stipend

Corey asked whether PartnerZ should be paid "for upholding the economy by
existing". The answer this codebase has to give is **no to a payout and yes to
a benefit**, and the line between them is one question:

> **Would this be worth anything to somebody faking it?**

A 🍥 or ⚡ stipend for HOLDING the status answers yes, twice over. It pays a
fixed past achievement forever — the substance rule inverted, because *could a
member get a good number without getting good?* becomes "yes: by getting good
once, in one week, in 2024". And the gate is passed once while the income never
stops, which is an annuity behind a one-time door.

`groupz.PARTNER_ESCROW_DAYS_OFF` answers no by construction. Escrow between
PartnerZ releases four days sooner, which is worth nothing at all to somebody
running two accounts: they own both wallets, so their own money reaching their
own other account sooner is money moving from one pocket to another. It only
pays when two genuinely separate people, with genuinely opposed interests, work
together AGAIN — so it costs nothing while a partnership is idle and cannot be
farmed while it is active.

It follows the Patron badge exactly, because Patron already solved the same
problem: the window is each PAYER'S own last chance to dispute, so **every payer
has to be a PartnerZ of every payee**, and it is still floored at
`ESCROW_MIN_RELEASE_DAYS`. Four rather than Patron's seven so the badge stays
the stronger thing and the two stack down to the floor.

### The hole this found, which is why the gate moved

`payers()` returns `[]` when nobody pays, so `all_funded()` is `all([]) == True`
— **one Fund call flips a zero-value deal to FUNDED, and `maybe_auto_release`
releases it on its own.** Three empty deals between two accounts cost nothing,
took no work and were PartnerZ. A list that is free to earn cannot carry a
benefit, so the count now requires the escrow to have actually HELD something
(money, SpinaZ or a stake), read before `release_deal` zeroes it.

### Battles count, and the reason is the same reason

Corey asked for battles alongside collabs. What makes it safe is not that a
battle is hard — it is that `settle_battle` only sets a `winner` when a side
cleared `BATTLE_MIN_RATINGS` judges, so somebody who is not one of the two of
them had to turn up. A battle that settles as a **draw** is one nobody rated,
and it does not count. Same shape as the collab rule: a third party settled it.

### It is a tally now, not a scan

`Partnership` is an ordered pair (`a_id < b_id`, so one row and never two that
disagree) with two counters, incremented once by the thing that just settled.
It replaced a Python scan of up to 2000 released deals per read, which was
affordable for one tab and impossible for `escrow_release_days`, which has to
answer per deal card.

It is a **tally of events, not a second opinion** — which is the distinction
`groupz.py`'s own docstring draws when it refuses to store FriendZ. Follow is a
live table you can read cheaply; a settlement is an event that has to be
counted when it happens. Both hooks are swallowed (the money has already moved
and a tally must never be able to undo that), which means the tally can drift,
which is why `manage.py rebuild_partnerships [--write]` exists — dry by default
like `reconcile_uploads`, and it **replaces** rather than adds, because a
counter you can only increase is one a double-fire corrupts permanently.
Migration 0119 seeds it from the events that already happened; without it,
shipping the tally would have silently emptied the tab for everybody who had
already earned a place on it.

### And the window is finally on the screen

`auto_release_days` has been in `deal_dict` since CollabZ was written and **no
screen ever read it**, so a payer funded a deal without being told how long
their money sits or when their dispute window shuts. The cost of funding is the
amount AND the days, and only the amount was on the button. `EscrowWindow` in
`CollabZ.jsx` states both now, which is also the only place the PartnerZ
benefit is visible — a window quietly four days shorter than the card beside it
reads as a bug rather than a reward.

---

## One person, one account (Corey's rule — a platform rule, not a design one)

**Every member gets one account. Duplicate accounts are not accepted.**

It is written down for members in `apps/economy/rulez.py` and served by
`GET /api/economy/rulez/` — open logged-out, because the screen that most needs
it is the signup form, where nobody is signed in yet. **No screen retypes it.**
A rule stated in three places reads three ways within a year, and a rule people
are held to has to be one they were actually told.

The reason is the one the substance rule already gives: everything here is
counted per person — reach, ratings, referral rewards, the daily AI allowance,
one vote in a battle. A second account is a second helping of all of it, and
every one of those numbers stops meaning anything the moment it can be doubled.

### Enforcement is a deletion, so it is deliberately narrow

`apps/economy/dupez.py` is what `rulez.one_account`'s `enforced_by` names, and
that field exists so a rule cannot quietly become a wish: grep the key and you
find both ends. Four things hold it:

- **Nothing is inferred and acted on.** `signals_between` returns the FACTS two
  accounts share — same email, same email on a linked sign-in, same referrer —
  each labelled and weighted strong or weak. **Never a score.** A "78% likely
  duplicate" is the substance rule's exact failure case with an irreversible
  action behind it.
- **A member may only ask about their OWN other account.** There is no "report
  this person for having two" — that door gets used for something else inside a
  week.
- **The owner decides, except where the member can prove it.** Same email on
  both accounts is your own mess and you may close the other one yourself.
  Anything weaker is an `AccountClaim` and it waits. Refusals are written down
  and the claimant is told either way: a queue somebody's account disappears
  into without a word is worse than no queue.
- **Weak signals never group anybody.** Two friends who joined on the same
  invite are two people, and an accusation built out of a coincidence is worse
  than a duplicate nobody noticed.

### Closing one without signing in to it takes PROOF, and proof is not a percentage

Corey's bar: deleting a duplicate from the main account, without ever signing in to
it, needs better than 90% certainty it is the same person. This is that bar, and it is
deliberately NOT a probability. Nothing here is calibrated — there is no set of labelled
duplicates a "92% likely" could have been fitted against — so the number would be made
up to look like a threshold, behind an action nobody can undo, which is the first rule
of this file. What can be stated is the evidence, and **proof is a stricter bar than 90%:
the provider confirmed the same address on a linked sign-in of BOTH accounts**
(`dupez.has_proof`). Two accounts sharing a confirmed inbox share an owner.

- **`email_verified` defaults to False and only a confirmed sign-in sets it.** Existing
  identities start unverified, so until each member signs in with that provider again
  their linked address proves nothing and the close falls back to a claim. That is the
  safe direction: the cost is a few more claims, never a wrong deletion.
- **A claim is finished by signing in to the other account** (`DupeZVerifyView`), which
  is a better proof than any hint — they know both passwords. The response says
  `confirm_by_sign_in` with the username, and the client keeps the main account signed in
  on the device for the switch back.
- **An account that is not proven tied to yours is not shown in full.** `redacted_card`
  gives a handle and the reasons, never the email, balance or posts, so the screen cannot
  be used to read somebody else's account before closing it.
- **`PROOF_RULE` is the sentence the screen shows**, served with the list; nothing retypes
  it, same as `rulez`.

### A delete may destroy work. It may never destroy money.

`AccountDeleteView` has always wiped a wallet holding real cash without a word.
Survivable when it is your own account and your own decision; not survivable
here, where the account being deleted is usually not the one pressing the
button. So `delete_duplicate` **refuses** when money or royalties would be lost
and there is no account named to sweep them to, and the refusal states the
amount.

**Money and royalties sweep. Energy, SpinaZ, PromptZ and XP do not**, and that
line is the whole design: cash is the member's and destroying it is taking it,
but the game resources are exactly what a second account exists to farm.
Sweeping those would make the tidy-up the payout — three accounts, three lots
of onboarding, merged into one. A duplicate's game balance dies with it.

A swept balance writes a `Transaction` (`KIND_TRANSFER`, its own kind so it is
not totalled as revenue that only ever moved sideways), because a balance that
appears with no reason behind it is what LogZ exists to stop.

### It is not a BugZ report, and that was a real decision

BugZ's queue is **public on purpose** — "everyone sees the queue", so nobody
files the same thing twice. A claim names two accounts and the evidence tying
them together, so filing one there would publish which handles belong to the
same person, for every member who ever came forward under the rule that asks
them to. `AccountClaim` has its own owner-only queue, following
`moderation.ReportView`.

### What the old finder got wrong

`manage.py find_duplicate_accounts` could not find the case it existed for. It
queried `oauthidentity__email` — the reverse name is `oauth_identities` — so
that branch raised `FieldError` the moment a real cross-email duplicate
existed, meaning it only ever "worked" on a platform that had none. It also
looked for one OAuth identity on two accounts, which
`unique_together = ("provider", "provider_uid")` forbids. And `--notify`
printed to stdout and then said "✓ Notifications sent to N users" having sent
nothing.

It reports and stops now, off the same `dupez` detection the screen uses, so
the command and the screen cannot disagree about what a duplicate is.

## FunnelZ offers: springing a sale is fine, springing a FAKE one is not

FunnelZ has only ever MEASURED — `FunnelEvent` counts landing → try → register
for a visitor with no account, owner-only, and nothing acted on it.
`apps/economy/offerz_engine.py` is the other half: the promotions that reach a
member who is already here, arriving without being asked for.

The whole design is one distinction, and it is the substance rule with a price
tag on it. *Could a member get a good number without getting good?* reads here
as **could a member get a good deal without the deal being good?** A countdown
that resets on reload, a "was $50" against a price nobody paid, a "last 3
seats" that says 3 forever — each is decoration wearing a discount's clothes,
and each is found out by the first person who looks twice. Selling
subscriptions to musicians who have been sold to their whole careers, being
caught once is the end of it.

Five rules, and every offer answers to all five:

1. **Cost and gain up front**, in the resource emoji, on the control. A
   promotion is the one place it is most tempting to lead with the gain and
   put the price in the small print.
2. **A deadline that does not end is a lie.** `offers_for` drops an expired
   offer AND `redeemable` refuses it — both directions, because the client
   keeps whatever panel it already rendered, and an offer that still works
   after it "ended" teaches members every deadline here is theatre.
3. **Scarcity is counted, never claimed.** "3 left" comes from
   `founding_status()["remaining"]`, a real row count, or it is not said.
4. **It is TRUE when it is shown.** Every offer is computed from the member's
   own state at request time. Nothing is blasted, scheduled or aimed at a
   segment — a time-triggered promotion cannot answer this rule, because what
   made it true was the date rather than the member. `test_funnel_offers`
   asserts every `when` is a callable.
5. **Dismissible, and it stays dismissed** (`OfferDismissal`). An offer that
   comes back after being closed is not a promotion, it is an obstruction, and
   the member's only answer is to stop opening the app.

**Every CTA lands on the CONTROL, not the tab.** Each row carries
`tab` + `target` and the panel uses `goToSpot`. "Go to MembershipZ" is where a
funnel dies: the member arrives at the top of a screen they have never seen,
hunts, and leaves. That is the cross-pollination rule applied to marketing —
the difference between a funnel and a poster.

Three things that must not rot:

- **The context is built ONCE.** `_context` reads the wallet, membership,
  profile and counts in one pass; eleven offers each calling `wallet_for`
  would be eleven queries on a panel that renders in one. A `when` needing a
  twelfth query is a `when` to re-think, not a query to add.
- **A predicate that raises hides ONE offer, never the screen.** An offer
  panel that 500s because a single check met an edge case is worse than one
  promotion going unseen. Tested.
- **`prompt_walls` counts the WALL, never a successful run.** It is the only
  number a paid offer is sold at, so it has to be a fact — "they met the
  ceiling three times" rather than "they seem engaged" — and it ROLLS over a
  week, because a lifetime counter would keep selling to somebody long after
  they settled into a rhythm that suits them, which is rule 4 broken by
  arithmetic.

**The free door always sits beside the paid one.** `prompts_wall_no_spinaz`
exists so a member out of both AI and 🍥 is shown how to EARN some rather than
how to spend some they do not have — the ladder rule as an offer, and the two
are never shown together.

`FunnelOfferRedeemView` grants nothing. The offers are doors; the thing behind
each door keeps its own endpoint, its own price and its own checks, because a
redeem that granted things would be a second place every one of those prices
lives.

### The owner sees the offers that DON'T fire, which is the half that matters

`/offerz/funnel/` answers "what is true for ME", capped at three. Right for a
member, useless for whoever runs the platform: from inside that panel there is
no way to see an offer nobody has ever matched — which is exactly the
decoration this section warns about, and it was invisible from the only
surface that existed.

`GET /api/economy/offerz/catalog/` is owner-only and returns the whole list,
each row carrying:

- **`why`** — the reason the offer exists. It is written beside every offer in
  the code and, until this view, was served nowhere. A promotion whose reason
  lives only in a comment is one the next person rewords into something that
  no longer has one.
- **`live_for_me`** — whether the engine says it is true for the caller right
  now, so the owner watches it decide rather than taking it on trust.
- **`dismissed_by`** — and that is the ONLY count. A dismissal is an honest
  signal (somebody saw it and said no); "impressions" would need a write on
  every render and would turn a read-only panel into a tracking surface.

It lands in **FunnelZ**, beside the join-funnel measurement, because the two
answer the same question from opposite ends: the measurement says where people
stop and the catalogue says what the platform does about it. Split across two
tabs, nobody looks at both — which is the only way either number means
anything.

That gap was worth noticing on its own: the offer engine shipped with its only
surface living inside PostZ, so the feature had no tab, and the owner had
nothing to pin.


## The funnel could not see the step that was losing everybody

Thirty days: 103 landed, 13 opened the trial, **1 got a score**, 0 registered.
The offer engine, the founding seats, the zodiacs and the referral ladder are
all downstream of a number that is one.

Between `try_view` and `try_scored` there is a RECORDER, and it was one
unmeasured step. Nothing in `FUNNEL_KINDS` could tell a refused mic from a
take nobody sent from a take the coach failed — three problems with three
opposite fixes, indistinguishable from the only two rows that existed. Five
kinds now name them: `try_record`, `try_mic_denied`, `try_attach`, `try_send`,
`try_failed`. `try_failed` carries a `why` from a closed list of slugs, never
the sentence the visitor read — the reason decides what gets fixed, and free
text is how a table that holds no PII starts holding some.

*(The client-side half of that story is in the frontend's CLAUDE.md and is
worth reading: the four recorder events had been added four days earlier
under names this endpoint rejects as unknown kinds, by a commit that also
left `track` unimported — so the Record button threw before `getUserMedia`
and the trial recorded nothing at all. A closed set is right; a closed set is
also why a client typo measures zero instead of measuring wrong.)*

### It happened again, eleven times, and the omission is the half a closed set cannot catch

An audit of every kind the client fires against every kind this endpoint
accepts found **eleven** being POSTed and answered 400. Same silence as the
recorder events, for the same reason: `track()` swallows its own failure so a
measurement can never take a feature down, which also means a rejected kind
and a recorded one look identical from the client.

Five were wanted and are declared now — `onboard_habit`, `onboard_skip`,
`onboard_prefs`, `oauth_linked`, `oauth_link_fail`. They are the first kinds
here that describe what happens AFTER the account, which the funnel has never
been able to see: it ended at `register_success`, and an account that never
finishes onboarding is a row rather than a member. The other six were
engagement telemetry from signed-in members — notifications read, sound
preferences changed — and were deleted at the call site instead. This table's
promise is that a row is a browser with no account and is never joined against
Users; a member's settings panel has no business writing to it.

Three things hold it now:

- **Both closed lists are read, never retyped.** `_PROVIDER` is
  `provider_requirements()` — the one list of provider names — after the first
  draft typed the eight in and got it wrong immediately, listing `apple`,
  which that function has commented out. `_FREQ` is `Habit.FREQUENCY_CHOICES`.
  A funnel that accepts a provider no button can fire, or a cadence no habit
  can have, is measuring something that does not exist.
- **`oauth_link_fail` keeps the provider and drops the error text.** The client
  sends `linkErr.message`, which is whatever the server or the network said —
  free text, on the table that holds none, exactly as `try_failed`'s `why` is a
  slug rather than the sentence the visitor read.
- **The client mirrors this list in `src/funnelkinds.test.mjs`** and fails if it
  fires a kind the mirror does not hold. The two repos deploy independently and
  this endpoint decides; the mirror is what makes an omission visible from the
  side that would otherwise never see it.

`kind` is `varchar(20)`, and four of the five arrived longer than that
(`onboarding_preferences_confirmed` is 32). Django's system check refuses the
model, so the build fails rather than the column silently truncating — the one
loud failure in this whole story — and the names are terse now to match the
rest of the list rather than widening a column to fit one of them.

### Ambient keys, because a per-kind allowlist grows holes

`src` and `dev` are true of the VISIT, not of the step, so they ride every
kind via `AMBIENT` instead of being remembered per entry. That is not tidying:
`register_success` and `login_success` were shaped under the key
`"registered"`, which is not a kind, so **neither of them ever stored a
`src`** — the per-channel table's register column was structurally always
zero, and the one number a marketing spend is judged on could not be non-zero
however well a channel worked. Listing those two would have fixed those two
and left the next kind with the same hole.

`dev` is `phone` / `tablet` / `desktop`, **measured on the client from screen
width and `pointer: coarse`, never from a user agent** — the rule
`useScreenShape.js` already follows, and it matters more here than anywhere
else: the trial's first move is a browser mic dialog, and a permission cliff
on a handset is not one on a laptop. One number covering both hides whichever
is real.

### The three rates, and who was on the other end

`headline` pins landing → trial, trial → scored, scored → account above the
step rows, each with BOTH counts: 100% of two people is not a working funnel
and a bare percentage cannot say so. `pct` is `None`, never `0`, when nobody
reached the top of a step — a 0% against no visitors reads as a broken
product, and an empty measurement and a bad one need opposite responses.

`members` answers "who stayed" rather than "who visits", and is deliberately
NOT part of the funnel rows. A `FunnelEvent` is a browser with no account: it
has no age and no gender, and attaching either would break the model's own
promise that nothing there is joined against Users. So gender and age bands
are counted off `Profile`, and three rules hold it — the denominator is
ACCOUNTS (a `Profile` is created lazily, so counting those would drop members
who never went near a screen that makes one), `unset` is a row rather than a
rounding error, and an age is a band and never a date.

## The trial door's rate limit was wrong in both directions at once

An audit of the whole logged-out path, asking "what stops a stranger getting a
score", found the per-address ceiling doing the opposite of its job.

`TRIAL_PER_IP_HOURS = 24` meant **one free take per IP address per day**, and
an IP address is not a person:

- **Against an honest visitor it was far too tight.** Mobile carriers run
  CGNAT — a single IPv4 address fronts thousands of subscribers — so the first
  person on that carrier to try the door spent the free take for everybody
  behind it. The rest were told *"You've had your free take for today"* about a
  take they never had, on the one screen a stranger ever sees, and most
  strangers arrive on a phone. It is also unanswerable: there is nothing they
  can do about somebody else's handset.
- **Against an abuser it did nothing at all.** `client_ip` read
  `X-Forwarded-For[0]`, and each proxy APPENDS, so entry `[0]` is whatever the
  CALLER wrote. One header bypassed the entire limit. A control that stops the
  people it is not aimed at and not the ones it is, is not a control — and the
  module docstring cited it as the thing standing between us and a bill.

What actually caps the money is `trial_daily_cap()`, which refuses rather than
overspends. It always was; the per-IP rule just read like it.

So the count is keyed per **browser** (`TrialTake.anon_id`, the same
localStorage UUID the funnel uses), `TRIAL_PER_IP` is a loose backstop sized
for a shared carrier address and kept well under the global cap, and
`client_ip` counts hops from the RIGHT (`TRUSTED_PROXY_HOPS`, 1 for Render —
raise it if a CDN goes in front).

Four things not to undo:

- **A blank `anon_id` never matches anybody.** Private-mode browsers throw on
  localStorage and send `""`. Treating every one of those as the same visitor
  would shut the door on all of them at once. It is "unknown", not a match —
  which is also why the IP backstop stays rather than being replaced.
- **`address_busy` is its own refusal, with its own sentence.** The fix for
  one is an account and the fix for the other is us raising a ceiling, and the
  copy never phrases it as something the visitor did. It is also its own
  `try_blocked` slug, so the funnel can finally tell the two apart.
- **An unscorable take does not use up the free take.** The coach listened and
  there was no performance in the file — silence, room noise, the wrong upload
  — so the visitor spent a performance and got no number, and trying again
  with a real take used to answer "you've had yours". `TrialTake.scored` is
  what browser_done counts. The row is still written and still counts against
  the address and the global cap, because we paid for that model call either
  way and a call that left no row would be money spent off the books.
- **The per-IP ceiling must stay below `trial_daily_cap()`.** One address may
  never be able to spend the whole day's budget. There is a test.

### And the public stats endpoint had never once answered

`TrialPublicStatsView` queried `visitor_id` in four places. The field is
`anon_id`, so every request was a `FieldError` — a 500, from the day it
shipped. The client made it moot by asking for `/api/trial/public/stats/`,
which is not where it is mounted, so the call 404'd before it could reach the
500. Both ends broken, and silent, because the caller swallows the failure.

What it served was the bigger problem. It published the **join funnel's own
conversion rates to the people standing in the funnel** — rendered on the
trial door, under the heading "What members do", which at the numbers that
produced it reads *"Tried → Scored 5%"* and *"Scored → Registered 0%"*. That
is a measurement of how well OUR door works, not of whether the coach is any
good, and handing it to somebody deciding whether to try argues against
trying. The three rates belong in FunnelZ, where the owner reads them, and
FunnelZ already has them.

It serves counts now — takes scored, and how many instruments have a door.
Both true, neither a percentage anybody can be on the wrong side of, and both
go UP as the platform works. And it stays silent below `MIN_TO_SHOW`: "3 takes
scored" is worse than no panel, which is the same rule `pct: None` follows.

## A route is not the same as a door

`test_instrument_routes` pins that a scored profile in `instruments.py`
becomes a route. `apps/economy/trialdoorz.py` pins the layer above it.

`INSTRUMENT_APP_KEYS` mounts `/api/<key>/trial/` for **seven** instruments and
the front door linked **two**. GuitarZ, BassZ, KeyZ, DrumZ and ViolinZ each
had a working, scored, no-account coach that nothing on the internet pointed
at — and it was invisible from the funnel by construction, because a step no
visitor can reach never appears as a drop-off.

`GET /api/economy/trialdoorz/` publishes them, read off the URL conf rather
than typed into a list, and open logged-out for the same reason `rulez` is:
the screen that needs it is the one nobody is signed in on. Each door carries
what it scores, so a drummer can tell the place is for drummers — reading
"pitch, breath, range" they would correctly conclude otherwise.

`door_keys()` is also the funnel's `app_key` allowlist. It was the pair
`("singz", "rapz")` typed into `views.py`, so the day a GuitarZ door opened
its events would have arrived with the app dropped and read as no traffic at
all.

## PersonalitieZ: a declaration is allowed here precisely because it is not a score

`apps/economy/personalityz.py` is four axes — I/E, N/S, T/F, J/P — declared by
the member, stored as one four-slot code on `Profile.personality`, and
filterable from the one member search every screen uses.

The substance rule's test is "could a member get a good one without getting
good?" This never has to answer it, because **there is no good one**: an axis
has two sides and neither is better. That is the entire licence for the
feature, so three lines hold it and none may be crossed later for convenience:

- **It never touches a measurement.** No rating, median, skill level,
  leaderboard position or price moves because somebody typed a letter. It
  changes who you SEE and nothing about what anyone is CALLED.
- **Nothing is inferred.** It is not scored from posts, takes or message
  patterns. "We detected you're an Extravert" would be `directz_ai_rating`
  wearing a personality quiz — a number derived from activity and presented as
  a fact about a person. `test_personalityz` asserts no third writer exists.
- **Undeclared is a third state, everywhere.** `-` is not "average" and not a
  default. A member who answers two axes has given a complete answer to two
  questions, not an incomplete answer to four.

Four more things worth not undoing:

- **A code is read positionally.** "PFNI" is "INFP" backwards and reads as
  NOTHING, not as a reversal — a code that can mean two things is a filter
  that is silently wrong. The module asserts on import that no two axes share
  a letter, because that is what makes positional reading safe.
- **Junk never refuses a save.** An unrecognised letter becomes "hasn't said".
  A profile write must not 400 over one character, and a wrong letter silently
  kept is worse than a blank.
- **The undeclared never match a filter, and the searcher is TOLD.** A search
  for Introverts that returned everybody who said nothing is a filter that
  does not filter. But an empty grid has two completely different causes —
  nobody matches, or nobody has said — and on a field this new the second is
  almost always the real one, so `filter_reason` returns the count that was
  hidden and why. Letting somebody conclude "there are no Introverts here"
  from a field nobody has filled in is the emptiest kind of wrong.
- **One filter, in `MembersView`.** Not in a dating app of its own.
  `MembersView` IS the member search on this platform, so a filter added there
  is one CollabZ, BattleZ, VenueZ, MessageZ and VybeZ all get. A personality
  field that only worked in the dating screen would be the fourth copy of a
  profile filter within a year.

**Deliberately not called MBTI.** Myers-Briggs is somebody's trademark; the
four letters are in general use. This ships as four axes with plain-English
labels, no type nicknames and no personality descriptions — which is also the
honest scope, since we are storing what a member told us rather than
publishing a theory about them.

One writer, reached twice: `clean_code` is imported by BOTH `social.py`'s
`clean_profile_field` and `accounts/views.py`, per the two-writers note above.

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

**Corey's standing instruction: merge without asking.** Don't stop at a green
branch to request permission — verify it (the repo's own checks, and for the
backend the full suite plus a column-width check on any new migration), then
merge and push. The merge is still the deliberate act; the deliberation is the
verification, not a question. Backend first whenever a screen needs a new
endpoint.

**Corey's second standing instruction: apply your recommendation, don't ask.**
When you have weighed something and have a view, take it — the recommendation
IS the decision, and a question that hands it back unanswered wastes the
reasoning that produced it. Two things this does not license. It is not
permission to skip the weighing, and a recommendation still has to say what it
traded away, because the value of the judgement is checkable only if the cost
is stated with it. And it does not cover a choice that is genuinely not the
code's to make — a price, a name, whether a real credential gets stored — where
the honest move is still to lay the options out. If in doubt: decide, ship, and
say plainly what you decided and what it cost, so it can be reversed by
somebody who disagrees.


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

## WidgetZ: the tier buys WHERE a link opens, never whether

`apps/economy/widgetz.py` turns a link into one of four answers, and the split
is about **who wrote the URL being framed**:

- **player** — a provider with a documented embed endpoint. The id is read out
  of the member's link and the provider's own player URL is built HERE, so
  nothing a member types reaches the frame. Available at every tier for exactly
  that reason. `test_widgetz` pins it: a link with junk appended still frames
  the clean embed.
- **internal** — one of our own public addresses. Never framed; the client
  opens the real screen, which beats an iframe of ourselves at every tier.
- **page** — an arbitrary site framed whole. **StatZ, and only for a URL the
  malware scan cleared.** A page inside our chrome borrows our chrome's
  credibility, which is what makes a framed login form worth building for
  somebody who wants one; the scan is the floor and the tier is who we hand a
  general-purpose frame to.
- **outside** — everything else, in a new tab. **This is what keeps the ladder
  rule intact.** No member loses a link; every tier opens every link. A refused
  page widget returns the link with the reason attached, so a Free member is
  told what StatZ would have done rather than finding a control that quietly
  behaves differently from the one beside it.

### An unscanned link cleared nothing

`links.scan_available()` exists because `safe_browsing_check` answers "safe"
when it *cannot look* — the right answer for a click (we don't block a member
on our own outage) and the wrong one for anything treating a verdict as a
permission. With no scanner key, a page widget is refused for everyone, StatZ
included, with that as the stated reason.

Two quiet lies came out of building on it:

- `LinkClickView` set `counter.scanned = True` whether or not a scan ran, so a
  deploy with no key recorded every link on the platform as checked and clean.
  The docstring already said we never claim a link is scanned when it isn't;
  the column said we do.
- **The key was never readable.** `settings.SAFE_BROWSING_API_KEY` was fetched
  with a `getattr` default and never defined in `settings.py`, so it was "" on
  every deploy however the dashboard was set. No member link has ever been
  scanned, and there was nothing to notice — an unscanned link and a clean one
  both come back safe. `test_link_scan` now asserts the settings *exist*, which
  is the dullest test in the suite and the one that would have caught it.

### Set WEB_RISK_API_KEY, not SAFE_BROWSING_API_KEY

Google's terms put Safe Browsing v4 at "non-commercial use only — not for sale
or revenue generating purposes", and this platform sells subscriptions, so v4
is the wrong product here however well it works; it is deprecated besides.
**Web Risk is its commercial successor** — enable the Web Risk API on a Cloud
project with billing on, make an API key, restrict it to that one API. Free to
100k lookups a month, then $0.50 per 1,000.

`links.scanner()` picks: Web Risk when its key is set, Safe Browsing when only
that one is (a non-commercial deployment of this code is entitled to it), and
"" when neither. The two speak differently and the difference is easy to get
backwards — Web Risk's `uris:search` is a **GET** with the URL in the query and
an empty `{}` body meaning clean; v4's `threatMatches:find` is a POST with a
`threatInfo` document. Posting a v4 body at Web Risk is a 400, and a 400 comes
back from `safe_browsing_check` as "safe", so getting it wrong looks exactly
like a platform where nothing is ever flagged. `test_link_scan` pins the method
on both.

**And a stub cannot tell you the key works.** `tools/linkscan_live_check.sh` is
the check that can — it looks up a URL Google publishes as a known threat and
fails if the answer comes back clean. That direction is the whole point: a
scanner that says "clean" to everything passes any check that only ever asks
about clean things, and this failure mode is invisible from the app, because
`safe_browsing_check` answers "safe" on an error too. Run it after setting a
key, after rotating one, and after touching the scan.

### The sandbox pair that must never be granted together

`allow-scripts` + `allow-same-origin` lets a sandboxed frame remove its own
sandbox. `SANDBOX` has scripts and not same-origin, which is what makes a page
widget a viewer rather than a tenant. `allow-popups` is out too — a framed page
that can open a window is one that can open a window over ours.

### What cannot be detected, and is therefore said out loud

Whether a site permits framing is the site's call (`X-Frame-Options`,
`frame-ancestors`) and there is no way to ask ahead of time — from inside the
page a refused frame and a slow one are identical. So `may_refuse` travels with
the spec and the client keeps "open it in a tab" on screen, rather than a
detection we would have to invent and would get wrong.

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

## The wallet primitives were a read-modify-write, in Python, with no floor

Every reward on this platform goes through three helpers, and all three looked
like this:

    w = wallet_for(user)
    w.spinaz = (w.spinaz or 0) + int(amount)
    w.save(update_fields=["spinaz", "updated_at"])

No lock, no floor, and the arithmetic done in the PROCESS rather than the
database. Two proven failures, neither theorised:

- **A lost update.** Two requests read the same row, each computes its own
  total, and the later write wins. Spending 50 twice from a balance of 100
  left **50** — one of the two spends simply vanished. Gunicorn runs two
  workers of four threads, so eight request threads can be inside this at
  once, and everything is in here: rating rewards, referrals, AdZ, OfferZ, the
  twenty-four zodiac bonuses, battle entries and wagers, collab escrow.
- **No floor.** `award_spinaz(user, -500)` on a balance of 10 left **-490**.

`_bump_wallet` does it with `F()` now, so the database does the arithmetic and
concurrent moves add up instead of overwriting each other. `select_for_update`
would also work and is what `collab.py` and `payouts.py` already use for the
paths somebody thought about — an F-expression is cheaper and needs no
surrounding transaction to mean anything, which matters because several
callers here are not in one.

### A spend is a different operation from a credit, and now says so

`spend_spinaz` is a CONDITIONAL atomic decrement:
`filter(spinaz__gte=amount).update(spinaz=F("spinaz") - amount)`. One statement
the database serialises, so a second spend racing the first loses and is told
so, and the balance cannot go under.

Both battle paths needed it. Each read the wallet, compared it to the stake,
and then spent in a SEPARATE statement — and a member is not obliged to wait
between the two. They answer 402 now rather than overdrawing.

Two properties worth keeping:

- **A refused spend writes no ledger row.** LogZ exists so a balance change
  has a reason behind it; a spend that did not happen must not appear as one.
- **A spend of zero or a negative is not a spend.** It returns None rather
  than quietly becoming a credit.

## A deal you were a participant in disappeared once the platform grew

`CollabDealsView.get` found them by fetching the **300 most recent deals
platform-wide** and filtering in Python. So a deal somebody else put you in
silently vanished from your screen once 300 newer deals existed anywhere —
the row stayed in the database, with whatever the escrow was holding still
held by it. It gets worse the better the platform does, which is the worst
property a bug can have.

`CollabParticipant` is the fix, and it is the same fix `PostContributor`
already is for a post — that docstring says it in four words: **JSON for
display, a table for lookups.** Deals never got one.

A `participants__contains` lookup would have been the obvious answer and is
not available: the suite runs on SQLite, production is Postgres, and that
lookup is Postgres-only. `offerz_engine._json_contains_works` already
documents this and answers it by skipping the query where the backend cannot
do it — right for an offer (a skipped offer shows nothing) and wrong here,
because it would mean a deal list that works in production and is untestable.
A table works identically on both.

Three things hold it:

- **It is DERIVED, not maintained.** A `post_save` signal reconciles the table
  from the JSON, so no call site can forget it — every writer already edits
  the JSON.
- **The signal is guarded on `update_fields`.** The release paths save with
  "participants" in their list and `maybe_auto_release` runs on every deal in
  the list view, so an unguarded signal would put two queries on every card of
  a READ.
- **It is swallowed, so it can drift, so there is a rebuild.**
  `manage.py rebuild_collab_participants [--write]`, dry by default and
  REPLACING rather than adding — same shape and same reasoning as
  `rebuild_partnerships`. Migration 0126 seeds it, because shipping the table
  without a backfill would have emptied the deal list for every participant:
  the exact failure the table exists to fix, caused by the fix.

### And both list screens were paying per row

    deals    42 queries for 40 deals     ->  1, at any length
    battles  123 queries for 40 battles  ->  6, at any length

BattleZ had three per card — the rating median, the entry count, and a
per-battle `exists()` asking whether I had entered. That last one is one
question about one member, and it was asked once per row.

## Two screens that re-poll, and every row on them cost a query

The feed re-polls every 30 seconds from every open tab, and VybeZ fires the
member search from three TEXT INPUTS. Neither is a page-load cost — they are
standing load that every idle member contributes to forever — so their query
counts are the ones to watch.

Both measured, both linear, both now flat:

    feed     108 queries for 50 posts    ->  11, at any length
    members  322 queries for 39 members  ->  15, at any count

**The feed**, three per-card counts: `shares`, `joins` and `rating`.
`_reactions_for`, the CollabDeal count and `take_state_for` beside them had
already been collapsed into one query each; these three were missed.

`joins` is the one worth remembering: it sits behind
`if p.visibility == "restricted"`, so **a feed of public posts measures two
N+1s and a real feed has three.** A benchmark built from convenient data hides
the case that costs.

**The member search**, six: two rating medians, a FaceZ rating join, a
membership read (no `select_related`), and the followers query **three
separate times** —

1. `follow_counts` counts them,
2. `social_sources` fetches the same rows again to build the "Music ConnectZ"
   reach source out of them,
3. `reach_median` rebuilds that entire source list from scratch, followers
   query and all, to take a median of a list its caller was already holding.

Three reads of one table, in one function, on every card. Each was locally
reasonable — `reach_median(user)` reads as a tidy one-liner — and the cost
only exists in the composition.

`worn_badges_by_user` and `Audience` directly above them were already batched,
which is the tell: somebody did this work and stopped at the two that were
obviously expensive.

### Two tests had the N+1 written into their expected value

`test_postz_collab` and `test_crosspost` each measure the feed's cost as a
DIFFERENCE between a short feed and a long one — the right shape, and why they
survived this at all. But both asserted **two extra queries per card**, and
each says why in its own words: *"the feed already does two per-card queries
(shares, rating median) that predate this change and aren't mine to fix
here."*

So the N+1 was found, documented, and pinned as expected cost. Both assert
**zero** now, which is also the only version that cannot rot: `== 2 per card`
goes green again the moment somebody reintroduces an N+1 of exactly the right
size, and `== 0` cannot.

A per-row cost noted in a docstring as somebody else's problem is a per-row
cost that never gets fixed. If a test has to describe a known inefficiency to
explain its own number, that number is the bug.

### What the batched versions must not quietly change

A batch that changes an answer is worse than the N+1 it replaced, so each has
a test beside the count test:

- **A missing key is None, not 0.** `.get()` on a batch dict returns None and
  the per-user helper returned None — which is luck rather than design until
  it is pinned. A fake rating ends the question; an empty one invites a real
  one.
- **`follow_edges_for` returns the SETS, not four numbers.** friends is the
  mutual set and fans is one-way, so handing back counts would mean doing that
  arithmetic in two places.
- **The single-card callers keep working with nothing batched.** A public
  profile and a member modal render one card, and one card's six queries is
  not worth a batching call site — so `batched=None` falls through to the old
  path, and there is a test that it still does.

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

## BodieZ is its own Android app, and it opens its own site

`android/` builds two apps from one project (`mcz` and `bodiez` Gradle flavors,
one CI run, two bundles). The decision worth keeping is what BodieZ OPENS:
**the BodieZ-only web build on its own host** (`npm run build:bodiez` in the
frontend, `bodiez.musicconnectz.net`), never `/bodie` on musicconnectz.net.

The first draft pointed at `/bodie`. It would have been the whole Music ConnectZ
app in a different icon — the profile, orientation, substance-use and
attractiveness-rating screens that make the main app a Data safety question, and
the Premium purchase flow that makes it a Play Billing one — with a listing that
said "a workout log". The shell that avoids all of it already existed in the
frontend; the Android app wraps that.

Two things that follow, both easy to get backwards:

- **Chrome verifies a TWA against the host it launches into**, so each app needs its
  own `assetlinks.json` on its own host. This backend's route and `TWA_*` variables
  are Music ConnectZ's; BodieZ's file lives in the frontend repo
  (`standalone/bodiez/public/.well-known/`). A draft served a second package from
  here — it would have verified nothing and had somebody set Render variables and
  believe it worked.
- **A number in a store listing is a tier number in copy.** "60 of 90 exercises are
  seated or lying" is quoted in `play/bodiez/listing/` (frontend) and goes stale the
  day the library moves. `tools/count_adaptive_exercises.py` prints the current
  figures; re-run it before every release.

**The Android workflow had never run.** A step's `if` cannot read `secrets`, so GitHub
refused to parse the file ("Unrecognized named-value: 'secrets'") — 630 runs, every
one failing before a step started, which reads as a flaky build rather than a dead
one. Nobody could have pressed "Run workflow" and got a bundle. Fixed by routing the
secret through the job's `env`. If a workflow "fails" instantly with no steps listed,
read the parse error before blaming the build.

`test_android_kit` holds what can be held without an Android SDK: distinct
packages, per-app `asset_statements`, resource references that resolve, art at the
sizes Play wants. Gradle itself only runs in CI.

## Deleting an account has to delete what it uploaded, and the policy is a claim about this code

`user.delete()` cascades the ROWS, and a Django `FileField` never deletes its bytes
when its row goes. There was no `post_delete` signal, no cleanup package and no sweep,
so every track, video, photo and avatar stayed on the disk (or in the bucket) after
the member was gone — while the privacy policy and the delete-account page both said
"your uploads" were deleted. `Face` images and avatars are pictures of people.

`apps/accounts/erasure.py` is the one way to delete an account now, and all four doors
use it (`MeView.delete`, `UsersView.delete`, `AccountDeleteView`, `dupez.delete_duplicate`).
Three decisions in it are the ones to keep:

- **Files are found BEFORE the delete** (afterwards the rows that name them are gone) and
  **removed AFTER it commits** (a rolled-back delete must not leave rows pointing at files
  somebody already removed).
- **A storage error is logged, never raised.** The member asked to be deleted and the rows
  are gone; a bucket having a bad minute is not a reason to 500 and leave a half-deleted
  account for somebody to retry by hand.
- **The models are found, not listed.** Any model with a `FileField` and a CASCADE
  foreign key to the user. A SET_NULL row is kept, so its bytes are kept too (a `Face`
  that merely TAGS the member survives them). A fifth door that calls `user.delete()`
  directly would bring the bug back, which is why a test reads the source of all four.

### Deleting cancels the billing first, and refuses if it can't

The ids that let anyone cancel a subscription live on rows that cascade away
(`Membership.stripe_customer_id`, `last_payment_ref`, `AutoTopUp`), so a delete that
ran first left a card billed monthly by an account nobody could reach. The member
found out from their bank. `apps/economy/stripe_cancel.py` runs BEFORE
`user.delete()`, from `erasure.delete_user`, and all four doors get it for free.

- **A failure refuses the delete (502, `CancelFailed.detail`).** The alternative is a
  deleted account still being charged, which is the worse outcome and the one this
  exists to prevent. Nothing is lost by refusing: the member retries. The screen, the
  web page and the privacy policy all say "if it can't be cancelled, the account is not
  deleted", so changing this means changing four places together.
- **Cancel is immediate, with no refund of the rest of the paid period.** There is no
  account left to hold the benefit for the remainder, and every screen says so before
  the button. Proration is a product decision; this is the version that is true today.
- **The membership row cannot be trusted to remember, and the first version of this
  trusted it.** Every Checkout creates a NEW Stripe customer (none passes `customer=`)
  and the webhook OVERWRITES `stripe_customer_id` / `last_payment_ref` with the newest.
  So Premium followed by StatZ — a path MembershipZ offers — leaves two live
  subscriptions on two customers and one row naming one of them. Review ran exactly
  that through the real webhook: the delete cancelled StatZ, succeeded, and Premium
  kept billing. The unit test beside it put both subscriptions on ONE customer, a
  state this app's checkout cannot produce, and passed for the wrong reason.
  `StripeSubscription` is the append-only ledger the webhook writes once per
  subscription (`stripe_cancel.remember`), never overwritten, and `cancel_for` reads it
  alongside the membership and auto-top-up rows and then LISTS every customer any of
  them names. `LedgerTests` drives the two-customer case through the real webhook and
  the real delete; dropping the `remember` call turns it red.
- **A payment that lands after the account is gone is cancelled on sight.** A Checkout
  stays payable for hours and its `checkout.session.completed` then names a deleted
  user; the webhook used to answer 200 with nothing to attach it to. It calls
  `cancel_orphan` now, and a failure there answers 5xx so Stripe retries — the opposite
  of every other branch, because a 200 here is a subscription that bills forever.
  Residual window: a payment that completes INSIDE the few seconds of someone's own
  delete pass. Not closed; it needs the member to pay and delete in the same breath.
- **`manage.py backfill_stripe_subscriptions [--write] [--cancel-orphans]`** is the
  past. The ledger starts empty, so a member who upgraded before it existed still has
  an unnamed subscription, and accounts deleted before the cancel existed may have
  subscriptions still billing. Stripe's own Checkout Sessions carry the member's id, so
  the command reads them, writes the missing ledger rows, and LISTS live subscriptions
  of deleted accounts; `--cancel-orphans` ends them. Dry by default, and cancelling is
  its own switch. It needs the live key, so it can only be run where that is set — it
  has been tested against a fake, never against Stripe.
- **A customer another account also references is never swept.** `stripe_customer_id`
  is not unique, and cancelling "every subscription on this customer" for a customer a
  second member also uses would bill-stop a stranger. Shared customers are skipped and
  logged. `dupez.delete_duplicate` cancels the TARGET's billing before the money sweep
  and passes `billing_stopped=True`, so the cancel happens once and a refusal leaves the
  duplicate untouched. It then re-reads the cash: the pass is seconds, an auto-top-up
  invoice paid inside it credits the wallet, and a figure read before would sweep
  nothing and delete the credit.
- **It fails closed on its own misconfiguration.** Ids on file and no
  `STRIPE_SECRET_KEY` refuses (billing may exist and nobody can reach it); no ids and
  no key is a dev box and passes. `resource_missing` is "gone" only when Stripe is not
  saying a similar object exists in the other mode — a test key asked about a live id
  answers the same code, and reading that as success would make a wrong key look like a
  platform where every delete works and nothing is cancelled. Every acceptance is logged.
- **A refusal after a partial cancel says so.** Stripe's own webhook downgrades the plan
  the moment a subscription ends, so a member refused after part of it went through
  sees Free. `CancelFailed.detail` adds that sentence only when something was cancelled.
- **One budget (`BUDGET_SECONDS`, 15) over the whole run, and the number is measured.**
  A per-call timeout is not a per-call bound: `requests` applies it to each socket
  operation and the SDK retries once after a pause, so an 8s setting was measured at
  16.5s per stalled call, and the budget is only checked between calls. At
  `CALL_TIMEOUT_SECONDS` 4 a stalled call measured 8.5s, so the worst pass is about
  24s, inside the 30s `api.js` waits. `test_the_whole_pass_fits_inside_the_wait_the_screen_allows`
  pins the arithmetic; if the client's wait moves, so does that test.
- **The Django admin is a door too, and was the fifth.** The stock user admin calls
  `user.delete()`: no cancel and no file purge. `accounts.admin.UserAdmin` routes single
  deletes through `delete_user` and says why on a refusal; bulk delete is removed, since
  Django reports "Successfully deleted N" from the selection size whatever happened to
  each account.
- **Not done:** the Stripe *customer* and its saved card are left in Stripe (we cancel
  billing, we do not erase the payment record), and `AutoTopUpCancelView` still flips
  `active=False` when its Stripe call fails (which is why the inactive row is still
  checked). Both are in the frontend's `play/bodiez/README.md`. Also unreviewed:
  subscriptions attached to a Subscription Schedule.
- **Pre-existing, found by the review, now fixed:** DupeZ's self-serve close counted
  `oauth_email` (the same address on two linked sign-ins) as strong proof while
  `OAuthLinkView` stored whatever address the provider returned without knowing whether
  the provider verified it — so one member could set an unverified address on their own
  sign-in and close another member's account. `OAuthIdentity.email_verified` is recorded
  at link and sign-in time (`_provider_vouches`) and `has_proof` counts the address only
  when it is true on BOTH accounts. See "Closing one without signing in to it" above.

**What deletion still does not do, on purpose or by omission:** it does not pay out
money (the screens say so), and a member's own transaction history cascades with them.
The second contradicted a sentence in the privacy policy for as long as the policy
existed. If the LLC needs to keep financial records for tax, that is an
anonymise-don't-cascade change, and the policy changes with it.

The BodieZ paragraph in `public/privacy.html` (frontend) was checked claim by claim
against this repo before it went live; "we do not show it to other members" needed an
exception for the workout summary a member posts or sends themselves, and
"three movement answers" was five.

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

## 853 seconds on a spinner: the failure where nothing failed

A member sent a 3:05 take and watched **"Scoring your take… 853s"**. No error,
no 500, no dropped connection, nothing in any log. **Every single component was
doing exactly what it was configured to do.** That is what makes this worth
writing down at length — it is the failure mode that no amount of error
handling catches, because nothing errored.

### The arithmetic

    Files upload            timeout=300
    wait_active poll        40 tries x (20s GET timeout + 1.5s sleep)  = 860
    generateContent         timeout=300  PER MODEL, and the chain has four
    ------------------------------------------------------------------------
    one request could legally run for              2360s = 39 minutes

**853 is `wait_active` one tick from the end of its own worst case.** The
member was sitting in that loop, and the loop was bounded by a TRY COUNT while
each try carried a 20-second timeout on a request that fetches a one-line
status document.

Every one of those numbers is defensible alone. 300s for an upload is right —
a big take over a slow link is still a take. 40 polls is right — video is
transcoded after upload and takes a while. The bug is that **nothing added
them up**, and the sum is what the member experiences.

### The thing that was supposed to stop it, and why it didn't

`render.yaml` says `--timeout 120`. That reads as a request timeout. It is not.

`--threads 4` selects gunicorn's **gthread** worker, and its main loop is:

    while self.alive:
        self.notify()                      # "I am alive" to the arbiter
        self.wait_for_and_dispatch_events(timeout=1.0)

It calls `notify()` **every second regardless of whether a request thread is
blocked**. `--timeout` is the arbiter's check for a stale heartbeat, so with
gthread it bounds an *idle or wedged worker*, never a slow request. A thread
can block on `requests.get` for as long as its own timeouts allow and the
arbiter never notices.

So the config that looks like it bounds a request bounds nothing, and it looks
correct in review. That is the part to remember: **`--timeout` means different
things to different gunicorn workers, and the one we run is the one where it
does not mean what it says.**

### And the client had no timeout at all

`api.js` had no `AbortController` and no `signal`. `fetch` with no signal waits
as long as the other end is willing to. So even if everything above had been
fine, a hung proxy would have produced the same spinner.

### What now stops it

- **`apps/economy/deadline.py`** — ONE budget for the whole run
  (`COACH_BUDGET_SECONDS`, 100s), made at the view and passed down. Every leg
  asks `remaining()` and can never get more than is left. Per-call timeouts
  answer "how long may this ONE call hang"; nobody was answering **"how long
  may this member WAIT"**, which is the only number a person experiences.
- **Running out is an ANSWER**, a 504 with a sentence and a next move, and
  nothing is billed. `Expired` carries the member-facing text because the
  catch site is usually not the one that knows what they were doing.
- **The poll is bounded by the clock, not the count**, and its status GET has
  a 5s timeout instead of 20 — it reads one line of JSON, it is not a
  transfer.
- **The client has a bound too**, deliberately LONGER than the server's, so a
  server that answers in time is always the one that decides and the client
  only fires when nothing answered at all.

### The general rule this leaves behind

**A timeout on a call is not a budget for a request.** If a request makes N
calls, its worst case is the SUM, and nobody reviewing any single line will
see it. Anything a member waits on gets one deadline, made where the request
starts, passed down — and every timeout below it is a cap on that, never an
addition to it.

The corollary is the one that bit here: **a number that only goes up is not
progress.** It cannot distinguish "working" from "hung", which is the single
thing the person watching needs to know.

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

## A profile in `instruments.py` is not the same as a route

`INSTRUMENT_APP_KEYS` in `music_connectz/urls.py` is the ONLY thing that turns
an instrument's scored profile into `/api/<key>/coach/`, `/api/<key>/trial/`
and a SkillZ tree. Adding an instrument to `instruments.py` — dimensions, a
caveat, `prompt_for()` support — does not by itself make it reachable.

That gap held for a while: guitarz, bassz, keyz, drumz and violinz had full
profiles, and `prompt_for("drumz", ...)` was tested and correct, while
`INSTRUMENT_APP_KEYS = ["singz", "rapz"]` meant every one of those coaches
404'd. `test_instrument_routes.py` pins both directions now — every key in
`INSTRUMENTS` is in `INSTRUMENT_APP_KEYS`, and the coach/trial/SkillZ routes
actually resolve for each — so a future instrument added to one list and not
the other fails a test instead of shipping a coach nobody can reach.

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
  nothing on the axis people arrive for. It was 3, and is 4 now (below).
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

### The free daily prompts are 4 / 7 / 12 (Corey's call, Oct 2026)

`PROMPT_ALLOWANCE` is Free 4, Premium 7, StatZ 12. The ceiling, for a member who
spends every free prompt every day at `DAILY_PROMPT_MAX_CENTS` (3c): $3.60/mo for
Free, $6.30 of Premium's $7, $10.80 of StatZ's $15 — and $10.80 against a founding
month's $10.50, so a founding member who maxes it daily costs a little more than they
pay. At the coach's ~2.75c a take the YEARLY founding seat ($105/yr, $8.47/mo after
Stripe) is $1.43/month short for a member who maxes it daily — 50 seats, so ~$72/mo at
worst, platform-wide. `test_pricing` pins those gaps. Typical use is far below the ceiling; this is written down so the next move is
made knowing it. Every screen reads the numbers from `/api/economy/tiers/`, and the
tests read the constant, so moving it again is one line.

## Nothing in this project was rate limited, including the login door

Not configured in settings, not applied to a single view. `/api/auth/login/`
took **25 wrong passwords in a row** and answered 400 to every one, and would
have taken 25 million. Registration had accepted the literal string
`password` until the same audit fixed it, so every account that signed up with
a top-100 password was one script away.

`apps/accounts/ratelimit.py`. Two decisions shape it and both are lessons from
elsewhere in this codebase:

- **It counts FAILURES, not requests.** DRF's own throttles count every call,
  which means a member who signs in successfully all day slowly runs
  themselves out of budget, and a suite that logs in a hundred times starts
  failing for a reason unrelated to what it tests. A good password clears the
  bucket. The limit is invisible to everybody who is not guessing.
- **It is keyed BOTH ways, and neither alone.** The trial door's lesson,
  applied before it could bite again: an address is not a person. Keyed only
  on IP it punishes everybody behind a carrier's CGNAT for one stranger's
  typos; keyed only on the account it does nothing about somebody walking a
  list. So the ACCOUNT limit is tight (8) and the ADDRESS limit is loose (40),
  and only failures ever count.

A successful login clears the account's bucket and **not** the address's — the
account has proven who it is, the connection has proven nothing, and one real
login among a run of guesses is exactly what a successful guess looks like.

The address comes from `economy.clientip`, for the reason that module exists:
**DRF's own `get_ident` uses the WHOLE `X-Forwarded-For` string when
`NUM_PROXIES` is unset**, so an attacker varying that header gets a fresh
bucket per request and the limit stops nobody. There is a test that spoofs a
different prefix on every attempt and asserts it still gets a 429.

Counts live in Django's default LocMemCache and gunicorn runs two workers, so
they are PER WORKER — the real limit is about double what is written. Fine for
what this is (a scripted guesser hits it either way), and the reason the
numbers are not tuned finer.

### What the login and OAuth audit found working

Worth recording, so the next person does not re-derive it. Login resolves by
username OR email, case-insensitively on both. The OAuth link flow refuses a
tampered pending token, a token minted for a different provider, an identity
another member already holds, and a replay of a spent token — each with the
right sentence. `oauth-config` reports per-provider readiness rather than
enabling a button the exchange cannot finish.

One thing deliberately NOT changed: login says "No account matches that login"
and "Incorrect password" as separate messages, which is username enumeration.
Usernames here are already public (every profile is), so the enumeration it
allows on a handle is free anyway, and the specific message is what tells an
honest member they typed the wrong email rather than the wrong password. A
generic "those don't match" would cost real signups to protect something the
public profile route already gives away.

## A username had THREE writers and one rule, applied by none of them

The same audit, run on the signup flow. `check-username/` carried a real
handle rule — `^[a-zA-Z0-9_]{3,20}$` — and was the only thing that had one. It
sat behind `IsAuthenticated`, so the single screen that needs it (the signup
form, where by definition nobody is signed in) could not call it, and nothing
did. Meanwhile:

- **`RegisterSerializer` had no rule at all.** It is a plain `Serializer`
  rather than a `ModelSerializer`, so Django's own `UnicodeUsernameValidator`
  never ran, and `create_user()` does not call `full_clean()`. The field was
  `CharField(max_length=150)` and nothing else.
- **`MeView.patch` had the regex typed out a second time**, with no reserved
  list — so a Premium member could rename themselves `admin`, `support` or
  `official`. Impersonation, behind a paywall.
- **`_unique_username` (the OAuth path) allowed `.` and `-` and 140
  characters**, so a provider display name of "bob.obrien" made an account the
  form would refuse.

Every one of these registered, and each was a real account:

    "a/b"                 public profile 404s — no screen could address them
    "who?"  "hash#tag"    their own ?ref= invite truncates at the ? or #
    "<script>x</script>"  goes wherever a handle goes
    "@everyone"  "."      reads as a mention; is a path segment

`apps/accounts/usernames.py` is the one rule now and all three import it.
`_unique_username` SANITIZES rather than refusing, because an OAuth sign-in
must not fail over an apostrophe in somebody's display name — that is a wall
in front of the easiest door we have.

`manage.py audit_usernames` names whoever is already over the line, because
"never lower a live limit without a plan for the members already over it"
applies to a handle too. It has **no `--write`**: a username is the address
other members type and the invite link they share, so renaming somebody
without asking breaks every link anybody ever made to them.

### The password rule was enforced on the weaker end

`AUTH_PASSWORD_VALIDATORS` has been configured since the project was started.
`passwords.py` runs them on a RESET. **Registration ran `min_length=8` and
nothing else** — so you could sign up with the literal string `password`, and
then be refused that same password if you ever tried to change to it. Held
forever, and the only way to find out it was not allowed was to try to stop
using it.

### And the Premium handle change had never once worked

`changed.append("username")` fed `Profile.save(update_fields=...)`, and
`username` is a **User** column — so it raised "fields do not exist in this
model" and 500'd, one line AFTER the handle had already been saved. The rename
worked and reported failure: the member sees an error, tries again, and is
told the handle is taken by themselves. `first_name`/`last_name` hit this
exact trap and were given their own `named` list; this one was missed.
Anything on User gets its own save and never goes in `changed`.

## Five modules each had their own copy of "whose request is this"

`trial.py`, `postz.py`, `links.py`, `adz.py` and `dupez.py` each carried the
same four lines, and all five were wrong the same way:

    fwd.split(",")[0].strip()      # the entry the CALLER writes

Each proxy APPENDS the address it saw, so a request arriving with its own
`X-Forwarded-For: 1.2.3.4` leaves our proxy as `1.2.3.4, <real>`. `[0]` is
whatever the sender invented — and every one of the five is a control that
reads it:

- **`postz`** mints 🍥 per "distinct authenticated user + IP", and its own
  comment says the cap exists "so rotating IPs / accounts can't farm it".
  Rotating IPs was one header.
- **`links`** pays +5 ⚡ per genuine visit, capped per address per day.
- **`adz`** pays per ad view, capped per address per day.
- **`dupez`** records the address an account SIGNED UP from, and two accounts
  sharing one is a duplicate signal — spoofable in both directions: hide your
  own second account, or put somebody else's address on your signup and raise
  a flag against them.
- **`trial`** gated the one free no-account take.

`apps/economy/clientip.py` is the one reader and counts hops from the RIGHT
(`TRUSTED_PROXY_HOPS`, 1 for Render alone, 2 with a CDN in front).
`test_clientip` walks the tree and fails if any module reads the header
itself, because a sixth copy is how this comes back.

**Nothing keyed on an address should be a hard "one per address" rule.** Too
few trusted hops over-trusts the caller; too many reads one of our own proxies
and collapses every visitor onto a single address. It is a ceiling or a
signal, never the only control — which is the same conclusion the trial door
reached from the other direction.

## The signup screen was the tenth place a tier number lived

`Register.jsx` had "3 scored takes/day", "5 scored takes/day", "2x faster
Energy" and both referral amounts typed into its copy, because
`PublicTiersView` served upload/storage/char limits and **not the allowance
every join screen actually sells on**. It serves `daily_prompts` and
`energy_per_hour` now, plus a `join` block with the welcome and referral 🍥.

Two things that came out of writing it down:

- **The "2x faster Energy" claim was wrong for its own audience.** The
  reach-derived rate is `reach ÷ divisor` (10 free, 5 premium — 2x), but reach
  is 0 until an external account is VERIFIED, so anybody reading a signup page
  is on the FLOOR: 2 and 6 ⚡/hour, which is 3x. The copy understated the thing
  it was selling.
- **`SIGNUP_WELCOME_SPINAZ` is paid on every registration and was named on no
  screen.** The gain half of the cost/gain rule, and the half that gets
  forgotten — a reward found out by accident is a coincidence, and a
  coincidence changes nobody's behaviour.

"Advanced analytics" and "Priority support" were also on the Premium card and
**neither exists anywhere in this codebase**. A signup page selling two
features that were never built is the substance rule with a price attached.
Both gone.

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

---


### Corey's fixed numbers — do not change without him saying so

- **StatZ character limit: UNLIMITED.** Never a number. It was set to 5,000
  for a day and Corey reversed it with "never change statz char limit from
  unlimited". `test_limits.test_statz_is_unlimited` and the two
  `test_bio` no-ceiling tests pin it.
- **Premium: $7/mo, $60/yr.** "dont change premiums price from 7/60".
  `test_pricing.test_the_published_numbers` pins it.

A tidier ladder, a margin argument or a "consistency" pass is not a reason
to move either. Ask him first.

## RapZ judges five dimensions of the take, plus the register it detects

A rap take is scored on **Flow 🌊, Timing ⏱️, Breath 🫁, Clarity 🔍 and Delivery 🔥** — dimensions about how the verse sits rather than what it says. That is deliberate. The model hears the performance; scoring on what makes a rap *good* is a conversation between the member and their listeners.

But the blueprint listed "Writing Score 📝 — rhyme density, structure, originality, punchlines, storytelling depending on style" as a core dimension alongside the five, and it was never built. It still isn't, because **lyricism depends on genre** — an old-school rapper cares about wordplay while a mumble-rap artist is after texture, and the same words score 2/10 in one style and 9/10 in another. A score derived from FORM rather than HEARD CONTENT would trip the substance rule — "could a member get a good one without getting good?" — and the answer would be yes, every time a member fills the Storytelling box without saying anything.

So `lyrics: True` opts the member IN. The model watches the bars roll and reads them, same as it does for SingZ. A member working on flow has the choice: send it to be judged on the performance and ignore the words, or opt in and ask for both. A take that scores high on lyricism but low on flow learns the member's writing is stronger than their delivery, which is real information.

The five dimensions are served at `/api/rapz/coach/` the same way SingZ serves its five — the model scores each, and nothing cascades.

### Register is always there; it is just finally visible

A rapper's register has been detected in the lab since before this app shipped — the screenshot of a rap take reads "your range reads Bass, D2 to B4". But RapZ had no `ranges` field and no `range_label`, so a take that arrived with a detected register had nowhere to go. The screen could not say what it heard.

It is visible now, under the label "Your register" and the same eight vocal range classes SingZ uses. A member who took both SingZ and RapZ gets told the same range by the same model — because pitch is pitch — and can learn whether their singing register and their rapping register match. **No choice to hide it, no tier gate to mute it.** The information was always there; now it goes somewhere.

### Rap styles: one list, never two that disagree

A rapper picks a style — Boom Bap, Trap, Drill, Cloud Rap, Lyrical, Storytelling, Freestyle, Melodic, Double-Time, Old School, Conscious, Mumble — and the coach scores how close the take comes to the form the member is aiming at. It is served from `apps/economy/instruments.py` so the style the member picked and the style the coach knows about are one list, not two that drift.

The model answers as a number and prose: "your delivery is methodical, which is closer to old-school than Trap" travels with a 0-100 score. Neither the number nor the prose alone is complete; a number with no reason is decoration, and prose with no number cannot trend or recommend. Both together answer what the take does RIGHT now rather than inventing a fixed rating.

### Every dimension serves its own purpose

- **Flow 🌊** — the pattern and rhythm of the verses. Is the cadence locked?
- **Timing ⏱️** — does the take align with the beat?
- **Breath 🫁** — is breath control visible in the performance?
- **Clarity 🔍** — can the words be understood?
- **Delivery 🔥** — does the take connect? Is it energized?

Each one is something a TAKE can show — which is why "Consistency, Health and Goal Match" live on the progress screen instead. A single verse shows whether a rapper's timing is improving; a week of verses shows whether they are developing as a performer.

### Style Match — now every instrument has this

The blueprint listed Style Match among RapZ's core scores and it was served only as prose (`style_fit`) — the number nobody could trend, nobody could recommend from, and the history never reported on. A rapper who was getting better at their chosen style had no way to know it was working.

Style Match is **added for every instrument** now, not only RapZ, because every take carries a genre. The substance rule says a score derived from FORM is not a score. Style Match is derived from HEARING — does this drum take SOUND like the drill record it is aiming at? — and it is the same question whether the instrument is drums or rap. The prose stays (an explanation is not decoration). The number is new and it is there to move.

Style Match is sent from the same call that scores the five dimensions; it is not a sixth dimension but rather what the model already hears when it listens for those five.

---

## Every scoring dimension must have a description served nearby

A member sends a take to the coach and gets back a score. The number means nothing without knowing what it measures. **Every dimension — Flow, Timing, Clarity, Consistency, Intonation, Groove, anything the coach scores — must have a short, honest description that lives in the endpoint alongside the score.**

`apps/economy/instruments.py` holds all of them: `_VOCAL`, `_RAP`, `_FRETTED`, `_KEYS`, `_DRUMS`, `_BOWED` and `STYLE_SCORE` are dictionaries mapping score keys to their labels. A member looking at "Flow 🌊 — 7/10" without knowing what flow IS has a number with no meaning, and a number a member cannot check or understand teaches them nothing about their performance.

**Three rules about these descriptions:**

1. **They live in ONE place.** If a dimension is scored, it is defined in `instruments.py`. If `prompt_for()` in `vocalcoach.py` names a dimension the endpoint does not declare, or vice versa, that is a test failure — `test_instrument_routes` pins both directions. A client that knows a dimension the server does not is the change that makes a screen show a blank score.

2. **They must be SHORT.** "Flow 🌊" is complete; "Flow 🌊 — the rhythmic pattern and cadence of your delivery including how you sit on the beat" is what a hover tooltip says, not what a label is. The label reaches the screen; keep it to one or two words plus the emoji. The expanded explanation lives in the coach's own caveat (the text that says what one take CAN show) or on a help screen that is ONE click away from the score.

3. **They are HONEST about what a single take shows.** The caveat says it: "Flow, timing, breath, clarity and delivery are what one take can show. Consistency, health and goal match come from your history, not a single clip — they're on your progress screen." A member who sees "Consistency — 4/10" without that sentence believes they are inconsistent after one take, which is false. `_HISTORY_CAVEAT` is that sentence, and it is the same for every instrument, because the rule is the same: a single clip is a snapshot, a week is a trend.

A take endpoint that adds a dimension without updating `instruments.py` ships silently — the frontend has no label for it, so it renders blank. A coach that drops a dimension does the opposite. Both are invisible failures because a score with no description is just a number, and a member staring at a missing score has nothing to report — they assume their take was not scored. `test_instrument_routes` guards this: every key in `INSTRUMENTS[key]["scores"]` + `STYLE_SCORE` is the exact set the coach is asked to produce, in the exact order, with no additions and no removals.

### This is also why the coach response stays structured

`_score_dict()` in `vocalcoach.py` returns a dictionary with one key per dimension. The response is NOT a free-form text description ("Your flow is good, your timing is tight, your breath control...") because a free-form response cannot be *scored* — nothing in it can be trended, compared, recommended on, or added to a history. A dimension must be:

- A **number** so it can trend
- A **key in the dictionary** so the frontend can find its label
- A **field in EVERY response**, always, never optional — a missing dimension reads as a zero or a failure

The prose explanation stays (Style Match includes it), but it rides ALONGSIDE the score, never instead of it. Both are necessary: the number moves, the text explains what moved.

---

## The overall score had no instruction for how it relates to the facets under it

Corey sent a verse in and got a 5/10 — "you've got the bones and the emotional honesty down, clean up the tongue stumbles on your fast lines" — for a song that human listeners on RepostExchange had just rated 9.7. Not a bad coach and not a lying one: the read was accurate, the fixes were real, and the prompt's own `THE SCALE` correctly anchors 5 as "solid, ordinary, nothing broken." The problem was one level up. `"score": <overall 1-10 integer, or null if unscorable>` asked the model for a number and never said how it should relate to the `"scores"` dictionary sitting right next to it in the same response. Nothing wrong was computed — nothing was computed at all. The model was left to invent its own combining rule, and the rule it reached for by default reads exactly like a technical instructor's: one facet that's rough sets a ceiling on the whole take, because that is how grading usually works when nobody says otherwise.

That is not how an actual audience hears a song. A listener does not average five sub-scores and does not get capped by the weakest one — they remember what landed, and one rough facet (diction blurring on the fast bars) does not erase a real hook or a performance that connects. `ScaleIsAnchoredTests` above already fixed this exact shape of bug once, for the bands themselves — an undefined "1-10" defaulted to a released-record reference and told every developing artist to quit. This is the same failure at the layer above the bands: an undefined "overall" defaulted to weakest-facet grading and told a member their best verse yet was ordinary.

`prompt_for()` now says explicitly, right where the bands end: the overall is not an average of the dimensions and never the weakest one, a carrying strength (the hook, the emotion, the energy) may outweigh one fixable rough facet the way a real listener would let it, and the weak facet belongs in `"fixes"`, not in the number. The floor is named too, on purpose — a take that is shaky **throughout** still scores low, because this is a calibration fix, the same kind `ScaleIsAnchoredTests` was: the number still has to move because the performance moved. It is not licence to inflate a take that has nothing carrying it, which is the same guard `test_it_did_not_become_a_licence_to_flatter` already holds one section up, and `OverallIsNotTheWeakestFacetTests` holds this one to the identical standard — a take shaky throughout is still told so.

RepostExchange's 9.7 is not the target to hit, and the fix does not chase it: that number comes from an exchange platform where reciprocal rating is the norm, which is exactly the kind of number the substance rule warns about — a score a member can get without the song being good. What the fix corrects is real and independent of that comparison: an AI coach that could not tell "ordinary" from "strong take, one habit to fix" was measuring the wrong thing regardless of what any other platform said about the same song.

---

## Two more calibration bugs, found the way the last one was: Corey scoring his own takes

Same complaint as the section above, sharpened: the trial door was costing signups on two separate axes, and the fix for neither is a floor.

**1. Medium was still landing low.** `ScaleIsAnchoredTests` had already moved the reference point off a released record — 5-6 was "solid, ordinary, nothing broken," and the docstring is correct that this fixed the undefined-anchor failure. But "5 is normal" is still a low number to see after a real attempt, and a visitor deciding whether to make an account reads a 5 as "below average" whatever the caveat beside it says — nobody's mental model of 1-10 puts the midpoint at "good." **The bottom of the scale did not move.** 1-2 and 3-4 are exactly what they were: a real attempt that is mostly getting away from someone still scores there, and there is still no floor under it. What moved is where ORDINARY lands — 5-6 became 5-7, and the anchor line now reads "6 is normal" instead of "5 is normal." A developing artist's solid, unremarkable take reads as a 6 or 7 now, not a 5, and a rough one is exactly as rough as it was.

**2. Nothing set the model's temperature.** Every scoring call ran at Gemini's default sampling temperature — tuned for creative variety, because that is what the API is FOR most of the time. A coaching score is the opposite kind of task: it is a judgement, and two calls against the same take should land close to the same number, or the coach reads as inconsistent rather than calibrated. `vocalcoach.COACH_TEMPERATURE` (0.3, env-overridable the same way `MAX_MB` is) pins it down. Low enough that the same performance gets the same read twice; not near-zero, which tends to make the prose repetitive rather than making the JUDGEMENT any more consistent — degenerate output is not the same thing as a stable one.

Both bugs shared one root: nothing in the original prompt or request body told the model HOW to be consistent, on the number or on the scale it lived on, so it filled the gap with its own defaults — a released-record reference for one, a creative-writing temperature for the other. `ScaleIsAnchoredTests` and the new `TheScoreIsAJudgementNotACreativeTaskTests` pin both so neither drifts back.

---

## The trial had no way back, so a stranger who scored once was gone

The trial asked for nothing — no account, no email — so it had nothing to
come back through, and the coach's real value is the CHANGE between two takes,
which needs a second visit by definition. `apps/economy/retake.py` is one
field under the score: the score and drill emailed now, a reminder to send
the same take again on day 3 and day 7, then nothing — and that schedule is
stated before the button.

- **The claim token is the proof.** Only a scored trial take can arm one,
  which ties the abuse ceiling to the trial's own caps; one inbox takes at
  most `PER_EMAIL_PER_DAY`.
- **No `EMAIL_HOST`, no field.** The console backend is not a send. `ready`
  is published and the screen renders nothing without it; the endpoint
  refuses rather than answering "sent".
- **Days count from the latest take** (`rearm_for`), joining stops it
  (`stop_for_member` — the emails pitch the no-account door), and a failed
  send never advances a stage. The stop link follows `ParcelUnsubscribeView`:
  GET asks, POST stops, plus RFC 8058 one-click headers.
- `send_retake_reminders` rides the hourly habit cron, which now gets the web
  service's SMTP variables. **Set `EMAIL_HOST` (and friends) on the web
  service or none of this is visible** — that is by design, not a bug.
- `RetakeReminder` is the one trial table holding PII, because the visitor
  typed it into a field that says what it is for. It is never joined to
  `FunnelEvent`; the funnel gets `try_email` and the returns arrive as
  `src=retake_d3` / `retake_d7`.

## BodieZ: what a body can do is a filter, and the muscle rating is progress

**Accessibility is stored per exercise and decided in one place.** Every
`BodieZExercise` carries `positions` (where it CAN be done: standing, seated,
lying, kneeling, floor), `needs_arms` and `needs_legs`. `bodiez.accessible()`
is the only rule, and `GET /bodiez/exercises/` returns **every** exercise with
an `accessible` flag for the caller — hidden rows are still served, because an
old session names lifts the member can no longer pick. A member's answers live
in `BodieZAccess` (`seated_or_lying_only`, `arms_ok`, `legs_ok`; three answers,
not one "disability" switch). Unusable legs implies seated/lying: a standing
exercise is a leg exercise whatever muscle it is filed under.

Untagged means **needs everything** (default `standing`, both limbs): a new
exercise nobody classified is hidden from a restricted member rather than
offered to somebody who cannot do it. `test_bodiez_access` fails if a library
row has no known position, or a muscle a seated member can reach has nothing
for them (Glutes had no exercise at all until migration 0177).

**The Thorough rating — a lift, a routine and a muscle, 1 to 10 (Corey's call).**
"Thorough" is the word for every rating here (see COREY_VOICE.txt, PART 8b).
It replaced a progress-only 10/6/3 that said whether a lift went up and nothing
about how completely it was trained. Read off FINISHED sessions in the last 28
days, arithmetic and not a model: **days trained** vs 8 (40%), **working sets a
week** vs a target (35%; 6 for a lift, the bodymap's 10 for a muscle) and, once
a lift has two sessions, **up/held/down against the member's own earlier best**
(25%, dropped and the rest re-weighted before then so a new lift is not marked
down for having no history). `thoroughness()` is the one formula.
- A **lift** is rated from its own sessions; a **muscle** from every session that
  touched it; a **routine** is the mean of its lifts' ratings with a lift never
  logged in the window counting as 1, so a routine half done reads as half done.
  `None`, never 0, when nothing in scope was logged in the window.
- **The substance rule, said out loud:** days and sets are effort and this number
  now includes them. That is a deliberate reversal of the earlier "never from how
  much was done". It is why the label says *thorough* (how completely it is
  trained) and never "good" or "strong", why the caveat is on the same card, and
  why the progress part stays: a muscle hit daily that goes nowhere cannot reach 10.
- Routines carry `coach_rating` / `coach_why` / `coach_exercises` on
  `GET bodiez/routines/`; muscles carry them on `bodymap/` with each lift's own
  `rating`.

Migration 0177 also wired seven clips that were uploaded to `ctkoth/mcz-media`
but pointed at by nothing. Their filenames contain spaces, so `demo_url` is
percent-encoded rather than the file renamed in a repo this one does not own.

## SubstanceZ: frequency is a declaration, and the member's own setting still wins

`apps/economy/substancez.py` owns the substance list, the frequency scale
(`rarely` < `sometimes` < `often` < `daily`) and the cleaner, and serves them at
`GET /api/economy/substancez/` — ProfileZ, the SubstanceZ app and VybeZ read that,
nobody retypes it. Each step carries a plain-language `hint` ("most weeks") so
"often" means one thing. A legacy `yes` (picked before frequency existed) is kept
as `yes` and never rounded into a frequency; unknown substance keys are dropped.

**Every reader goes through `visible_substances(p, viewer, audience)`**, which
applies the adult wall in BOTH directions and the member's VisibilitieZ setting
(`substances` is PRIVATE by default). An adversarial review of the first cut
found five places that skipped one or both, and each was reproduced:

- `card["use_frequency"]` and `use_freq` were added after `redact()` ran, so a
  private declaration's frequency was readable — all eleven keys in one call
  returned the whole row.
- The avoid filter (`substances=` + `substance_max=`) is a frequency oracle:
  stepping `substance_max` up one band at a time reads a declared frequency off
  who appears. It sits inside the adult wall now, a minor's row reads as empty,
  and a hidden declaration reads as undeclared (so being filtered out can never
  tell a searcher someone uses X).
- `_profile_full` added `substances`, `birthday` and `location` AFTER the card
  was redacted, so `GET /members/<username>/` served them to every signed-in
  member, minors included. It redacts the finished card now. This one predates
  frequency; frequency just made what leaked finer.
- The tile counts and the member list disagreed (5 over a list of 4) because
  counts ignored visibility. Counts read through the same helper now.

**Open to members by default (Corey's call).** `visibility.DEFAULTS["substances"]`
is `member`, so the SubstanceZ app and the avoid filter have people in them
without each member having to find a control. It is still adult-only in both
directions whatever the setting says, and a member can narrow it to private or an
audience at any time. **Moving a default is retroactive**: `Profile.visibility`
stores only deviations, so an unset row follows the default, including rows
written when the label said Private. Migration 0188 therefore pins every member
who had ALREADY declared substances and made no visibility choice to `private`
— an explicit override — so nobody's existing declaration opens without them
choosing it. Everyone who declares from now on gets the new default. It is
one-way on purpose: a reverse could not tell its pins from a member's own
choice, and un-pinning someone's private declaration cannot be undone.

**Corey then opened the pinned ones too — migration 0189, and only the provable
pins.** A pin (`["private"]`) is byte-identical to a member choosing Private after
the default moved, so "open everything that is private" would override real
choices. They differ in one place: 0188 wrote its pins with
`save(update_fields=["visibility"])`, which leaves `Profile.updated_at` alone,
while every normal write (the profile PATCH, the profile POST) saves it. So a
`["private"]` row whose `updated_at` is not later than the moment 0188 was applied
(read from `django_migrations`) has not been saved by anybody since the pin and is
provably one; 0189 opens those by removing the override (they follow the default)
and tells each member in-app. Anything saved since is ambiguous and stays private
— the error that cannot be taken back is overriding someone's own decision. It
uses `.update()` so the cutoff is not moved and a re-run finds nothing. With no
0188 timestamp it opens nothing. Pinned members who have since edited their
profile are therefore still private; opening *those* would need either their own
say-so or accepting that some explicit choices get overridden, and is not done.

**Choosing a field's default must REMOVE its stored override.** `clean_visibility`
drops a value equal to the default (the row records choices), and the PATCH merged
what survived — so a field once moved off its default could never come back: the
"Members" button answered 200 and changed nothing. With the default moved and
every earlier declarer pinned to private, that would have been a dead control for
exactly those members. `visibility.merge_visibility` is the writer now (default →
pop the override; junk → no change) and `accounts/views.py` uses it. This bug
predated SubstanceZ and applied to every field.

**Sober by choice is a tile, not a footnote.** `metricz` serves it as a real
option (`key: "sober"`) beside the eleven substances: counted, listed under
`uses=sober`, in `mine`. It is a claim, so it carries no frequency, never
satisfies a frequency filter, is not in the profile editor's substance list, and
follows the `sober` field's own visibility setting (member by default) rather
than `substances`'. A hidden sober member is not counted, as a hidden
substance is not.

Known drift, accepted: rows saved under the old two-step scale keep their
`sometimes`/`often` and now read under the defined scale (see the module docstring
for the cost and the one-line migration if it is ever judged wrong).

**Do not add a card key derived from a profile field without naming it in
`visibility._DERIVED`, and do not add keys to a card after `redact()` runs.** Both
are how the setting quietly does nothing.

### And a migration conflict took the deploy down once

Two sessions each added "the next" migration (two `0178`s). Each was fine alone;
together `migrate` refuses ("Conflicting migrations detected") and the deploy
fails after a green merge. `test_migration_graph` now fails on more than one leaf.
Run `makemigrations --check` after pulling main, before pushing — the fix is
`makemigrations --merge`.

## RoutineZ: where a routine came from never decides whether it can change

`BodieZRoutine.source` (`member` / `coach` / `session` / `trial`) is a LABEL
for the routine list, never a permission — every routine goes through the same
PATCH. A client may only claim `member` or `coach`; `session` is set by
`sessions/<id>/routine/` and `trial` by `create_trial_split_routines`.

- **A logged workout is editable after the fact.** `PUT sessions/<id>/sets/`
  replaces a FINISHED session's sets through `clean_set_rows`, the one
  validator `sessions/past/` also uses. Rows that come back with their `id` keep
  their measured rest; every rewritten weight is marked `converted_from_lb` so
  the pounds fix never converts a number typed in the current unit. Only a
  backfilled workout's date can move — a live one's time was measured.
- **A workout becomes a routine** (`routine_from_session`): one row per lift,
  sets = how many were done, target = the TOP set, never an average.
- **Routine titles are cut to 80** on both writers. SQLite ignored it; a
  whole-body Coach title ran past the column and would have 500'd on Postgres.
- Migration 0190 added 96 everyday lifts the library was missing against Jefit
  (barbell/dumbbell/cable upright row, Arnold press, chin-up, hip thrust…). No
  barbell RDL — 0178 made the one RDL a dumbbell lift. The listing counts moved
  with it; re-run `tools/count_adaptive_exercises.py` before a release.

## Sentence ConnectZ: three kinds that are claims about a person, and a brief that can hold one

The writer gained **resume, cover letter, poem and bio** so it can be a product on its
own (the frontend's `standalone/sentencez/`). Each kind now declares what a screen needs
to say about it — `voice`, `hint`, `style_label`, `invents_nothing` — and the screen
renders it, so a kind added here is usable without a client release.

- **Whose voice is declared, not assumed** (`voice_of`). Lyrics, captions and posts stay
  K-Oth's register; essays the academic one; **everything else is plain**. Putting a
  resume in anybody's house voice makes it not the member's, and the legal kinds were
  already plain for the same reason. The original kinds keep exactly the voice they had
  (`test_the_original_kinds_keep_the_voice_they_had`).
- **A document that claims a history may not invent one** (`NO_INVENTION`, on resume,
  cover letter and bio). A resume is a claim about a person, and a model filling gaps
  with plausible employers and dates produces something that looks finished and is false
  — the substance rule with a job application attached. Anything the member did not say
  becomes a visible `[BRACKETED]` blank, and `FILL_NOTE` on the finished piece says to
  fill them. A poem carries no such rule: nothing in it is a claim.
- **The brief has its own ladder** (`catalog.WRITER_BRIEF_CHARS`: Free 3,000, Premium
  6,000, StatZ unlimited). It was the tier's post limit, 400 characters on Free, and at
  400 a resume is not harder for a Free member, it is impossible — a tier says how
  MUCH, never whether. The brief is material the writer works FROM (a work history, the
  sources an essay must cite), not published text, which is why it is not
  `over_char_limit`'s. It only ever raises what the writer accepted, and what a run can
  cost is still capped by `DAILY_PROMPT_MAX_CENTS`. **A recommendation, Corey's to move:**
  the 3,000/6,000 are judgements, not measurements. StatZ stays unlimited, as ever.
- **The royalty is unchanged and still only fires on an explicit attach** (`UseIn` in
  Music ConnectZ). The standalone has no DistributeZ, CollabZ or BattleZ, so it neither
  asks for nor states one, except a line on lyrics saying the royalty applies if the
  member later takes the piece to the music platform.
- **`SentenceWork.kind` is `varchar(16)`**; `cover_letter` is 12. A longer kind name
  would be invisible on SQLite and a 500 on Postgres.
- **Nothing identifying is sent to Google**: the request body is the prompt (our
  instructions and the member's text) and a temperature. The privacy policy says exactly
  that, and says Google processes it under its own terms — it makes no claim about what
  Google does with it, because nothing here can check one.

## Supersets: the Coach chooses, the member always may

Two lifts done back to back, rest after the pair. **Linking two rows of a
routine by hand is free at every tier** — a superset is an order of work, and a
tier that could say whether somebody may do two exercises in a row would be the
ladder rule's first counter-example. What is gated is the Coach CHOOSING the
partner (`statz_trial.FEATURES["coach_pairing"]`, `POST /bodiez/pair/`), which is
StatZ's, or the free hour's. Same shape as the framed-page widget: a capability
on top of a thing everybody already has, which can switch off again without
taking anything the member made. A routine the Coach already paired stays paired.

`apps/economy/superset.py` offers two pairings and the member picks, because
they are different ideas: **compound + isolation** (one muscle: bench press then
fly) and **push + pull** (opposing muscles: bench press then row). Both are
offered rather than one chosen for them. Compound-then-isolation is the one that
builds a muscle; push-pull is the one that saves time without costing reps, and
which is better depends on whether the member is short of minutes or short of
volume.

Four things hold it:

- **Every fact is declared, never inferred.** `superset_table.TABLE` says, per
  library exercise BY NAME, compound or isolation and push or pull. By name
  because ids differ per database (the library is made by migrations). A lift
  not in it — a member's own custom exercise, cardio, a hold — is never paired,
  and a custom exercise NAMED like a library lift is still not classified by its
  name (`test_a_custom_exercise_named_like_a_library_lift…`). `test_superset`
  fails when a library exercise has no entry, so a lift added by a migration
  without being classified is a red test, not a Coach that quietly ignores it.
- **The partner is always something the member can do.** `bodiez.accessible` is
  the one rule and the equipment they said they own is respected. It adds at most
  one row per lonely lift and says which it added; the client marks it "added by
  the Coach" so a pairing can never silently grow a routine.
- **It is idempotent and leaves hand-made pairs alone.** Running it twice changes
  nothing the second time; a pair somebody made is not re-made, and a stale label
  is dropped rather than guessed at. Routine rows are raw JSON, so the pairing is
  a `group` label (A, B, C…) on two ADJACENT rows; `valid_groups` is the one
  validator and `src/supersets.js` mirrors it so the two cannot disagree about
  what a pair is.
- **A sample never changes the tier.** `has_statz` is the real tier; the free hour
  only widens what `feature_tier` answers while it runs.

**Rest alerts are client-only and gated by the same state.** Nothing about them
costs a resource, so there is no server meter; `statz_trial.state` is what the
screen reads. The sample ending locks the control and says so with a notification
if the member has already let the site notify them (it never asks for permission
itself — the rest-alerts control does, because that is when someone has a reason
to say yes). **A locked phone pauses a web page and nothing a page can do prevents
that.** Keeping the screen on keeps the rest clock running and the notification
covers switching to another app; the copy says exactly that rather than promising
a timer that survives a pocket.

## The portfolio: links ladder, and a ceiling that is said rather than applied

A member's `links` are their portfolio — the tracks, videos, pages and shops that say who
they are — and they are the one thing on a profile a visitor came for. They had a flat
**silent 50**: `clean_profile_field` cut the list there and answered 200, so somebody who
pasted 60 saw a clean save and ten of them gone. `catalog.TIER_LIMITS["profile_links"]`
is the ladder now (**Free 25, Premium 100, StatZ 300**) and it is **a recommendation,
Corey's to move**.

- **Generous at the bottom on purpose.** The work is the reason anybody visits a profile,
  and a tier that rationed it would be rationing the thing the platform exists to show.
  It ladders because rows are not free — the list rides the full-profile payload and the
  public page (never the member CARD, which carries no links) — not because links are a
  luxury. A tier says how MUCH, never whether.
- **Said, not applied.** `ProfileView.post` judges the list BEFORE writing anything and
  refuses with the number (`links_limit`, `links_count`) and a sentence the screen shows
  unreworded — like the bio, so one over-long list cannot lose the rest of the edit.
- **Nobody loses a link when the number moves** (`links_over_cap`). The ceiling is the
  tier's or what the member already holds, whichever is MORE: somebody holding 50 on a tier
  that now says 25 keeps all 50, can reorder and remove them, and cannot add until they are
  under. A list no longer than the stored one can never be refused.
- **The cleaner's own bound is not a tier** (`LINKS_CEILING`, 1000): it only limits the work
  one request can ask of `clean_link`. What a member may HOLD is `links_over_cap`.
- **The owner is told the ceiling before adding anything**: `links_limit` (what they may
  hold now) and `links_tier_cap` (their tier's own number) ride their own profile payload and
  nobody else's. The ladder for every tier is already in `tiers` from `/limits/`, so a screen
  can say what the next tier holds without typing it.
- `POST /api/economy/profile/` is the only writer of a profile's links. **Nothing mounted in
  the frontend could call it** until `PortfolioLinks.jsx` — the feature had a reader on three
  screens (card, public profile, widget board) and no way to make a link.

## Plays on Music ConnectZ from the embedded SoundCloud player

`apps/economy/embedplays.py`, `EmbedPlay` (migration 0195, additive). A play is a
member who listened 30 s (`EMBED_PLAY_MIN_SECONDS`) through heartbeats clamped to
the wall clock (as `record_listen`), once per member per post per day; the author,
a second account in the same browser (`anon_id`), more than 5 counted plays on a
post from one address a day, and non-SoundCloud embed indexes do not count. Pays
nothing. Served as `mcz_plays` on a post, batched in one query and skipped when no
post in the batch frames SoundCloud. **No rebuild command**: the count is derived
from `counted` rows, not a stored counter, so it cannot drift. Labelled "on Music
ConnectZ" and never mixed with SoundCloud's own number. Never run against a real
SoundCloud widget (no access from CI).


## Credits buy outcomes, and the list is enforced (Corey's rule)

**Every credit spent buys something tangible, shareable, understandable, lucrative,
braggable or learnable.** `apps/economy/credit_outcomes.py` declares, per spending
module: the resource, what it buys in one sentence, which of the six outcomes it
delivers, where the thing can be USED (`lands_in`), and either a `free_way` or an
honest `no_free_way`. `test_credit_outcomes` walks the source, finds every module that
calls a spend primitive (`charge_ai_usage`, `_bill`, `spend_spinaz`,
`charge_skill_energy`, `_spend_energy_up_to`, or an energy decrement) and fails if one
is undeclared — its first run found `collab.py` spending Energy on starting a deal and
saying nothing — and fails when a declaration outlives the code. `GET
/api/economy/creditz/` publishes the list.

A spend also points at what it bought: `Transaction.ref` ("take:12", "sentence:4"),
set with `link_spend` AFTER the thing exists (nothing is charged for an empty answer,
so the ledger row is written first). `logz_outcomes.outcomes_for` resolves a page of
rows to the rating, the report and the file in two queries, filtered by owner so a
forged ref reads as nothing. Only the coach and Sentence ConnectZ link so far; the
other spenders are declared but their rows carry no `ref` yet.

**The file is not always kept, and the ledger says so.** A take recorded in the coach is
scored and not stored; the recording exists only when it came from a post or journal
entry, or the member posted it. Keeping every take would change what the privacy policy
promises and what storage costs — the owner's decision, not a default.

## Coach history is where the member's work becomes shareable

- `TakeScore.read` keeps the coach's read (verdict, strengths, fixes, practice, exact
  score, HookZ, FeelZ) — never the lyrics it transcribed. `overall` is the number the
  member was SHOWN; it used to be the plain mean of the dimensions, so the history
  disagreed with the score they had just been given.
- `takescorez.exports_for` is the one list of doors out of a past take: share, post,
  message, journal, drills, breath, the lyric writers, a battle — each with what it does
  and what it costs before it is pressed. `coaching()` is the board: wins, strengths,
  alerts and problem areas, worded by the server, each problem with its free way and,
  for a lyric dimension, the paid writer.
- **Lyric fixers** (`sentencez.FIXERS`): punchlines, hooks, rhymes, imagery, story beats,
  fresh angles — five suggestions per run, each with technique and why, ranked by what
  members rate highest only once a technique has `MIN_RATINGS_TO_RANK` ratings (else in
  the writer's order, and it says so). Every one is a saved `SentenceWork`, so the
  existing K-Oth royalty applies to the part a member keeps. HookZ and FeelZ count in
  the overall, strength-weighted; both are absent, never 0, when a take has none.
- **Shares are minted server-side from stored data** (`share_take`, `ShareWinView`) and
  never from a request; the card shows the number the member saw (`score_exact`), says
  who made it only if they DECLARED it (`ScoreShareHumanView`), and gives the reasons
  behind the score. `ScoreShare.views` counts opens of the public page.
- `breathz.py` is free breath training: patterns, minimums and the daily XP cap are the
  server's; sessions earn XP for turning up and never move a rating (a timer cannot
  measure a breath — the coach's Breath score is the measure, read back beside it).
- `whyz.py` says why a member is here with THEIR proof, and never a number it cannot back.

## Age groups, keeping takes, challenges and listener reasons

- **No adult-to-minor contact** (`models.may_contact`, symmetric): DMs, calls and member
  search stay within an age group. The LessonZ comments already stated this as "the ScoutZ
  rule" and nothing enforced it for DMs or search until now. Unknown ages count as adults
  (matching `is_minor`). **Collabs and battles across ages are still open** — the stated
  policy in `adult_only_reason` ("posting, collabs, BattleZ… stay open") — and that, plus
  any romantic or "dating" surface for under-18s, is the owner's call; the recommendation is
  that InfernoZ (listed as "projects & dating", not built) and VybeZ's dating filters are 18+.
- **Keep this take** (`takekeep.py`): opt-in per take (`keep=1`), stored as an ordinary
  Upload under the existing quota, never charged, and a take that does not fit is still
  scored with `kept_note` saying why. The privacy policy changed with it.
- **The weekly challenge** (`challengez.py`) is derived from the ISO week alone — one prompt
  per coach for everybody — and a shared card carries the week only when the take answered
  it. **Listener reasons** (`ItemRating.reason`) reach only the performer
  (`listener_reasons`), kept apart from `listeners_for`, which feeds the coach's prompt.

## A SpinaZ is worth one cent, and what a visit pays follows from that

Corey's valuation: **1 🍥 = 1¢.** Every minting constant reads as cash from that, which is
the only way "limit the earn so it doesn't inflate" has a number to check. A members-only
(restricted) post paid its author **300 🍥 per engaged member** — $3.00 for somebody staying
five seconds, and at `JOIN_REWARD_DAILY_CAP_PER_AUTHOR` (500) that is up to $1,500 a day
from one account. `RESTRICTED_JOIN_REWARD_SPINAZ` is **150** now (Corey's two options were
300 and 150; this is the recommendation, reversible in one line). **Not changed, and the
bigger exposure:** `JOIN_MIN_ACTIVE_SECONDS` is 5 and the per-author cap is 500, so the
worst case is still $750 a day per author. A recommendation, Corey's to move: a per-author
cap near 40 and a longer minimum stay.

## A past take writes its own promo post, and the brief is the server's

`takescorez.TakePromoView` (`/api/<key>/take/<id>/promo/`; GET = price, POST = run) mints the
take's public share link, then runs the SAME writer Sentence ConnectZ uses (`sentencez.write_piece`,
extracted from `SentenceView.post` so there is one run, one price, one "a failed run is not
charged") with a brief built by `promo_topic` from what the coach stored — score as shown,
verdict, two strengths, the link. Nothing in the request reaches the brief. The writer is told
to use only those facts and to say "human-made, AI-scored" only when the member declared it on
the share. The door (`promopost`, second after share) carries its price like every paid door;
standalone shells never offer it (no writer in their listing or data-safety answers).

## ViewZ results, and the audit of everything StatZ is the difference for

`viewz.post_results` / `ViewPostResultsView` (`/views/post/<id>/`), `ViewMineView` (`/views/mine/`):
numbers for everybody (views, people, stayed %, came-back %, live now, what visitors did), by-day
history, and — only `has_statz` — each viewer as a track with one clip per visit (start, end,
seconds). `stayed` = visits of at least `MIN_VIEW_SECONDS`; `came back` = people with more than one
separate stretch; neither is video retention and none is blended into a score. Share-link opens are
`ScoreShare.views`; who opened is not recorded, so none is claimed. A promo post's LogZ row carries
`results` (opens, read at request time).

**`statz_trial.DRIVERS` is the audit**: every StatZ difference, `sampled` or not, with `why_not` for the
ones the free hour cannot honestly switch off (a saved voice, a cloned voice, a code sandbox, a
visibility setting other members see, tier limits). `test_statz_drivers` walks the source: a module that
calls `has_statz`/`feature_tier` and is not named fails, and the sampled rows must be exactly `FEATURES`.
The state also publishes `also_in_statz` and `warn_at_seconds` (600, 60) for the screen.

## Takes leave as files, and a take points at where its results are

`GET /api/<key>/take/<id>/download/?format=txt|json` and `/api/<key>/takes/export/?format=csv|json`
answer `{filename, content_type, text}` (the screen makes the file, because a plain link cannot
carry the login header). Own takes only; a take with no stored read says so rather than inventing
one; an unmeasured dimension is a blank cell, never 0; a CSV cell that starts like a formula
(`= + - @`) is made a literal because a verdict is model text. `progress(limit=)` lists ten by
default and `?takes=all` (capped at `ALL_TAKES_CAP`) lists the rest — the history used to stop at
ten with no sign of the others.

The doors out of a take, audited (`exports_for`): share, promo post, **Instagram caption** (same
server-built brief, kind `caption`), draft in PostZ, message, journal, drills, breath training, the
lyric fixers for weak dimensions, enter a battle (post-sourced takes), **see how its link is doing**
(ViewZ, once a link exists) and **download**. Not offered, on purpose: improving the member's own
WORDS in Sentence ConnectZ from a take — the coach never stores what it transcribed, so there is
nothing honest to send; the fixers write new lines for the weak dimension instead.

ViewZ post results also carry `sources` and `devices` (counts for everybody; "direct" is a visit with
no `?src=`) and **ActionZ** (`action_log`, StatZ): every rating, comment, like, share, members-only
join and message from the post, newest first, with `via_page` (did they also open the post's page).
Link opens still have no per-source split — `ScoreShare.views` is one counter, and recording a
source per open would be a new table.

## The StatZ sample: a first hour, then fifteen minutes every 24 hours

The one-time hour was the whole of what a member could learn about StatZ, and it could burn before
there was anything to look at (ViewZ is worth checking again after a post is promoted). The FIRST
sample ever is `FIRST_TRIAL_MINUTES` (60); every later one is `TRIAL_MINUTES` (15), once every
`TRIAL_COOLDOWN_HOURS` (24) measured from the last window's START (the clock is UTC, and a calendar day
would hand a New York member a fresh window at 7pm). No schema change: the one `StatzTrial` row is
re-armed with a conditional update so two presses at once cannot open two windows. A press while a
window runs returns that window (200, not a second one). `state()` publishes `minutes`,
`last_minutes`, `first`, `next_at` and `seconds_until_next`. Nothing the sample unlocks changes: it
only widens `has_statz`/`feature_tier` while a window runs, and the `DRIVERS` audit's reasons for what
it does not cover still hold. **A recommendation, Corey's to move:** hour-then-15 rather than either
alone; the cooldown is one constant.

`ViewMineView` also carries ActionZ across all of a member's posts (`action_counts` for everybody,
`action_log` for StatZ — fetched once for the whole list, tested to cost the same queries for one post
or many) and `sources`/`devices` over every post.

## Dating is 18+, collabs are open at any age (Corey's calls)

`MembersView` refuses a minor when the request names the VybeZ surface (`?vybez=1`) — 403 with
`VYBEZ_MINOR_REASON`. The gate is on the SURFACE, not the search, because that endpoint is also how
CollabZ, BattleZ, VenueZ and MessageZ pick people. Orientation (`attracted_to`, `asexual`) was already
adult-only both ways. Collabs and battles across ages were an open question and are now decided: open
(`test_a_minor_and_an_adult_can_make_a_collab_together`). What is NOT opened: a direct message or call
between an adult and a minor (`may_contact`) — the recommendation was and is that a collab does not need
one. A close-in-age exception ("teens may date adults within 5 years") was considered and rejected: it is
a rule about when an act is a crime, not a safety rule for introducing strangers, and ages here are
self-entered. Teens may still see each other as friends and collaborators; a ±2-year band for minors
(so a 13 and a 17 cannot reach each other) was recommended and is **not built**. InfernoZ's dating half,
when it exists, refuses minors the same way.

## Cross-age messages inside a collab: consent is the acceptance, not the naming

Corey: adults and minors may message each other inside a collab, and call when the adult is on
StatZ. `models.may_message` / `may_call` are `may_contact` plus `collab_link(a, b)`: a shared deal
that is not released/refunded/cancelled and that **both have accepted**.

- **Being named on a deal is not consent.** `CollabDealsView.post` lets the starter name any member,
  so "both are on a collab" would let an adult open a channel to a minor by creating a deal. The
  starter has accepted by starting (`accepted_at` stamped on their entry); everyone else presses
  accept (`POST /collab/<id>/accept/ {accept}`), and may withdraw at any time. The participant list
  is rebuilt from a whitelist on create, so a request cannot carry someone else's `accepted_at`
  (`test_a_starter_cannot_forge_somebody_elses_acceptance`). The accept view locks the row: fund,
  deliver and release rewrite the same JSON column and a stale save would un-fund a stake.
- **Blocks still win**, checked before the age rule. The channel closes with the work.
- **Calls need BOTH members on paid StatZ** (tier statz/debug — the free hour does not count,
  anybody can start it), on top of the accepted collab. Corey's call; first read as "the adult on
  StatZ", corrected to both. Reversible in `may_call`. A lapse closes the call door again.
- Everything else stays age-grouped: member search, direct messages with no shared collab, calls.
  VybeZ (finding a date) is 18+ regardless.

## 18+ ID checks end in a stated success or failure

`IdentityCheck` is one row per Stripe Identity session: status (`verified`, `failed`, `under_18`,
`unreadable`, `canceled`, or open) and the reason (Stripe's code, worded by `identity.REASONS`).
The old flow set a boolean on a pass and did NOTHING on any other ending, so a member who scanned
three times could not tell whether it worked — a failed scan, a genuine ID that proved under 18 and a
DOB that could not be read back were all silent.

- `GET /identity/` serves `last` as `{result: success|failure|pending, detail, reason}`, plus
  `attempts_left_today` and `can_start`. Success is never worded as pending, failure always names why.
- **After success a new scan is refused** (`already: true`, no Stripe session created — a check is
  paid for). After `MAX_FAILED_PER_DAY` (3) non-passes in 24h it is refused with the last reason.
  An open session is reused for 30 minutes rather than duplicated.
- **The webhook is not the only route**: GET and POST first retrieve any open session from Stripe
  (`refresh`), so a deploy without the identity events subscribed still reports. If members say the
  badge never appears, check the endpoint is subscribed to `identity.verification_session.*`.
- A final result is never overwritten by a late event, and a session only applies to the row's own
  member (`metadata.user_id` must match the row).

## Hashtags in the writer: asked for, ordered, and held to

`sentencez.clean_hashtags` reads the member's number (None = did not say, 0..`HASHTAG_MAX` 30; junk is
"did not say", never a refusal) for the `post` and `caption` kinds, on the screen's POST and on a take's
promo POST. The prompt asks for exactly N, together on the last line, most to least relevant, and no
filler tags. **The model is not trusted to count:** `fit_hashtags` trims the TRAILING all-hashtag block to
the first N (the most relevant, by the prompt's own ordering); a tag inside a sentence is part of the
sentence and stays. Fewer than asked is reported as `hashtags: {asked, got}`, never padded. The caption
kind's built-in "5-10 hashtags" yields to the number so the prompt never holds two instructions.

## Ratings move royalties by (median − 5) × 10%, and the AI coach can count — if the member says so

`royaltyfactor.py`. Corey's formula: royalties change by the median rating minus 5, times 10% — each
point above 5 adds 10%, each below takes 10% off. **5 pays the base rate, 10 pays 150%, 1 pays 60%**
(`PIVOT`, `STEP`; written as ".10%" in the instruction and read as 10% per point, because 0.10% would
move a payout by half a percent at most and could not make "bad ratings get less" true — reversible in
one constant). Never zero, and neutral until `MIN_RATERS` (5) people OUTSIDE the credits have rated: an
unrated track is not a badly-rated one.

1. **The track:** the median of outside ratings scales what the post earns per play
   (`accrue_playlist_royalties_for_date`). Said before the payout: `GET /royalty/ratings/` serves the rule
   and each post's factor and why; RoyaltieZ shows it.
2. **The skills:** each credited person's share is scaled by the same formula applied to their rating in
   the skill they brought (`skill_haircut`, from `skills_for_post`; the name predates the formula — it is a
   bonus above 5), averaged over those skills so bringing five does not multiply one bad one five times.
   **Never twice:** a post from a deal whose pot was already re-cut by contribution rating
   (`basis == "rating"`) has had each person's rating applied once already. Nothing is redistributed — a
   factor below 1 is money not paid, not money moved to someone else.

**This formula pays a bonus, so rating is now worth gaming.** The guards are the design: only outside
raters count, the median (one rater cannot move it), five of them before it moves anything, and a rating
needs the listen the rating endpoint already requires. Worst case is +50% on a track whose five-plus
outside raters all gave it a 10 — which is exactly the ring a rating-for-rating exchange would build, so
watch `rating_adjusted_posts` in the accrual summary. An earlier draft had no bonus above 7 for that reason;
Corey's formula has one and this is the cost of it.

**The AI coach as a skill voice is OPT-IN** (`Profile.coach_counts_for_skillz`, off by default,
`POST /skillz-coach/ {enabled}`). On, the median of the member's last `COACH_WINDOW` (10) takes for the
matching instrument (`COACH_SKILLS` maps persona-skill names to coaches — one list, extend it there)
joins their listener ratings as `COACH_VOTES` (2) votes, only once there are `MIN_COACH_TAKES` (3) takes
behind it so one lucky take cannot carry it. **It cuts both ways and the note says so before the toggle
is pressed** — a weak run lowers the rating as surely as a strong one raises it. Listener ratings stay
the majority. `ratez.skills_of` shows `coach` detail on a blended rating so a number is never
unexplained. `skill_rating_median` itself is untouched (it is called per card; the blend costs a
profile read, so it lives in the royalty and own-skills paths only).

Known gap, Corey's to decide: a post with credited contributors and **no** deal is split in equal
shares, then each share takes its skill haircut — so a weak skill earns less but the money is not moved
to the stronger one.

## Lilith's call-to-action routines: Lilith ticks them, the member cannot

**A routine or task can name a VERIFIED action** (`action` + `goal`; `lilith_actions.py`). Lilith keeps
it herself, from rows the platform already writes when the thing really happens — a `TakeScore`, a
`Post`, a `Message`, an `ItemRating`, a `BodieZSession`, a freestyle `Post`, a `BattleEntry` — and the
member has no button for it (`409` from the old tick endpoints, with "2 of 3 so far"). A typed tick is
unverified; a row is a performance that happened. That is what makes the streak the "you cannot backdate
a habit" claim made literal: only rows created AFTER the routine existed count (`sweep_routine`).

- **The audit** is the catalogue: ~40 actions (every coach's scored takes, drills, practice sessions,
  breathing, posts, freestyle posts, journal entries, Sentence ConnectZ pieces, instrumentals, videos,
  mixes, releases, playlists, uploads, messages, ratings, comments, shares, score cards, follows, invites,
  collabs, battles, freestyle/cypher battles, lesson bookings and offers, workouts). `test_lilith_cta`
  reads every one against a fresh user, so a renamed field is a red test, not a routine that never ticks.
  NOT verifiable, on purpose: profile edits (`updated_at` moves for reasons that aren't the member's work),
  listening/reading (a tab left open), and anything like "was kind" — those stay ordinary self tasks.
- **Cadence.** `LilithRoutine.cadence` = daily | weekly | monthly; a streak counts PERIODS (days, ISO weeks
  Mon–Sun, calendar months) and keeping twice in one period is one keep. Rungs per cadence pay the same
  20 / 50 / 150 🍥 (+⚡): daily 7/30/100, weekly 4/12/26, monthly 3/6/12 — fewer ticks to farm and longer
  real time to earn, which is the point.
- **Catch-up.** The sweep walks the periods since the last keep, so a board not opened for a week does
  not break a run the member actually kept. It runs on the board read (a write on a read: there is no
  cron, and it is idempotent).
- **A milestone is once for life per starter/title, not per row.** `keep_routine` checks a stable ledger ref
  (`ms:<template-or-title-hash>:<cadence>:<rung>`) — before this, deleting and re-making a routine re-earned
  the rung. Custom routines are keyed by a hash of the title, so renaming is the only way round it (known,
  small: 20 🍥 per 7 real days per routine, capped by the tier's routine ceiling).
- **Starters** (`lilith_starters.py`) are names + descriptions + the control they open + the cadence, served
  in the board and added by `POST /lilith/starters/ {kind, key}`: the content is the SERVER'S, a request
  cannot set `action` or `app_key` (a task's `source=platform` decides what it pays). Only
  `INSTRUMENT_AWARE` starters take the coach the member names. One "record a take" task and one daily
  routine are GENERATED per coach (`take_<app>`, `daily_<app>`), so a rapper's streak is RapZ takes and a
  SingZ take cannot keep it. Rap pack: Off the Top (freestyle post, weekly), Sixteen on Paper (Sentence
  ConnectZ, weekly), Cypher Night (freestyle/cypher battle, monthly).
- **Suggestions** (`lilith_suggest.py`) rank from three honest signals and say WHY in a sentence: the
  persona (what they declared), the instrument (their scored takes, else their declared skills through the
  role table), and the records (a habit waiting to be a streak at 3+ in 14 days; a gap — takes but no
  posts, posts but no ratings, ratings but no messages). It only suggests; nothing is added until tapped.
  Counts are cached 10 minutes per member.

## Roles next to a persona: what a member's skills say they ARE

`personaz.artist_roles` / `role_pairs`: an Independent Artist is shown as "Independent Artist · 🎤 Rapper,
🎶 Singer, 🎸 Guitarist"; a Designer as "· 🖌️ Illustrator, 🎯 UI/UX Designer"; the same for videographers,
producers, mix engineers, ghost writers, developers, actors, dancers, mimes, directors, managers and A&R
scouts. DECLARED skills only (never inferred from takes or ratings), derived on READ by `personas_of` and
dropped by `clean_persona` on any write, so a stale copy cannot be stored. A stint is stored under its key or
its label, so a key matches as a whole run of words and the LONGEST key wins ("bass_guitar" is a Bassist
although "bass", the voice, is inside it; "trapeze" is not a Rapper). `ROLE_COACH` maps a role to its AI
coach, which Lilith reads to point a rapper at RapZ. Rated skills are deliberately not used: reading them
would put a query on every member card, and `personas_of` costs none.

## LookZMaxZ: sectors for adults, server arithmetic, and a shop no model can write into

`apps/economy/lookmaxz.py` + `lookmaxz_view.py` (`/api/economy/lookmaxz/`, `.../shop/`, `.../markets/`) extend
AttractivenessZ and inherit all of its lines: **18+ verified (Stripe Identity), self-attested photo, presentation never
identity, nothing stored.** The adult wall covers the free parts too (shop, body, markets) — the framing is the risk, not
the price.

- **Sectors:** face (hair, facial hair, brows — what a barber can change, never face shape), skin, teeth (never alignment),
  styling, and **body, which is read from BodieZ progress and never from a photo.** A body shape is the clearest trait no
  one can change by Tuesday; scoring one from a picture is how a looks app becomes an eating-disorder app.
- **The model scores factors; the server does the arithmetic.** Sector = mean of scored factors, overall = mean of the
  asked-for photo sectors, photo quality shown apart. A factor the photo does not show is None, never guessed. Undeclared
  sectors/factors from the model are dropped (`clean_reply`).
- **`FACTORS` is what/why/how per factor, one place.** The prompt is built from `what`, the screen shows all three before a
  photo, and `test_lookmaxz` fails if a declared factor has no entry or an entry has no factor.
- **Nothing a model wrote reaches a link.** `PRODUCTS` is the server's catalogue, chosen by which factor scored under
  `WORK_BELOW`; categories not brands; every sector states when to see a professional. No affiliate tag, said on screen.
- **The tier buys WHERE you shop, never whether.** Everybody: Amazon, eBay, Walmart, in that order. StatZ (real tier, not
  the sample — `statz_trial.DRIVERS` `shop_markets`, `sampled: False`) saves their own list in `LookmaxPrefs`, the only
  thing stored. Templates: https, exactly one `{q}`, public host (no IP literal, localhost, credentials), capped at 8,
  repaired on read, query percent-encoded. A lapse keeps the saved list and serves the defaults.
- **Billing:** one price per reading, billed only after a readable result; unreadable or nothing-scorable is free.
- **Found on the way:** `vocalcoach.gemini_mime` is the audio/video list and has never held an image, so AttractivenessZ
  answered "can't read image/jpeg" to every real photo — its tests mock the rating, which is why nothing noticed.
  `attractivenessz.gemini_image_mime` is the fix; both modules use it. Like the coach and TTS transports, **the photo path
  has never run against Google** (CI has no key).

## Lilith: moving, Trash and recommendations

`POST /lilith/move/` moves a task between buckets or into/out of daily/weekly/monthly routines, or to Trash and back.
Finished tasks are immovable and a moved entry never mints (task XP once per task, milestone rungs once per starter via the
stable `ms:` ref); a routine changing cadence restarts its run and the response says so. Trash is `trashed_at`, excluded from
ceilings, sweeps and ticks, and purged after 30 days on a board read. Recommendations come from `lilith_suggest.signals`
(profile completeness, personas, ever-posted/shared/collabbed, collabs waiting, last take) — computed from the member's own
state at request time, cached ten minutes, each with a `because` so none is unexplained.

## Inclusive principles, exclusive standards — set by the member (Corey's principle)

Freedom of choice, discourage bureaucracy: the platform is inclusive, the bar is the member's. Every metric that can
be a range already is (`gates.py`: rating, price, attractiveness, age, km) and the member search, gated deals,
battles, lessons, venues and message reach all evaluate them from one spec. **A range is exclusive, and a member's
own switch beats it**: `Membership.attractiveness_public` was honoured by the rating endpoint only, so the community
attractiveness number still rode every search card and could be read off by stepping a range one band at a time.
`models.attractiveness_shown_medians` is the one reader the gate, the card and the rating response use now, and a
hidden score is "no value" — which an active range treats as out. Do not put an approval queue in front of something
a member can set for themselves. The AI LookZMaxZ readings are NOT a filterable metric and never will be: nothing
about them is stored (so there is nothing to filter), and a self-attested photo is not proof enough to rank people on.

## Posting a take, and what a low FeelZ is told to do

`takescorez.TakePostView` (`/api/<key>/take/<id>/post/`) makes a PostZ post from one of the member's own takes through
`postz.create_post` — one creation path, so the daily submission cap, sanitising and zodiac hooks are the composer's.
The score and read come from the stored take and the share token (never from a body); the recording is the kept upload by
its stable address. **Playable by link means kept**: an unkept take posts without media and `GET` says so first. The
member ticks score / feedback / recording separately; score + feedback together carry the coach's read card, either alone
goes as plain text because the card cannot show half of itself. Note `VISIBILITIES` is `("", "members", "private")` —
public is the EMPTY string, and "public" is refused.

**HookZ and FeelZ on the row** (`extras_of`): labelled, with the reason, the emotion, and `counted` — whether each was
inside the overall the member was shown (stored on the read as `hook_counted` / `feelz_counted`; older takes carry
neither and say nothing). Both are strength-weighted into the overall like any dimension, never a 0 when unjudged.
**`feelz_tips`** exist only for a FeelZ under `FEELZ_TIPS_BELOW` (7) whatever the model sent — a 9 with a to-do list is a score
contradicting itself — each `{kind, label, what, why, how}` with kinds server-owned (`FEELZ_TIP_KINDS`; an invented kind
becomes delivery). **`mix_tips`** are separate and not score-gated: a vocal can be buried on a take whose overall is fine.
They are `{helps: clarity|feelz|both, what, why, how}`, about the mix and never the performance, and the prompt says to
return none when the vocal sits well. Mic/room tips say what kind of change, never a brand.

## A shared rating carries every metric, and a history share is as full as a live one

An audit of what the coach produces against what a share carried found the history thinner than the live result: a take's stored
read kept the verdict, strengths, fixes and a few numbers, but not where the member is (`now`), what they aim at (`goal`), the style
read, the song score and its reason, the next drill, or HookZ / FeelZ with their reasons — so a card or post made from the history
said less than the screen the member had just seen. `read_of` keeps them now, `share_payload` passes them with `extras` (HookZ /
FeelZ rows, cleaned once by `extras_of`) and `mix_tips`, and `scoreshare.clean_extras` / `clean_mix` re-clean on the way OUT to a
stranger's page (whitelisted keys, caps) because a stored row is read for years. `coachshare._KEEP` / `read_view` carry the same to a
post's read card, and `render_card` draws "HookZ 8 · FeelZ 4 · longing" — numbers and emotion only; the tips stay on the page.
**An older share link is filled in, never replaced** (`share_take`): only keys it lacks are added, so a declaration (`human`), a recap or
a challenge already on it survives. Cards are cached a day, so a refilled one reaches the picture on the next day's fetch.
**Not shared, on purpose:** the take's file (only a post can carry a kept recording), the transcribed lyrics (never stored), and the
member's listener reasons (the performer's alone).

## Inspiration: your take against a song you want to sound like

`matchref.py`, `POST /api/<key>/match/` on every coach (named Inspiration, first for RapZ). Two files: the take and a
reference; the reference is never kept (no Upload row, Files API copy deleted) and nothing is saved as the member's — no
TakeScore, share, XP or rating, because a gap to someone's record is not a measurement of the member. `closeness` is how
near the SOUND is, never good/bad. EQ regions are server-owned (`EQ_REGIONS`) and said to be heard, not measured. Lyrics
come back as a DIRECTION for Sentence ConnectZ, never the reference's words (prompt forbids quoting). One standard AI
price, stated on GET before the button; a failed run is not charged. Never run against Google (CI has no key).

## Interests, brands and strengths: intuition is allowed, as a suggestion with its reason

Corey asked for VoiceZ to pick up the brands and interests a member mentions in
speech, and for the app to be intuitive about what they imply — a designer who
draws is probably dexterous, a designer who does song covers is probably creative
and observant. The obvious version breaks the substance rule in its first line:
a trait derived from a hobby is "a number derived from activity and presented as a
fact about a person", which `personaz` and PersonalitieZ both refuse by name. So
the intuition is kept and the claim is not:

- **`interestz_table.RULES` IS the intuition.** Every suggestion is one row — who,
  which interests, which trait, and the reason in a sentence. It is read before the
  member decides and can be argued with and changed by a person. No model guesses a
  trait from a pile of interests; that would be a conclusion with no reason behind it.
- **A strength is a suggestion until the member says "that's me".** Then it is theirs
  (`declared_strengths` on the persona, a closed list), shown as declared, and
  **nothing reads it as a measurement** — no rating, skill level, median, price or
  search rank. `test_interestz` fails if a second module reads `declared_*`.
- **The scan is a closed list.** Words are matched against `INTERESTS` and `BRANDS`,
  so sensitive territory (health, faith, politics, orientation) cannot be picked out
  of a transcript: the list can only find what is on it.
- **Speech arrives as text.** The keyboard's voice-clip door (`keyz/transcribe/`,
  already metered and priced before the mic) turns a clip into words; `interestz/scan/`
  reads those words and writes nothing. The transcript is not stored — only what the
  member picks. That adds no audio path and nothing new to disclose about speech.
- **A brand is a thing a member likes.** It unlocks nothing, is shared with nobody and
  is not an ad-targeting profile. If that ever changes, the privacy policy changes first.

CharacterZ has hobbies too (`Character.hobbies`, migration 0223, a JSON list). They are
short tags bounded like a persona's interests (`characterz.clean_hobbies`, 20 of 40
characters, repeats folded), declared by the member, and `prompt_block` hands them to the
dialogue writer as flavour inside the same defanged data block as the rest of the
character — a hobby cannot close the block. A character gets the interests picker only:
no brands and no strengths, which are claims about a real member's own work. The persona
picker lives in a persona's bio and interests editor.

## A finished session says what changed since the last one

`session_summary` carries `vs_last` (`bodiez._vs_last`): the same totals for the member's previous
finished session, the signed change in volume (with a percent), sets, reps and — only when BOTH lengths
were measured — duration, and per exercise `top_delta_kg` / `volume_delta_kg` on its row of `exercises`.
Arithmetic over logged sets and nothing else.

- **Like with like.** A routine is compared with the last run of the SAME routine (`basis: "routine"`);
  a routine with no earlier run, or an ad-hoc session, with the last session that had anything logged
  (`basis: "last"`). Push day against a leg day would be noise, and the screen says which it did.
- **None, never a made-up number.** No earlier session → `vs_last` is None ("starting mark"). Last
  time's volume 0 (all bodyweight) → no percent. A lift done last time and skipped now is named in
  `not_repeated`; one new this time has no `vs_last` row. A workout typed in afterwards has no
  duration to compare.
- **A drop is not "worse".** Lighter can be a deload; the screen shows direction and does not colour it
  as a failure. Only a RECORD (heaviest, most reps at a weight, biggest session) gets the trophy, and
  those are unchanged — they compare with every earlier session, not only the last.

## Inspiration: either side can already be on the platform

`matchref.MatchReferenceView` takes, per side, a file OR an id: the take as `take_post_id` /
`take_upload_id` / `take_journal_id`, the reference as `reference_post_id` / `reference_upload_id`. They
go through the coach's own `_take_from_post` / `_take_from_upload` / `_take_from_journal` (via `_Fields`,
which presents the prefixed fields as the plain ones), so view rights (`can_view_post`), own-uploads-only,
size-from-the-row and the "recording is gone" 410 are the coach's rules and not a second copy of them.

- **The reference can be ANY post the member may view** — that is the "famous example". It is read for
  the comparison and never kept (no `Upload` row, Files API copy deleted), nothing is written on the
  post (`_save_to_post` is not called) and its author is not notified. The response names the post and
  its author in `sources`; nothing else about it is sent.
- **A post on either side costs `coach_post_energy` ⚡, once.** Same figure as coaching a post, served
  on GET (`post_energy_cost`, `post_note`) so the screen states it before the button, checked BEFORE the
  model runs (402 with the shortfall), spent only after a usable result. Files, FileZ uploads and
  journal entries cost no ⚡. **A recommendation, Corey's to move:** without it Inspiration would be a
  ⚡-free way to put other people's posts in front of a model, which the post-coach deliberately is not.
  Every AI run still takes its usual small ⚡ (`_take_ai_energy`) on top.
- A journal entry is take-only: a diary page is not "another artist's finished record". The same post
  on both sides is a 400.
- **Never run against Google** (CI has no key), like the rest of the coach's transport.

### Inspiration links: YouTube can be heard, Spotify and SoundCloud cannot

Either side may be `take_url` / `reference_url`. Only a **YouTube** link works: Gemini watches a public video
from its address (`file_data.file_uri` + `video_metadata`), so nothing is downloaded or stored here, and
`classify_link` rebuilds the address from the 11-character id alone (reusing `widgetz._player_for`, so
lookalike hosts and appended junk never reach the model). The coach reads `LINK_WINDOW_SECONDS` (4 min) from
the link's `?t=` / `?start=` (default 0) — a whole album upload must not be the price of one comparison —
and is told it is hearing a section.

**Spotify and SoundCloud are refused up front, with the reason, and nothing runs.** They serve a player and never
the audio, so there is nothing to hear; having the model "review" a song from its title would be invented detail,
which is the substance rule's failure case. `GET` publishes `link_sources` (the sentence per provider) and
`link_note` so the screen says it as the member pastes, not after the press. A link costs no ⚡ (only a post does).
A video Gemini cannot open (private, age-restricted, removed) answers 502 `link_unreachable`, uncharged.

**Never run against Google** — the YouTube-URL input is Gemini's preview feature and CI has no key, so the request
shape is pinned by tests and unverified live. Check it once with a real key before relying on it.

## SessionZ: every past session, editable, with the ones that need a look said plainly

`GET /api/economy/bodiez/sessions/log/` (`BodieZSessionLogView`) is every FINISHED session, newest first, paged
(`limit` ≤ 100, `offset`), searchable (`q`: a routine's title or a lift's name), bounded by `since` / `until`
(YYYY-MM-DD), fetchable singly (`id`), with lifetime `totals`. The plain `sessions/` list stays the newest 50 with
the open one mixed in, because Today needs exactly that; SessionZ is where somebody goes to find a log from last
spring, so this one has no ceiling. Each row is the editable session (sets with ids, so an edit keeps measured rest)
plus its own `volume_kg` / `reps` / `duration_seconds` and `check`. Yours only, by the query; the cost is constant in
the number of sessions (a test pins it).

- **`check` is facts about the row, worded for the member, never a correction.** Nothing logged → "add what you did,
  or delete it". A LIVE session that ran ≥ `LEFT_OPEN_HOURS` (4) → "probably left open, so the length may not be the
  workout's; the sets are what count". A workout typed in afterwards has no measured length, so it is never flagged for
  one. `check=1` narrows the list to these. The fix stays the member's.
- Editing and deleting use the endpoints that already existed (`sessions/<id>/sets/` PUT, `sessions/<id>/` PATCH and
  DELETE); this only lists. An edit recounts records, BodyMap and goals, as before.

## The Plan rating: a coach-made routine is built to its checks — it is NOT stamped a 10

Corey asked that a routine the coach makes or edits get a 10, and that an edit show how the score changes and why.
Taken literally that is the substance rule's exact failure: the routine rating that exists, **Thorough**
(`bodiez.thoroughness`), is read off sessions the member actually trained and is None until there are some, and a flat 10
stamped on a plan nobody has trained is a number that measures nothing — *could a member get a good one without getting
good?* So the two asks are met with a DIFFERENT number about a different thing (`routine_plan.py`): the **Plan** rating,
the routine AS WRITTEN against rules that are written down, each shown passed or failed with the lift that decided it.

- **Five checks, score = 10 × passed ÷ judged (one decimal):** `reps` and `sets` inside the goal's range (`GOALS`, each with its
  citation; sets within ±1), `order` (compound before isolation, from `superset_table`'s declared mechanic — the app's own
  rule, said to be uncited), `access` (the server's own `accessible` flag) and `repeats`. A check that cannot be judged (no goal,
  nothing to compare) is LEFT OUT, never passed; an empty routine has no score, not a 10 and not a 0.
- **The Planner builds to the checks, so its routines read 10.** `source: "coach"` on create runs `polish` (big lifts first;
  reps and sets to the NEAREST edge of the goal's range — the smallest change that passes, never a number of the Planner's
  choosing) and returns what it changed in `polished`. A routine made by hand is scored as written and never rearranged.
  That a coach-made routine usually reads 10 is a statement of what it was built to, not of how good it is for anyone — said
  in the caveat served with it (`PLAN_CAVEAT`), which also says Thorough is the other number and where it comes from.
- **An edit says how the score moved and why.** `PATCH` returns `plan_change` ({before, after, change, checks[{label, was, now, why}]},
  `why` naming the lift); `POST routines/plan/` is the same arithmetic read-only, so Fit to equipment and "Let the Planner fix this"
  show "Plan 7.5 → 10, because Bench Press: 3 → 8 reps…" BEFORE anything is saved, and `polish: true` returns the Planner's list.
- **Only what the Planner can fix, it fixes** (order, reps, sets). `access` and `repeats` are the member's to resolve: reported
  as "still yours to fix", never silently deleted or swapped. Weights and every other field are untouched.
- **Found on the way:** the board (`routines/` cards are drawn from `bodiez/board/`) never carried `coach_rating`, so the Thorough
  line on a routine card read "not rated yet" for everybody. Both ratings ride the board now, in a constant number of queries.
- Never feeds a skill level, leaderboard, price or anything else — it only labels a routine.

`session_summary` carries `routine_id` (None for a custom session, and None once the routine is deleted) so the ended-session card can
offer "Improve this routine" and LAND on that routine; a routine that no longer exists offers nothing rather than a dead door.
