#!/usr/bin/env bash
# push_backend_force.sh — force-push the backend to GitHub so Render redeploys.
# Run from the ROOT of your backend repo (where manage.py lives).
#
#   bash push_backend_force.sh            # pushes to 'main'
#   bash push_backend_force.sh master     # pushes to 'master'
#
# IMPORTANT: pass the SAME branch Render deploys from (check Render -> Settings -> Branch).
set -e

BRANCH="${1:-main}"

if [ ! -f manage.py ]; then
  echo "!! manage.py not found. cd into your backend repo root first."; exit 1
fi

# Make sure origin exists / points at your repo
git remote get-url origin >/dev/null 2>&1 || \
  git remote add origin https://github.com/ctkoth/music-connectz-backend.git

echo "==> staging + committing"
git add -A
git commit -m "Auto-fix CORS E013 (accounts.ready); SkillZ + OAuth + committed migrations" || echo "(nothing to commit)"

echo "==> force-pushing to origin/$BRANCH"
git push --force origin "HEAD:$BRANCH"

echo "==> Done. Render will redeploy from '$BRANCH'."
echo "   Expect the system check to pass and migrate to run:"
echo "     accounts.0001_initial OK / mimez.0001_initial OK / directz.0001_initial OK / skillz.0001_initial OK"
