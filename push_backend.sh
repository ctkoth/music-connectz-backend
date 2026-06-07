#!/usr/bin/env bash
# Push the Music ConnectZ BACKEND to GitHub (auto-deploys on Render).
# This repo is now a COMPLETE, standalone Django project (manage.py + settings +
# wsgi + all existing apps + working auth) — it boots and deploys on its own.
# Usage:  bash push_backend.sh ["commit message"]
set -euo pipefail
cd "$(dirname "$0")"
MSG="${1:-Backend: standalone deployable project + JWT/OAuth auth + DesignZ (no DrawZ) + live ScoutZ/ManageZ marketplaces + gamified creator apps + manifest}"
REMOTE="https://github.com/ctkoth/music-connectz-backend.git"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || git init
git remote get-url origin >/dev/null 2>&1 || git remote add origin "$REMOTE"

# Safety: make sure the project at least imports before pushing.
python manage.py check || { echo "✗ django check failed — not pushing"; exit 1; }

git add -A
git commit -m "$MSG" || { echo "Nothing to commit."; exit 0; }
git push -u origin HEAD:main
echo "✓ Backend pushed → Render will build admin.musicconnectz.net"
echo "  Render settings to confirm:"
echo "    Build:      pip install -r requirements.txt && python manage.py collectstatic --noinput"
echo "    Pre-Deploy: python manage.py migrate && python manage.py seed_skillz && python manage.py seed_dawz"
echo "    Start:      gunicorn music_connectz.wsgi:application"
