#!/usr/bin/env bash
# push_to_gh.sh — push this backend to GitHub with manage.py at the REPO ROOT.
#
# IMPORTANT: run it from INSIDE this folder (the one containing manage.py):
#     cd music-connectz-backend
#     bash push_to_gh.sh                # pushes to main
#     bash push_to_gh.sh master         # pushes to master (if that's your branch)
#
set -e

BRANCH="${1:-main}"
REPO="https://github.com/ctkoth/music-connectz-backend.git"

if [ ! -f manage.py ]; then
  echo "!! manage.py not found in the current folder."
  echo "   You're in the wrong directory. Do:"
  echo "     cd music-connectz-backend && bash push_to_gh.sh"
  exit 1
fi

echo "==> Initializing git here so manage.py is at the repo ROOT"
git init -b "$BRANCH" 2>/dev/null || git checkout -B "$BRANCH"

git add -A
git commit -m "Full backend (manage.py at repo root): accounts/OAuth + SkillZ MimeZ/DirectZ" \
  || echo "(nothing to commit)"

git remote remove origin 2>/dev/null || true
git remote add origin "$REPO"

echo "==> Force-pushing to $REPO ($BRANCH)"
git push --force origin "$BRANCH"

echo ""
echo "==> Done. In Render → Settings, make sure:"
echo "    • Root Directory: (EMPTY / blank)  — so manage.py is at the root"
echo "    • Build Command:  ./build.sh        (or: pip install -r requirements.txt)"
echo "    • Start Command:  gunicorn music_connectz.wsgi:application --bind 0.0.0.0:\$PORT --workers 2 --threads 4 --timeout 120"
echo "    Then redeploy. 'manage.py' will be found and migrate will run."
