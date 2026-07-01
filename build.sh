#!/usr/bin/env bash
# Render Build Command:  ./build.sh
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py seed_skillz || true
