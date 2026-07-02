#!/usr/bin/env bash
set -o errexit
HERE="$(cd "$(dirname "$(find . -path '*/music_connectz/wsgi.py' | head -1)")/.." && pwd)"
echo "==> project: $HERE"
cd "$HERE"
pip install -r requirements.txt
python manage.py collectstatic --no-input || true
