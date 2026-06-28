#!/usr/bin/env bash
# Termux-friendly push for the Music ConnectZ backend (MimeZ + OAuth drop).
# Run from the root of your local backend repo clone.
set -e

echo "==> Music ConnectZ backend push (MimeZ + OAuth)"

# Stage the two new apps + docs (adjust paths if your repo layout differs).
git add apps/mimez apps/auth_oauth INTEGRATION_MIMEZ.md requirements_additions.txt 2>/dev/null || git add -A

git status --short

MSG="${1:-Add MimeZ persona (teen-safe, SkillZ) + OAuth Google/GitHub/Apple}"
git commit -m "$MSG" || echo "(nothing to commit)"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "==> Pushing to origin/$BRANCH"
if ! git push origin "$BRANCH"; then
  echo "!! Push rejected. Pulling with rebase and retrying..."
  git pull --rebase origin "$BRANCH"
  git push origin "$BRANCH"
fi
echo "==> Done. Render will auto-deploy. Run migrations on deploy:"
echo "    python manage.py migrate --no-input"
