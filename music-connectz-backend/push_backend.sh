#!/usr/bin/env bash
# push_backend.sh — commit the SkillZ/OAuth apps (with committed migrations) and
# push to GitHub -> Render auto-deploy. Run from the backend repo ROOT.
#
#   bash push_backend.sh
#
set -e
BRANCH="${1:-main}"

if [ ! -f manage.py ]; then
  echo "!! manage.py not found. cd into your backend repo root first."; exit 1
fi

# Migrations are ALREADY committed in this zip — no makemigrations needed.
# Sanity check that nothing is missing (won't fail the push):
python manage.py makemigrations --check --dry-run accounts mimez directz skillz \
  && echo "==> migrations are complete" \
  || echo "!! heads-up: a model change isn't captured — run makemigrations and commit it"

git add -A
git commit -m "DirectZ/MimeZ SkillZ + accounts OAuth, with committed migrations" || echo "(nothing to commit)"
git push origin "$BRANCH"
echo "==> Pushed. Render runs 'migrate' on deploy and will create the new tables."
