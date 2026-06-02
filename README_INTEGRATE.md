# Integrate into your real music-connectz-backend

Additive: new app folders + a merged urls.py + an INSTALLED_APPS patch. Your
settings.py is NOT replaced — only INSTALLED_APPS gets new lines inserted.

## One command (from your cloned repo root)
```bash
bash /path/to/this/integrate.sh         # branch 'creator-appz'
bash /path/to/this/integrate.sh main    # straight to main (auto-deploys)
```
Backs up settings/urls, copies apps/, patches INSTALLED_APPS, installs merged
urls.py, runs `manage.py check`, commits, pushes.

## Render: run migrations on deploy
Pre-Deploy (or Build) command:
```
python manage.py migrate && python manage.py seed_skillz && python manage.py seed_dawz
```

## Auth — nothing to change
New endpoints use DRF permissions only; your JWT/Bearer secures them automatically.

## Tier gate (Premium/StatZ)
Read from your `apps.memberships` (`user.membership.tier`). Tolerant of related
names; if paid users stay locked, fix one line in `apps/common/tiergate.py`.

## Age verification (the only path to 'adult')
Endpoints under /api/:
- `GET  /api/me/age/`                   current state
- `POST /api/me/age/declare/ {dob}`     records DOB — NEVER grants adult alone
- `POST /api/me/age/parental-consent/`  → youth (call after verified guardian confirm)
- `POST /api/me/age/verify-adult/`      → the ONLY path to 'adult'. NOT self-serve:
  needs Django admin OR header `X-MCZ-KYC-Secret: <settings.MCZ_KYC_SECRET>`
  (call from your KYC webhook; pass `user_id`).
Set `MCZ_KYC_SECRET` in env. age_status defaults to 'unknown' (fail-closed) →
ManageZ, ScoutZ and your gambling/dating/payout surfaces stay locked until a
user is verified. Set per-user in admin (Common ▸ User flags) for testing.

## New endpoints (all under /api/)
designz/*, shotz/* (+train), writez/* (+train), managez/* (18+),
developz/*, producez/train/*, mixez/train/*, scoutz/* (Premium+18+),
dawz/proposals|vote, skillz/progress/<id>/, skillz/capabilities/, me/age/*

## Verified
check clean; migrations apply; age flow (DOB never grants adult; minor can't
self-verify; parental consent → youth; KYC/admin → adult); ScoutZ requires
BOTH premium and adult; training/badges/voting tested.

## Stripe Identity — activation (what YOU need to do)
The code is wired; activation is all dashboard + env (never paste secret keys in
chat — set them in Render → Environment):

1. **Enable Identity**: https://dashboard.stripe.com/identity  (and use a
   restricted key with Identity write — https://dashboard.stripe.com/apikeys).
2. **Create a webhook**: https://dashboard.stripe.com/webhooks → endpoint URL
   `https://admin.musicconnectz.net/api/webhooks/stripe-identity/`, subscribe to
   `identity.verification_session.verified` and
   `identity.verification_session.requires_input`. Copy its **Signing secret**.
3. **Render env vars** (Environment tab):
   - `STRIPE_SECRET_KEY` = your restricted/live key (you may already have this for memberships)
   - `STRIPE_IDENTITY_WEBHOOK_SECRET` = the signing secret from step 2
   - (optional) `MCZ_KYC_SECRET` = a random string, if you also want server-to-server `verify-adult`
4. `pip install stripe` — add `stripe>=9.0` to requirements.txt if not present.

Cost: ~$1.50 per completed US verification; attempts that end in `requires_input`
are free. The webhook reads the verified DOB and marks the user an adult ONLY if
the verified age is ≥ 18 — a verified minor is never made adult.

Endpoints: `POST /api/me/age/stripe-identity/start/` (auth'd; returns Stripe URL),
`POST /api/webhooks/stripe-identity/` (Stripe → you; signature-verified).

## "Could not connect"
Backend is UP — https://admin.musicconnectz.net/ returns 404 (no route for `/`,
which is normal; `/admin/` and `/api/...` work). The error is client-side:
Render free-tier cold start (~50s first hit) or the frontend running on
localhost/Electron without `VITE_API_BASE`. See the frontend README for the fix.
