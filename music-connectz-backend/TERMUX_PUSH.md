# TERMUX_PUSH — Backend (Render)

## The CORS E013 crash is now auto-fixed in code (no settings.py edit)

`corsheaders.E013: Origin '://musicconnectz.net' is missing scheme` kept failing
because the bad origin lives in YOUR settings/env. This zip fixes it in code:
`apps/accounts/apps.py` -> `ready()` normalizes CORS_ALLOWED_ORIGINS and
CSRF_TRUSTED_ORIGINS at startup, BEFORE Django's system check runs. Verified: with
`CORS_ALLOWED_ORIGINS = ["://musicconnectz.net"]`, `manage.py check` now reports
"no issues". `accounts` is already in your INSTALLED_APPS, so this applies the
moment you deploy this code — nothing to edit by hand.

## Termux: force-push so Render redeploys

```bash
# 1) go to your repo
cd ~/music-connectz-backend          # adjust if your path differs

# 2) drop in the updated apps from this unzip (overwrites accounts/ with the fix)
cp -r ~/path-to-unzip/music-connectz-backend/apps/* apps/

# 3) one-shot helper (pass the branch Render deploys from: main OR master)
bash push_backend_force.sh main
```

Prefer raw git instead of the script? Same thing:
```bash
cd ~/music-connectz-backend
git add -A
git commit -m "Auto-fix CORS E013; SkillZ + OAuth + migrations"
git push --force origin HEAD:main      # use master if that's your deploy branch
```

If git rejects the remote or it's missing:
```bash
git remote add origin https://github.com/ctkoth/music-connectz-backend.git 2>/dev/null || true
git push --force origin HEAD:main
```

After it deploys, the log should show the system check passing and:
`accounts.0001_initial OK`, `mimez.0001_initial OK`, `directz.0001_initial OK`,
`skillz.0001_initial OK`.

---

## 1. Merge the files
    cd ~/music-connectz-backend
    cp -r ~/unzipped/music-connectz-backend/apps/* apps/

Adds apps/skillz, apps/accounts, apps/mimez, apps/directz — each WITH a committed
migrations/0001_initial.py. Does not touch apps/common.

## 2. INSTALLED_APPS  <- the missing-apps fix
All four must be present (skillz first). skillz + accounts were already there;
ADD mimez and directz:

    INSTALLED_APPS = [
        # ...
        "rest_framework_simplejwt",
        "apps.skillz",
        "apps.accounts",
        "apps.mimez",     # <-- add
        "apps.directz",   # <-- add
    ]

## 3. Root urls.py
    urlpatterns += [
        path("api/auth/", include("apps.accounts.urls")),
        path("api/mimez/", include("apps.mimez.urls")),
        path("api/directz/", include("apps.directz.urls")),
    ]

## 4. Settings + requirements
- config_snippets/settings_oauth.txt -> SimpleJWT, CORS/CSRF for the Vercel origin,
  OAuth env reads.

  CORS DEPLOY FIX (corsheaders.E013): your last deploy failed with
  "Origin '://musicconnectz.net' is missing scheme or netloc". One of your CORS
  origins has no https:// scheme. The updated settings_oauth.txt now builds the
  lists through a normalizer that auto-adds https:// and drops malformed/blank
  entries, so it can't crash boot again. Replace your CORS_ALLOWED_ORIGINS /
  CSRF_TRUSTED_ORIGINS blocks with the ones in that file (and remove any stray
  bare-host origin from your env / settings).
- config_snippets/requirements-additions.txt -> append + pip install -r requirements.txt.

## 5. Render env vars
    GOOGLE_OAUTH_CLIENT_ID, GITHUB_OAUTH_CLIENT_ID, GITHUB_OAUTH_CLIENT_SECRET, APPLE_OAUTH_CLIENT_ID

## 6. Render start/build command
Your current one is fine — migrations are committed, so this creates the tables:

    python manage.py migrate --no-input && gunicorn music_connectz.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120

To also seed drills/badges on deploy (idempotent), prepend:

    python manage.py migrate --no-input && python manage.py seed_skillz && gunicorn ...

## 7. Push
    bash push_backend.sh

After deploy the migrate log should read:
  Applying accounts.0001_initial... OK
  Applying mimez.0001_initial... OK
  Applying directz.0001_initial... OK
  Applying skillz.0001_initial... OK

## Verify
    curl -X POST https://admin.musicconnectz.net/api/auth/register/ \
      -H "Content-Type: application/json" \
      -d '{"username":"test1","email":"t@example.com","phone":"+15551234567","password":"supersecret"}'

Expect 201 with {user, access, refresh}. A 405 means the route isn't wired (step 3);
a 500 about a missing table means migrate didn't run (step 6).

## Endpoints
    POST /api/auth/register/  {username,email,phone,password} -> {user, access, refresh}
    POST /api/auth/login/     {identifier,password}           -> {user, access, refresh}
    GET  /api/auth/me/    POST /api/auth/refresh/
    POST /api/auth/oauth/google|github|apple/
    GET  /api/mimez/skillz/profile|drills|badges|leaderboard/   POST /api/mimez/skillz/complete/
    GET  /api/directz/skillz/...                                POST /api/directz/skillz/complete/
