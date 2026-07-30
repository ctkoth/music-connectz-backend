#!/usr/bin/env bash
set -o errexit
HERE="$(cd "$(dirname "$(find . -path '*/music_connectz/wsgi.py' | head -1)")/.." && pwd)"
echo "==> project: $HERE"
cd "$HERE"
pip install -r requirements.txt
# Apply migrations on every deploy. render.yaml's startCommand runs gunicorn
# directly (it does NOT use start.sh), so this is the reliable place to migrate.
python manage.py migrate --no-input
# Blank catalog for print-on-demand MerchZ. Idempotent (update-in-place), and
# `|| true` because an empty product list is a degraded feature, not a reason to
# fail a deploy.
python manage.py seed_pod || true
python manage.py collectstatic --no-input || true
