#!/usr/bin/env bash
# push_backend.sh — merge SkillZ/OAuth apps into music-connectz-backend and push.
# Run from the ROOT of your backend repo (where manage.py lives), after copying
# the apps/ folder from this zip into the repo.
#
#   bash push_backend.sh
#
set -e

BRANCH="${1:-main}"
echo "==> Music ConnectZ backend push (branch: $BRANCH)"

if [ ! -f manage.py ]; then
  echo "!! manage.py not found. cd into your backend repo root first."
  exit 1
fi

# 1) Generate migrations for the new apps (committed so Render can migrate).
echo "==> makemigrations"
python manage.py makemigrations skillz accounts mimez directorz || {
  echo "!! makemigrations failed — fix INSTALLED_APPS / settings, then re-run."
  exit 1
}

# 2) (optional) apply locally + seed drills so you can test before pushing.
if [ "${RUN_LOCAL_MIGRATE:-0}" = "1" ]; then
  python manage.py migrate
  python manage.py seed_skillz
fi

# 3) Commit + push -> triggers Render auto-deploy.
git add -A
git commit -m "MimeZ + DirectZ SkillZ training; accounts OAuth (Google/GitHub/Apple), phone register" || echo "(nothing to commit)"
git push origin "$BRANCH"

echo "==> Pushed. Render will build & deploy."
echo "   Make sure your Render build/start command runs:"
echo "     python manage.py migrate && python manage.py seed_skillz"
echo "   And set env vars: GOOGLE_OAUTH_CLIENT_ID, GITHUB_OAUTH_CLIENT_ID,"
echo "     GITHUB_OAUTH_CLIENT_SECRET, APPLE_OAUTH_CLIENT_ID."
