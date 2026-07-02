#!/usr/bin/env bash
# Auto-locate the project (works nested), resolve ABSOLUTE path, run.
HERE="$(cd "$(dirname "$(find . -path '*/music_connectz/wsgi.py' | head -1)")/.." && pwd)"
echo "==> project: $HERE"
cd "$HERE"
# One-shot escape hatch for a polluted old database:
# set env RESET_DB=1, deploy once (schema is wiped + rebuilt), then REMOVE it.
if [ "${RESET_DB:-0}" = "1" ]; then
  echo "!! RESET_DB=1 — dropping and recreating the public schema"
  python manage.py reset_schema --force
fi
python manage.py migrate --no-input
python manage.py seed_skillz || true
exec gunicorn music_connectz.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120
