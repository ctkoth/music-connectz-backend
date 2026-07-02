#!/usr/bin/env bash
HERE="$(cd "$(dirname "$(find . -name manage.py -not -path '*/node_modules/*' | head -1)")" && pwd)"
cd "$HERE"
echo "==> starting from: $HERE"
exec gunicorn music_connectz.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120
