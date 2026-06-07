#!/usr/bin/env bash
# Add the creator-apps frontend to your music-connectz-frontend repo.
# Usage: cd into your cloned frontend repo root, then: bash /path/to/this/push.sh
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
REPO="https://github.com/ctkoth/-music-connectz-frontend-"
BRANCH="${1:-creator-appz}"
[ -d src ] || { echo "✗ Run from your frontend repo root (no src/ here)."; exit 1; }
[ -f src/lib/api.js ] || echo "  note: src/lib/api.js not found — components import ../lib/api.js; make sure yours is there."
mkdir -p src/creator-appz
cp -r "$SRC/creator-appz/." src/creator-appz/
mkdir -p public/icons
cp -r "$SRC/public/icons/." public/icons/ 2>/dev/null || true
git checkout -B "$BRANCH"
git add src/creator-appz public/icons
git commit -m "Add creator app pages + SkillZ training + DawZ voting + badges + profile progress + tier gating" || { echo "nothing to commit"; exit 0; }
git push -u origin "$BRANCH"
echo
echo "✓ pushed src/creator-appz/. Next:"
echo "  • wire the tabs in src/App.jsx (see creator-appz/README_INTEGRATE inside)"
echo "  • prod needs no env change — vercel.json already proxies /api/* to your backend"
echo "  • local dev only: set VITE_API_BASE=https://admin.musicconnectz.net"
echo "  • PR: $REPO/compare/$BRANCH?expand=1"
