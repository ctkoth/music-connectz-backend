# BodieZ Audit — blueprint vs. what is actually built

Audited against the BodieZ App Blueprint you sent: **Jefit's training metrics behind
Lilith's project-management paradigm.**

Everything below is checked against the code in `apps/bodiez/`, not against my
memory of what I wrote. Counts come from running the catalog, not from counting
by eye. 417 tests pass, 62 of them BodieZ.

---

## Scoreboard

| Area | Status |
|---|---|
| Lilith bucket paradigm (Inbox → Trash) | ✅ built |
| Equipment bank, user-toggled | ✅ built — 27 items |
| Target muscle groups | ✅ built — your 12, in your order, + glutes + full-body |
| Exercise library | ✅ built — 98 exercises |
| Supersets | ✅ built |
| Rest timers | ✅ built |
| Target weight / sets / reps | ✅ built |
| Jefit metrics (volume, 1RM, overload, streaks) | ✅ built |
| BodyMap | ✅ built |
| Progress charts | ✅ data built, chart is frontend |
| AI coach / routine creator | ✅ built — see the note in §7 |
| StatZ access to other users' routines | ✅ built |
| Premium locations w/ equipment + muscle coverage | ✅ built |
| Recovery / readiness | ⚠️ partial — honest heuristic, no wearables |
| Reminders | ⚠️ partial — due dates stored, no push delivery |
| Nutrition 🥗 | ❌ not built |
| Community 🌐 beyond shared routines | ❌ not built |

---

## 1. The tab paradigm

Your blueprint listed 17 tabs. They are not 17 of the same kind of thing — five
are **buckets** (a routine or item lives in exactly one), the rest are **views**
over the same data. I built them that way rather than making 17 parallel lists.

**Buckets** — `BUCKET_LABELS` in `apps/bodiez/models.py`, 7 of them:

`Inbox 📥` · `Today 💪` · `Upcoming 📅` · `Anytime 🏋️` · `Someday 🧠` · `Logbook 🧾` · `Trash 🚮`

