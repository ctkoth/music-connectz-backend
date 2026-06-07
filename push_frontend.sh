#!/bin/bash
# push_frontend.sh — pushes music-connectz-frontend to GitHub
# Usage: ./push_frontend.sh "commit message"

set -e

REPO="https://github.com/ctkoth/-music-connectz-frontend-.git"
MSG="${1:-feat: rebuild frontend v0.58 with auth, feed, profile, api client}"

echo "==> Initializing frontend repo..."
cd "$(dirname "$0")"

git init
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO"

git add -A
git commit -m "$MSG"

echo "==> Pushing to $REPO..."
git push -u origin main --force

echo "✅ Frontend pushed to GitHub."
echo ""
echo "⚠️  Set these env vars in Vercel dashboard:"
echo "   VITE_API_URL=https://<your-render-service>.onrender.com"
echo "   VITE_STRIPE_PUBLISHABLE_KEY=pk_live_..."
echo ""
echo "📦 Build settings for Vercel:"
echo "   Build Command:  npm run build"
echo "   Output Dir:     dist"
echo "   Install:        npm install"
