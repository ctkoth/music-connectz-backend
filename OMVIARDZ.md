# OmviardZ — the guided tour

OmviardZ walks a new member through the platform by spotlighting **one control
at a time** while Corey explains it, and it branches on what they answer. It is
built mobile-first: a bottom sheet in the thumb zone, one tap per step, and every
reply short enough to read without scrolling.

It is **free**. No wallet charge, no prompt allowance, ever — a paywalled
tutorial is how you lose someone in the first five minutes.

---

## The shape of it

```
GET  /api/omviardz/tour/           the whole tour for this member's track   (public)
GET  /api/omviardz/step/<key>/     one step, for deep links                 (public)
POST /api/omviardz/answer/         answer a step -> Corey explains, advances (auth)
POST /api/omviardz/skip/           stop asking                              (auth)
POST /api/omviardz/reset/          run it again from the top                (auth)
```

Reading is public so an unsigned-in visitor (or a Play Store screenshot) can see
the whole walkthrough. Answering needs a login — that's the endpoint that can
reach the model.

### One call on app open

`GET /api/omviardz/tour/` returns everything the client needs to render the
entire tour offline:

```json
{
  "app": "omviardz",
  "free": true,
  "track": "make",
  "tracks": {"make": "Make something", "discover": "Get discovered", "…": "…"},
  "design": { "viewport": "mobile-first", "card": {"placement": "bottom-sheet", "…": "…"} },
  "facts": { "tiers": {"free": {"char_limit": 400, "…": "…"}} },
  "resume": "profilez",
  "progress": {"track": "make", "step": "profilez", "done_count": 1, "total": 9},
  "steps": [
    {
      "key": "profilez",
      "index": 2, "total": 9,
      "screen": "profile", "route": "/profile",
      "title": "🎨 ProfileZ — this is what people judge",
      "blurb": "👀 Nobody rates a track from a blank avatar…",
      "highlight": {"target": "[data-omviardz=\"profile-card\"]", "label": "Your profile card",
                    "shape": "rect", "placement": "below", "pulse": true},
      "input": {"kind": "choice", "allow_text": true},
      "options": [
        {"key": "1", "reply": "#1", "label": "🖼️ Avatar — your photo",
         "explain": "🖼️ Tap the circle, pick a photo, done…",
         "highlight": {"target": "[data-omviardz=\"profile-avatar\"]", "label": "Avatar",
                       "shape": "circle", "placement": "below", "pulse": true}}
      ]
    }
  ]
}
```

Pass `?track=money` to preview a different route without changing the member's.

### Answering

```http
POST /api/omviardz/answer/
{"step": "profilez", "choice": "2", "text": "", "slang": false, "suggest": false}
```

```json
{
  "step": "profilez",
  "choice": "2",
  "explain": {"text": "🎂 This one isn't cosmetic…", "source": "corey-gpt", "cost_cents": 0},
  "highlight": {"target": "[data-omviardz=\"profile-birthday\"]", "label": "Birthday", "…": "…"},
  "route": "/profile",
  "next": { "…the next step, same shape as above…" },
  "progress": {"step": "personaz", "done_count": 2, "total": 9}
}
```

- `choice` accepts `"2"`, `"#2"`, or the option's label — tap or type, same field.
- `text` is free typing. With a model key Corey answers it directly; without one
  he says so and hands back the options. **Typing does not advance the tour** —
  you asked a question, you didn't answer one.
- `explain.source` is `"corey-gpt"` when the model answered and `"builtin"` when
  it fell back to the written copy. Render both identically; it's for telemetry.
- `next: null` means the tour is done (`progress.completed` is `true`).

---

## How the client renders a step

1. Navigate to `step.route` if you're not already on `step.screen`.
2. Resolve `step.highlight.target` (a CSS selector). Found → cut a hole in the
   backdrop around it using `design.spotlight`. Not found → skip the spotlight
   and centre the card. **Never block the screen on a missing target.**
3. Render `step.title` + `step.blurb` in the bottom sheet.
4. Render `step.options` as stacked rows, each ≥48dp tall, showing
   `option.reply` as a chip on the right.
5. On tap: immediately show `option.explain` (it's already in your payload — zero
   latency, works offline) and move the spotlight to `option.highlight`. Fire
   `POST /answer/` in the background and replace the text if `explain.source`
   comes back `"corey-gpt"`.
6. On `next`, repeat. Fire haptics per `design.haptics`.

That step 5 ordering is the whole trick: the tour feels instant because the
written answer ships with the payload, and it feels alive because Corey's live
reply replaces it a beat later.

### The DOM hooks

