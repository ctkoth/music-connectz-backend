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
GET  /admin/
```

## Local dev
```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_skillz
python manage.py createsuperuser
python manage.py runserver
```
