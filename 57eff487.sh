#!/bin/bash

# ─────────────────────────────────────────
# Music ConnectZ — Frontend GitHub Upload
# Usage: bash upload-frontend.sh
# ─────────────────────────────────────────

REPO_PATH="/storage/emulated/0/Download/mcz-frontend-repo-30/frontend-repo"
GITHUB_REPO="https://github.com/ctkoth/-music-connectz-frontend-.git"
COMMIT_MSG="${1:-Update frontend $(date '+%Y-%m-%d %H:%M')}"

echo ""
echo "🎵 Music ConnectZ — Frontend Upload Script"
echo "─────────────────────────────────────────"
echo ""

# Check if folder exists
if [ ! -d "$REPO_PATH" ]; then
  echo "❌ Folder not found: $REPO_PATH"
  echo "👉 Enter your frontend folder path manually:"
  read -r REPO_PATH
fi

cd "$REPO_PATH" || { echo "❌ Cannot enter folder. Check the path."; exit 1; }

echo "📁 Folder: $REPO_PATH"
echo ""

# Fix Android dubious ownership issue
git config --global --add safe.directory "$REPO_PATH"

# Check if git is initialized
if [ ! -d ".git" ]; then
  echo "🔧 No git repo found — initializing..."
  git init
  git remote add origin "$GITHUB_REPO"
  git branch -M main
  echo "✅ Git initialized and remote set."
else
  # Make sure remote is set correctly
  git remote set-url origin "$GITHUB_REPO" 2>/dev/null || git remote add origin "$GITHUB_REPO"
  echo "✅ Git repo detected."
fi

echo ""
echo "📦 Staging all files..."
git add -A

echo ""
echo "📝 Committing: $COMMIT_MSG"
git commit -m "$COMMIT_MSG"

echo ""
echo "🚀 Pushing to GitHub..."
git push -u origin main

STATUS=$?
echo ""
if [ $STATUS -eq 0 ]; then
  echo "✅ Upload complete!"
  echo "🔗 View at: https://github.com/ctkoth/-music-connectz-frontend-"
else
  echo "⚠️  Push failed. If this is an auth issue, GitHub needs a Personal Access Token."
  echo "👉 Create one at: https://github.com/settings/tokens"
  echo "   Scope needed: repo (full control)"
  echo ""
  echo "Then run this to save your credentials:"
  echo "   git config --global credential.helper store"
  echo "   git push -u origin main"
  echo "   (enter: username=ctkoth, password=YOUR_TOKEN)"
fi
