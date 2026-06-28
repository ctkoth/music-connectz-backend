#!/usr/bin/env bash
# Termux-friendly push for the Music ConnectZ frontend (MimeZ + OAuth drop).
# Run from the root of your local frontend repo clone.
set -e

echo "==> Music ConnectZ frontend push (MimeZ + OAuth)"

git add src/mimez src/auth src/icons/CUSTOM_ICONS_mimez_snippet.js \
        public/icons/Personaz_Mime.png INTEGRATION_MIMEZ_FRONTEND.md 2>/dev/null || git add -A

git status --short

MSG="${1:-Add MimeZ studio + OAuth buttons (Google/GitHub/Apple)}"
git commit -m "$MSG" || echo "(nothing to commit)"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "==> Pushing to origin/$BRANCH"
if ! git push origin "$BRANCH"; then
  echo "!! Push rejected. Pulling with rebase and retrying..."
  git pull --rebase origin "$BRANCH"
  git push origin "$BRANCH"
fi
echo "==> Done. Vercel will auto-deploy. Remember to wire the /mime route,"
echo "    merge MIMEZ_ICONS, add <OAuthButtons/>, and call captureOAuthTokens()."