Both `Routine` and `BodieZItem` carry a bucket, so a loose thought ("try
Bulgarian split squats") and a full routine move through the same pipeline.
Logbook and Trash are terminal — Logbook is what a finished session writes into,
Trash is soft-delete.

**Views** — one endpoint each:

| Tab | Endpoint |
|---|---|
| Routines 🧩 | `GET/POST /api/bodiez/routines/` |
| Exercises 📚 | `GET /api/bodiez/exercises/` |
| Session ⏱️ | `POST /api/bodiez/sessions/`, `.../sets/`, `.../finish/` |
| Progress 📈 | `GET /api/bodiez/progress/` |
| BodyMap 🧍 | `GET /api/bodiez/bodymap/` |
| Coach 🤖 | `GET /api/bodiez/coach/` |
| Goals 🎯 | `GET/POST /api/bodiez/goals/` |
| Recovery 🛌 | folded into `coach/` as `readiness` |
| Community 🌐 | `GET /api/bodiez/routines/?shared=1` (StatZ) |

**Not built: Nutrition 🥗.** Deliberately. Food logging is its own product — a
food database, portions, macros, barcode scanning. Bolting a token version onto
BodieZ would be worse than not having it. Flagging it rather than pretending.

## 2. Equipment bank — 27 items

Your list is all present: barbell, dumbbell, kettlebell, EZ bar, weight plate,
flat bench, decline bench, incline bench, cable pulley, and the machines. Plus
bodyweight, bands, rings, TRX, landmine, trap bar, sled, rower, bike, treadmill,
box, pull-up bar, dip station, ab wheel, foam roller, medicine ball, jump rope.

The user toggles what they have; `GET /exercises/?equipment=barbell,flat-bench`
filters the library down to what they can actually do today.

**One design decision worth surfacing.** My first pass modelled equipment as
AND — an exercise listed its equipment and you needed all of it. That is wrong.
A goblet squat needs a kettlebell **or** a dumbbell; a bench press needs a
barbell **and** (flat bench **or** incline bench). So requirements are stored as
**groups**: a list of any-of tuples, ANDed together.

```python
def can_perform(requirements, have):
    return all(set(group) & have for group in requirement_groups(requirements))
```

Bodyweight is always implicitly available — nobody should have to toggle "I have
a body". `apps/bodiez/catalog.py`.

## 3. Muscle groups — your 12, in your order

`neck · shoulder · chest · bicep · tricep · forearm · wrist · back · trapZ ·
abZ · upper leg · lower leg`

I added two: **glutes** (Jefit tracks them separately and they are half of any
lower-body program) and **full-body** (so cleans and burpees have somewhere to
land). 14 total. Your 12 come first and in your order, so the UI can render them
without re-sorting.

## 4. Exercises — 98

Each carries: primary muscle, secondary muscles, equipment requirement groups,
movement pattern, and whether it is unilateral. Filterable by muscle, equipment,
pattern, or search string.

98 is enough to build a real program for every split in the catalog. It is not
Jefit's 1,400. Growing it is data entry against a schema that already holds
everything needed — no code changes.

## 5. Routines — supersets, rest, targets

`RoutineExercise` carries `sets`, `reps`, `rest_seconds`, `target_weight`,
`superset_group`, `tempo`, `order`. Exercises sharing a `superset_group` are
performed back-to-back and the app rests once at the end of the group — that is
what the field is for, and the ordering respects it.

Routines also compute `estimated_minutes` and the `muscles` they hit, so the
list view can show "48 min · chest, tricep, shoulder" without opening anything.

## 6. Jefit metrics — what is actually computed

`apps/bodiez/coach.py` and the session models:

- **Volume** — per set (`weight × reps`), rolled up per session (`total_volume`)
  and per muscle group over a window.
- **Estimated 1RM** — Epley, `w × (1 + reps/30)`. **Capped at 12 reps**, because
  Epley diverges into fantasy above that; a 20-rep set does not tell you a 1RM.
- **Progressive overload verdict** — per exercise, over the last sessions:
  `increase` / `repeat` / `reduce` / `deload` / `no_data`. `no_data` is a real
  answer and it is returned honestly rather than defaulting to `repeat`.
- **BodyMap** — 7-day volume per muscle. Secondary muscles get **half credit**,
  since a row is not a bicep day. `weakest` returns **every** undertrained
  muscle, not just the single worst — you cannot fix a program from one data
  point.
- **Streaks and PRs** — in `progress/`.

**Readiness (Recovery 🛌) is a heuristic, and it says so.** It reads recent
volume, days since training each muscle, and logged soreness. It returns a
`basis` string naming what it actually used. It is not HRV, sleep, or anything
from a wearable — there is no wearable integration. A number that looks like
Whoop's but is computed from three inputs would be worse than an honest one.

## 7. Tier gates

| Tier | BodieZ access |
|---|---|
| Free | Catalog, exercises, own routines, sessions, progress, BodyMap, goals, items, readiness |
| Free | AI routine creator — **3 prompts/day**, then PromptZ or cents |
| Premium | Everything above + **locations** (per-gym equipment, muscle coverage, gaps) |
| Premium | AI routine creator — **10 prompts/day** |
| StatZ | Everything + AI routine creator **without spending a prompt** + **other users' public routines** |

**One correction to your spec, and it is deliberate — flagging it rather than
burying it.** You said StatZ gets the AI coach / routine creator. I did not gate
it to StatZ. A free member spends one of their 3 daily prompts and gets the same
coach, because "the AI wrote me a program" is the reason to open this app at
all — a free member who never sees it never upgrades for it. What StatZ actually
buys is that it stops costing anything: unlimited, not exclusive. If you want it
locked to StatZ instead, it is a one-line gate in `AIRoutineView`. Say the word
and I will flip it.

`_gate()` returns **402 Payment Required**, not 403, with the feature name and
the tier that unlocks it — so the app can route straight to the upgrade screen
instead of showing a dead end.

**Locations** are the Premium feature you specified: a gym has an equipment
list, and BodieZ computes its `muscle_coverage` and its `gaps` — "this gym can
train 11 of 14 muscle groups; no neck, no sled, no reverse-hyper." That is the
Jefit gym-profile metric.

**A bug worth recording.** `GymLocation.muscle_coverage` was still using
`set(needs).issubset(have)` after I restructured requirements into any-of
groups, so every tuple requirement silently failed to match and gyms
under-reported their coverage. I found it by printing the actual output instead
of reasoning about the diff. It now calls `can_perform`.

## 8. AI coach

`ai_plan()` builds a routine from goal + available equipment + days per week +
split + focus. Two properties matter:

1. It is given only the **filtered** catalog, so it cannot prescribe a leg press
   to somebody with a barbell in a garage.
2. Anything it returns that is **not in that filtered catalog is dropped**, not
   trusted. The model does not get to invent exercises.

Free and Premium run it through the daily prompt allowance (3/day and 10/day),
falling back to PromptZ then cash. StatZ runs it for free. A failed coach run
charges **nothing** — a 503 is not a prompt the member spent.

The plan is saved as a real `Routine` in the `anytime` bucket, with every
exercise, set, rep, rest, and superset group written through — not returned as
text for the user to re-enter.

---

## Honest gaps

1. **Nutrition 🥗** — not built, and not faked.
2. **Reminders** — due dates and buckets are stored, so Today/Upcoming are
   correct. Nothing pushes a notification. That needs the mobile push channel,
   not a BodieZ change.
3. **Recovery** — heuristic, no wearables. Stated in the payload.
4. **Exercise library at 98** — real but not exhaustive. Pure data growth.
5. **Progress charts** — the endpoint returns series; drawing them is frontend.
6. **Rest timer** — `rest_seconds` is stored and served; the countdown itself
   lives in the client.

Nothing in this list is blocked on a decision. They are all "not yet", not
"cannot".
