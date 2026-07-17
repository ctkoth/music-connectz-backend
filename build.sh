#!/usr/bin/env bash
set -o errexit
HERE="$(cd "$(dirname "$(find . -path '*/music_connectz/wsgi.py' | head -1)")/.." && pwd)"
echo "==> project: $HERE"
cd "$HERE"
pip install -r requirements.txt
# Apply migrations on every deploy. render.yaml's startCommand runs gunicorn
# directly (it does NOT use start.sh), so this is the reliable place to migrate.
python manage.py migrate --no-input
python manage.py collectstatic --no-input || true
