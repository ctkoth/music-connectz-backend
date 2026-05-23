#!/usr/bin/env bash
# PUSH-TO-GITHUB.sh
# Run this AFTER unzipping. It force-replaces your GitHub repo with v0.33 backend.
# Requires: git installed + you've authenticated to github (`gh auth login` or HTTPS token)

set -e  # exit on first error

REPO_URL="https://github.com/ctkoth/music-connectz-backend.git"
COMMIT_MSG="v0.33 clean push - 16 apps, JWT auth, OAuth, all migrations, Wave 1-4"

echo "🧹 Cleaning local git state..."
rm -rf .git

echo "🌱 Initializing fresh git repo..."
git init
git add .
git status | tail -5

echo ""
echo "📦 Committing all files..."
git commit -m "$COMMIT_MSG"
git branch -M main

echo "🔗 Connecting to GitHub..."
git remote add origin "$REPO_URL"

echo ""
echo "🚀 FORCE-PUSHING to GitHub (overwrites everything in the remote repo)..."
echo "If prompted, paste your GitHub Personal Access Token (or use 'gh auth login' first)"
git push -f origin main

echo ""
echo "✅ DONE. Now go to dashboard.render.com → music-connectz-backend → Manual Deploy → Clear build cache & deploy"
echo ""
echo "Verify on GitHub: https://github.com/ctkoth/music-connectz-backend"
echo "Should show: apps/ folder + music_connectz/ folder + Procfile + requirements.txt + render.yaml + runtime.txt"
