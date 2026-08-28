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

- **BossTake "Send it to the coach"** — spends a prompt, says nothing before
  you press it. `cost_cents` comes back only in the response.
- **AI actions generally** (translate, OCC chat, Gemini image/video) — the
  charge happens server-side with no pre-flight statement of the price.
- **CallZ** — priced by the other member's skill rate per hour; the rate needs
  to be visible before the call connects.

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

### Known violation, not yet fixed

- **`directz_ai_rating`** — see above. It had never run in production because
  nothing posted to DirectZ; the composer added in `claude/occ-agent-loop` means
  it now will, at scale. Either it measures the video or it stops calling itself
  craft.

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

## Tier limits live on the server

`apps/economy/catalog.py` is the source of truth for char limits, upload and
storage sizes, and prices. The frontend reads them from
`/api/economy/limits/`. Never hardcode a tier number in UI copy — that is how
the "20 free prompts" figure drifted into nine places.
