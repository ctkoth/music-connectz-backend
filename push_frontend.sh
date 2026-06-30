#!/usr/bin/env bash
# push_frontend.sh — deploy the Music ConnectZ frontend to Vercel.
# Run from the ROOT of your frontend repo after copying these files in.
#
#   bash push_frontend.sh            # git push (auto-deploys if repo is linked)
#   bash push_frontend.sh vercel     # direct deploy via Vercel CLI
#
set -e

MODE="${1:-git}"
BRANCH="${2:-main}"

if [ ! -f package.json ]; then
  echo "!! package.json not found. cd into your frontend repo root first."
  exit 1
fi

echo "==> Installing deps + test build"
npm install --no-audit --no-fund
npm run build

if [ "$MODE" = "vercel" ]; then
  echo "==> Deploying with Vercel CLI"
  npx vercel --prod
else
  echo "==> Committing + pushing (Vercel auto-deploys linked repos)"
  git add -A
  git commit -m "MimeZ + DirectZ SkillZ UI; OAuth register/login (username/email/phone)" || echo "(nothing to commit)"
  git push origin "$BRANCH"
fi

echo "==> Done."
echo "   Set these in Vercel → Settings → Environment Variables:"
echo "     VITE_API_BASE=https://admin.musicconnectz.net"
echo "     VITE_GOOGLE_CLIENT_ID, VITE_GITHUB_CLIENT_ID, VITE_APPLE_CLIENT_ID"
echo "     VITE_OAUTH_REDIRECT=https://musicconnectz.net/oauth/callback"