Every highlight targets `[data-omviardz="…"]`. Add the attribute to the real
control — a class name will get renamed by a restyle and silently break the tour.
The tests assert every target uses this form; the full list is in
[`apps/omviardz/tour.py`](apps/omviardz/tour.py).

```html
<button data-omviardz="profile-avatar">…</button>
```

### Mobile rules (from `design`)

| Token | Value | Why |
|---|---|---|
| `card.placement` | `bottom-sheet` | One-handed reach |
| `card.max_height` | `46vh` | Spotlight stays visible above it |
| `card.safe_area_inset` | `true` | Clears the home indicator |
| `options.min_tap_target` | `48` | Android's minimum touch target |
| `typography.min_body` | `16` | Below 16px iOS zooms on focus |
| `motion.respect_reduced_motion` | `true` | Kill the pulse when the OS asks |
| `copy_budget.blurb_chars` | `240` | No scrolling inside a step |

---

## The tour collects real data, not just explanations

Two steps carry a `picker` and the live catalog, so a member finishes the tour
with their actual PersonaZ skills and GenreZ set — the difference between a tour
and a slideshow of tooltips.

```json
"picker": {"type": "personaz", "endpoint": "/api/economy/personaz/",
           "saves_to": "PATCH /api/auth/me/ {personas: [...]}", "select": "many"}
```

| Step | Picker | Collects |
|---|---|---|
| `personaz` | `personaz` | 8 personas, 271 skills, with start dates |
| `genrez` | `genrez` | 47 genres — 2.2's fifteen first |

`GET /api/omviardz/tour/` ships **both catalogs inside the payload** (`catalog.personaz`,
`catalog.genrez`) so a picker step renders without a second round trip — the tour
opens on a phone, and a picker that waits on its own request after the member has
already tapped feels broken.

Options that should open the picker rather than just show Corey's answer carry
`opens_picker: true`. Steps without one report `picker: null` rather than omitting
the key, so a client never has to guess.

The skill start date matters and the copy says so: it's the input to
years-of-experience, and rating 6 in a skill is what unlocks teaching it in
LessonZ.

## Tracks

Step one asks why they're here, and the answer picks the route:

| Track | Steps |
|---|---|
| `make` | welcome → profilez → **personaz** → **genrez** → occ → postz → walletz → tierz → safetyz → finish |
| `discover` | welcome → profilez → **personaz** → **genrez** → postz → socialz → messagez → tierz → safetyz → finish |
| `money` | welcome → profilez → **genrez** → walletz → earnz → royaltiez → collabz → sellz → tierz → safetyz → finish |
| `learn` | welcome → profilez → **personaz** → skillz → **genrez** → occ → sellz → messagez → tierz → safetyz → finish |

`genrez` is on **every** track, including money — a shop with no genre on it is a
shop nobody browses into.

Switching tracks mid-tour is fine — `progress.done_count` counts only the steps
on the *current* track, so the bar can't read 7/9 on a route you just started.

---

## Where the words come from

**Written copy** (`option.explain` in [`tour.py`](apps/omviardz/tour.py)) is the
floor. It ships in the payload, costs nothing, needs no network, and is written
in Corey's voice — most members on a deploy without `ANTHROPIC_API_KEY` will only
ever read this. Treat it as product copy, not as a fallback stub.

**Live Corey** ([`voice.py`](apps/omviardz/voice.py)) reuses `COREY_VOICE` from
OCC plus a tutorial-mode prompt that pins him to the one highlighted control,
caps him at ~120 words, and forbids inventing numbers — the real tier limits are
injected from `apps.economy.catalog`, so the tour cannot promise a limit the
server doesn't give. `slang: true` turns on the same AAVE opt-in OCC uses.

Any failure — no key, rate limit, network, empty reply — falls through to the
written copy. The tour never dead-ends on a step.

---

## Adding a step

1. Add an entry to `STEPS` in `tour.py` with a `highlight`, and options that each
   carry a one-character `key`, a `label`, an `explain`, and their own
   `highlight`.
2. Add the key to at least one track in `TRACKS`.
3. Add `data-omviardz="…"` to the controls you're pointing at, in the frontend.
4. `python manage.py test apps.omviardz` — the spec tests check every track is
   walkable, every step is reachable, reply keys are unique single characters,
   every option has written copy, and every `goto` points at a real step.

---

## On the phone

The Android app (`android/`) appends `?omviardz=1` on first launch, so a fresh
install from Play opens the tour instead of a feed of strangers. Have the
frontend read that query param and start the tour at `resume`. See
[GOOGLE_PLAY.md](GOOGLE_PLAY.md).
