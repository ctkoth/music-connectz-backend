#!/usr/bin/env bash
# Auto-locate the project (works nested), resolve to an ABSOLUTE path, run.
HERE="$(cd "$(dirname "$(find . -path '*/music_connectz/wsgi.py' | head -1)")/.." && pwd)"
echo "==> project: $HERE"
cd "$HERE"
python manage.py migrate --no-input
python manage.py seed_skillz || true
exec gunicorn music_connectz.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120
