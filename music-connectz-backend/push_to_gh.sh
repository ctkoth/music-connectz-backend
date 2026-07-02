#!/usr/bin/env bash
# push_to_gh.sh — push this backend so manage.py ends up at the REPO ROOT.
# Works whether you run it from INSIDE the project folder OR one level above it.
#
#   bash push_to_gh.sh            # branch main
#   bash push_to_gh.sh master     # branch master
#
set -e
BRANCH="${1:-main}"
REPO="https://github.com/ctkoth/music-connectz-backend.git"

# Find the directory that directly contains manage.py
if [ -f manage.py ]; then
  ROOT="."
elif [ -f music-connectz-backend/manage.py ]; then
  ROOT="music-connectz-backend"
else
  FOUND="$(find . -maxdepth 3 -name manage.py | head -1)"
  if [ -n "$FOUND" ]; then ROOT="$(dirname "$FOUND")"; else
    echo "!! Could not find manage.py near here. cd to the extracted folder and retry."
    exit 1
  fi
fi

cd "$ROOT"
echo "==> Using project root: $(pwd)  (manage.py is here)"

git init -b "$BRANCH" 2>/dev/null || git checkout -B "$BRANCH"
git add -A
git commit -m "Full backend at repo root: accounts/OAuth + SkillZ MimeZ/DirectZ" || echo "(nothing new to commit)"
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO"

echo "==> Force-pushing to $BRANCH"
git push --force origin "$BRANCH"

echo ""
echo "================ VERIFY ================"
echo "New commit that should now be on GitHub:"
git log --oneline -1
echo "Files at repo root (manage.py MUST be listed):"
git ls-files | grep -E '^(manage.py|requirements.txt|build.sh|start.sh)$' || echo "  !! manage.py NOT at root — you ran this from the wrong folder"
echo "======================================="
echo "If the commit hash above still matches your old failing deploy,"
echo "the push didn't change anything — re-run from the extracted folder."
