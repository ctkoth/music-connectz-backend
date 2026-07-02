#!/usr/bin/env bash
set -o errexit
HERE="$(cd "$(dirname "$(find . -name manage.py -not -path '*/node_modules/*' | head -1)")" && pwd)"
cd "$HERE"
echo "==> building from: $HERE"
pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py seed_skillz || true
