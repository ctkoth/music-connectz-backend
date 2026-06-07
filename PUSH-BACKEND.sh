#!/usr/bin/env bash
# PUSH-BACKEND.sh — push backend to GitHub
# Repo: https://github.com/ctkoth/music-connectz-backend
set -e
REPO_URL="https://github.com/ctkoth/music-connectz-backend.git"
MSG="backend v0.46 — OAuth disconnect + groups synced (Wave 20)"
echo "🧹 Resetting local git + build artifacts..."
rm -rf .git
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
rm -f db.sqlite3
echo "🌱 Init + commit..." && git init && git add . && git commit -m "$MSG" && git branch -M main
echo "🔗 Remote: $REPO_URL" && git remote add origin "$REPO_URL"
echo "🚀 Force-pushing..." && git push -f origin main
echo "✅ Backend pushed. Render auto-deploys."
echo ""
echo "Set OAuth env vars in Render → Environment:"
echo "  GOOGLE/SPOTIFY/SOUNDCLOUD/FACEBOOK/INSTAGRAM/TWITTER/TIKTOK/GITHUB/DISCORD/MICROSOFT _OAUTH_CLIENT_ID + _SECRET"
