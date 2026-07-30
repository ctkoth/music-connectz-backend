# Music ConnectZ — Backend (complete, Render-ready)

A clean Django project you can push and deploy live. Boots green and is verified:
register/login (username · email · phone), Google/GitHub/Apple OAuth, and the
SkillZ training engine for MimeZ and DirectZ (XP, streaks, badges, leaderboards).

> This is a from-scratch project. It includes the four apps I built
> (`accounts`, `skillz`, `mimez`, `directz`). It does NOT include your other apps
> (dawz, designz, managez, scoutz, shotz, writez, common) — those live only in your
> GitHub history. To merge them back, see `RECOVER_REPO.md`, then drop their
> folders into `apps/` and add them to `INSTALLED_APPS`. Your Postgres data is
> untouched.

## Push it live (fresh repo or overwrite)
```bash
cd music-connectz-backend
git init -b main            # if this is a fresh folder
git add -A
git commit -m "Complete backend: accounts/OAuth + SkillZ (MimeZ/DirectZ)"
git remote add origin https://github.com/ctkoth/music-connectz-backend.git
git push -u origin main --force     # overwrites the broken main
```

## Render settings
- **Build Command:** `./build.sh`  (installs deps, collectstatic, migrate, seed)
- **Start Command:**
  `gunicorn music_connectz.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
- **Environment variables:**
  ```
  SECRET_KEY=(generate a long random string)
  DEBUG=0
  DATABASE_URL=(your Render Postgres internal URL)
  GOOGLE_OAUTH_CLIENT_ID=...
  GITHUB_OAUTH_CLIENT_ID=...
  GITHUB_OAUTH_CLIENT_SECRET=...
  APPLE_OAUTH_CLIENT_ID=...
  ```
  (Or use `render.yaml` as a Blueprint — it declares all of these.)

OAuth provider setup is in `APPLE_OAUTH.md` (covers Apple, Google, and GitHub).

### Persistent uploads (S3 / Cloudflare R2)

Render's web filesystem is ephemeral, so FileZ uploads are lost on redeploy
unless you point storage at S3-compatible object storage. Set these env vars to
switch the media backend from the local filesystem to S3/R2 (leave them unset
for local dev — quota enforcement works either way):
```
S3_BUCKET_NAME=your-bucket
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com   # Cloudflare R2 only
S3_REGION=auto            # "auto" for R2; e.g. "us-east-1" for AWS S3
S3_CUSTOM_DOMAIN=cdn.example.com   # optional: serve via public CDN (no signed URLs)
```
By default uploads are served with short-lived signed URLs
(`S3_URL_EXPIRE` seconds, default 3600). Set `S3_CUSTOM_DOMAIN` to serve them
publicly through a CDN/custom domain instead.

### Wallet funding (Stripe / PayPal)

Users fund their wallet via Stripe Checkout or PayPal. Each provider is optional
— set its keys to enable it; the client hides the button when a provider is off.
Crediting applies the developer tax server-side and is idempotent.
```
FRONTEND_URL=https://musicconnectz.net      # for checkout return URLs
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...           # returned to the client
STRIPE_WEBHOOK_SECRET=whsec_...              # verifies webhook calls
PAYPAL_CLIENT_ID=...
PAYPAL_SECRET=...
PAYPAL_MODE=live                             # or "sandbox" (default)
```
Point the Stripe webhook at `/api/economy/webhooks/stripe/` for the
`checkout.session.completed` event — that's what credits the wallet after a card
payment. PayPal credits on capture at `/api/economy/checkout/paypal/capture/`.

## Verify after deploy
```bash
curl https://admin.musicconnectz.net/                       # {"status":"ok",...}
curl -X POST https://admin.musicconnectz.net/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"username":"t1","email":"t1@x.com","phone":"+15551234567","password":"supersecret1"}'
```
Expect `{"status":"ok"}` then `201` with `{user, access, refresh}`.

## Endpoints
```
POST /api/auth/register/   {username,email,phone,password} -> {user, access, refresh}
POST /api/auth/login/      {identifier,password}            -> {user, access, refresh}
GET  /api/auth/me/   POST /api/auth/refresh/
POST /api/auth/oauth/google|github|apple/
GET  /api/mimez/skillz/profile|drills|badges|leaderboard/   POST /api/mimez/skillz/complete/
GET  /api/directz/skillz/...                                POST /api/directz/skillz/complete/
GET  /api/omviardz/tour/                                    POST /api/omviardz/answer/
GET  /api/economy/personaz/          GET /api/economy/personaz/<key>/
POST /api/economy/occ/projects/<id>/agent/   (OCC coding agent — tool loop)
GET  /api/economy/pod/blanks/        POST /api/economy/pod/listings/<id>/buy/
POST /api/economy/play/verify/       (Google Play Billing purchase verification)
GET  /.well-known/assetlinks.json    (Android app <-> site link verification)
GET  /admin/
```

## OmviardZ — the guided tour

The mobile onboarding walkthrough: it spotlights one control at a time, Corey
explains it in his own voice, and it branches on what the member answers. Free —
no wallet charge, no prompt allowance. Works with no `ANTHROPIC_API_KEY` (every
option ships written copy in the payload) and gets live Corey when one is set.

Client contract, mobile design tokens, and how to add a step: **[OMVIARDZ.md](OMVIARDZ.md)**

## OCC coding agent

OCC can now change code, not just explain it: an agentic tool loop (read, write,
exact-string edit, search, rename, delete) over a per-member workspace, running
until it's done or the step cap is hit. Every run is recorded with its tool calls.

A bad run is one call to undo: the workspace is snapshotted before every writing
run (`POST /occ/projects/<id>/undo/`), and the undo is itself undoable.

It has **no code execution and no shell** — running member code on the API host
needs container isolation this backend doesn't have, and OCC is told never to
claim it ran anything. What that gap takes to close, and the full API:
**[OCC_AGENT.md](OCC_AGENT.md)**

## MerchZ print-on-demand

One design, listed on any of **20 blanks** (tees, tanks, long sleeves, hoodies,
crewnecks, AOP kimono/bomber/windbreaker, embroidered denim jacket, baseball
/snapback/trucker caps, beanie, beach towel, tote, mug, posters, stickers),
produced only when it sells — no inventory. The buyer's exact size gets printed; extended sizes and dark garments
carry the printer's upcharge, paid by the buyer so the creator's margin is the
same on every variant.

```bash
python manage.py seed_pod        # blank catalog (idempotent)
```

Sellers get invoices (`/pod/orders/<id>/invoice/`), a revenue-ranked "what's
selling" report with size and colour breakdowns (`/pod/sales/`), and a monthly
statement (`/pod/statement/`). These are sales records, not tax invoices — no
sales tax or VAT is calculated or collected.

Sizes, colours, stock-outs, print-method limits, the money split, and provider
setup: **[MERCH_POD.md](MERCH_POD.md)**

## PersonaZ — the persona/skill catalog

`GET /api/economy/personaz/` serves every persona and its skills, so the frontend
stops carrying its own copy. 8 personas, **271 skills**: the five from the 2.2 build
preserved verbatim, plus Ghostwriter, Manager and Developer (top 20 languages),
built in the same paradigm.

```bash
python manage.py audit_personaz          # catalog + stored-data audit
python manage.py audit_personaz --fix    # normalize stored profiles in place
```

Findings from the 2.2 audit, the paradigm every persona follows, and what the
frontend needs to change: **[PERSONAZ_AUDIT.md](PERSONAZ_AUDIT.md)**

## Android app + Google Play

`android/` is a Trusted Web Activity — it opens the site full-screen with no URL
bar, so the mobile web app is the Android app. Build an APK with no local
toolchain: GitHub → Actions → **Android APK** → Run workflow.

**Play Billing** (required for digital goods in the Android app) is built:
`POST /api/economy/play/verify/` checks a purchase token against Google's Play
Developer API, grants exactly once per token, and refuses a token bound to another
account. Needs `PLAY_PACKAGE_NAME` + `PLAY_SERVICE_ACCOUNT_JSON`; answers 503
until then so the client falls back to web checkout.

- **[GOOGLE_PLAY.md](GOOGLE_PLAY.md)** — joining Play, signing, the declarations
  that get checked, the 12-tester closed test, and the three things most likely
  to get the app rejected (read the payments one).
- **[android/README.md](android/README.md)** — the app itself.
- `brand/` — the wordless logo mark plus Play Store assets, all generated by
  `python tools/make_brand_assets.py`.

Link verification needs two env vars on Render (fingerprints from Play Console →
Release → Setup → App signing):
```
TWA_PACKAGE_NAME=net.musicconnectz.app
TWA_SHA256_FINGERPRINTS=<play app-signing sha256>,<upload key sha256>
```

## Local dev
```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_skillz
python manage.py createsuperuser
python manage.py runserver
```
