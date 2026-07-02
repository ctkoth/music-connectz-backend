# DB_FIX — "relation auth_user does not exist" + login 500

## What happened

Your Render service is pointed at the OLD platform's Postgres database. That DB's
`django_migrations` table still lists the OLD apps' migrations (old `accounts`,
`skillz`, `common`, `dawz`, ...) as applied. When the NEW backend migrates:

- Django sees `auth` / `accounts` marked "already applied" → skips creating
  `auth_user` and `accounts_profile`
- Then `directz.0001` tries to reference `auth_user` → ProgrammingError
- And login queries hit missing tables → the 500 you saw on /api/auth/login/

The new code and the old database schema are incompatible. Pick ONE fix:

## Option A — fresh database (recommended, keeps old data intact)

1. Render Dashboard → New → PostgreSQL → create (e.g. `mcz-db-v2`).
2. Copy its **Internal Database URL**.
3. Your web service → Environment → set `DATABASE_URL` to that new URL → Save.
4. Manual Deploy. Migrations run on a clean DB:
   `auth… accounts.0001 OK, skillz.0001 OK, mimez.0001 OK, directz.0001 OK,
    lessonz.0001-0003 OK` — then login/register work.

The old database is untouched (you can still recover anything from it later).

## Option B — one env var, no psql needed (DESTROYS old data)

If you can't or don't want to create a new database, wipe the polluted schema
right from Render:

1. Service → Environment → add `RESET_DB=1` → Save → Manual Deploy.
   start.sh detects it, runs `reset_schema --force` (drops + recreates the
   `public` schema), then migrate rebuilds everything and seeds SkillZ.
2. VERIFY login works, then REMOVE `RESET_DB` from the environment so it can
   never wipe again on a future deploy.

This erases everything in that database — old platform rows included.

## Option C — manual psql (same result as B)

Only if you don't need anything in the old DB. In Render → your Postgres →
Connect → external psql command, then:

```sql
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
```

Redeploy the service; migrations rebuild everything from zero.

## Also fixed in this zip

The start command previously did `cd "$P"` AND `gunicorn --chdir "$P"` with a
RELATIVE path — after the first cd, the second chdir looked for
`./music-connectz-backend/music-connectz-backend` → "can't chdir" flapping.
`start.sh` / `build.sh` now resolve the project to an ABSOLUTE path first.

Simplest Render settings now:
- Build Command: `./build.sh`   (or bash music-connectz-backend/build.sh if nested)
- Start Command: `./start.sh`   (same note)

Or paste inline (absolute-path safe):
```
bash -c 'P="$(cd "$(dirname "$(find . -path "*/music_connectz/wsgi.py" | head -1)")/.." && pwd)"; cd "$P" && python manage.py migrate --no-input && (python manage.py seed_skillz || true); exec gunicorn music_connectz.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120'
```

## Verify after deploy
```
curl https://admin.musicconnectz.net/                 -> {"status":"ok"}
curl -X POST https://admin.musicconnectz.net/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"username":"t1","email":"t1@x.com","phone":"+15551230000","password":"supersecret1"}'
                                                      -> 201 {user, access, refresh}
```
Then log in from the app — the 500 is gone once the tables exist.
