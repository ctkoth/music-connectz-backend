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
