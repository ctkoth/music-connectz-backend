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

## Deployment

- Backend is on Render with **auto-deploy OFF**. Every backend change needs a
  **Manual Deploy**, and any change with a migration needs `migrate` run too.
- Frontend deploys itself (Vercel / Cloudflare Pages). This means a frontend
  change can go live before the backend it depends on — sequence deploys so the
  UI never promises what the API cannot do yet.

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
