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

## Testing

- The suite runs on SQLite by default, but production is PostgreSQL, and
  **SQLite ignores varchar length**. A column-width bug is invisible locally.
  For anything touching field widths, run against a real Postgres:
  `DATABASE_URL=postgres://... python manage.py test`
- Member-authored text answers to the **tier's character limit**, never to a
  column width. Use `catalog.over_char_limit(text, tier)`.

## Tier limits live on the server

`apps/economy/catalog.py` is the source of truth for char limits, upload and
storage sizes, and prices. The frontend reads them from
`/api/economy/limits/`. Never hardcode a tier number in UI copy — that is how
the "20 free prompts" figure drifted into nine places.
