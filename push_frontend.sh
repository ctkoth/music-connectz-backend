#!/usr/bin/env bash
# Push the Music ConnectZ FRONTEND to GitHub (auto-deploys on Vercel).
# Usage:  bash push_frontend.sh ["commit message"]
set -euo pipefail
cd "$(dirname "$0")"
MSG="${1:-Frontend: creator icons + OAuth redirect capture; point API at admin.musicconnectz.net}"
REMOTE="https://github.com/ctkoth/-music-connectz-frontend-.git"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || git init
git remote get-url origin >/dev/null 2>&1 || git remote add origin "$REMOTE"

git add -A
git commit -m "$MSG" || { echo "Nothing to commit."; exit 0; }
git push -u origin HEAD:main
echo "✓ Frontend pushed → Vercel will build musicconnectz.net"
