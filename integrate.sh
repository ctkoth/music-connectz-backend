#!/usr/bin/env bash
# Integrate the creator apps into your EXISTING music-connectz-backend repo.
# Usage: cd into your cloned repo root, then:  bash /path/to/this/integrate.sh
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
REPO="https://github.com/ctkoth/music-connectz-backend"
BRANCH="${1:-creator-appz}"   # pass 'main' to target main (auto-deploys)

[ -f music_connectz/settings.py ] || { echo "✗ Run from your backend repo root."; exit 1; }
[ -d apps/accounts ] || { echo "✗ apps/accounts not found — wrong repo?"; exit 1; }

echo "==> backing up settings.py + urls.py"
cp music_connectz/settings.py music_connectz/settings.py.bak
cp music_connectz/urls.py music_connectz/urls.py.bak 2>/dev/null || true

echo "==> copying new app packages"
cp -r "$SRC/apps/." apps/

echo "==> patching INSTALLED_APPS (idempotent)"
python3 - <<'PY'
s = open("music_connectz/settings.py").read()
if "apps.skillz" in s:
    print("   already present, skipping")
else:
    adds = ["apps.common","apps.skillz","apps.designz","apps.shotz","apps.writez",
            "apps.managez","apps.developz","apps.producez","apps.mixez","apps.scoutz","apps.dawz"]
    block = "\n    # ── Creator apps + SkillZ + DawZ + ScoutZ + gates ──\n" + "".join(f"    '{a}',\n" for a in adds)
    anchor = "    'apps.notifications',\n"
    if anchor in s: s = s.replace(anchor, anchor + block, 1)
    else:
        i = s.index("INSTALLED_APPS"); j = s.index("]", i); s = s[:j] + block + s[j:]
    open("music_connectz/settings.py","w").write(s); print("   INSTALLED_APPS patched")
PY

echo "==> installing merged urls.py"
cp "$SRC/music_connectz/urls.py" music_connectz/urls.py

echo "==> sanity check"
python3 manage.py check || { echo "✗ check failed — restoring backups"; mv music_connectz/settings.py.bak music_connectz/settings.py; mv music_connectz/urls.py.bak music_connectz/urls.py 2>/dev/null||true; exit 1; }

echo "==> commit + push to '$BRANCH'"
git checkout -B "$BRANCH"
git add apps music_connectz/urls.py music_connectz/settings.py
git commit -m "Add creator apps + SkillZ + DawZ + ScoutZ + age/tier gates + age verification" || { echo "nothing to commit"; exit 0; }
git push -u origin "$BRANCH"
echo
echo "✓ pushed. Next:"
echo "  • Render Pre-Deploy: python manage.py migrate && python manage.py seed_skillz && python manage.py seed_dawz"
echo "  • Set env MCZ_KYC_SECRET=<random> and call /api/me/age/verify-adult/ from your KYC webhook"
echo "  • Go live: merge '$BRANCH' to main, or re-run: bash integrate.sh main"
echo "  • PR: $REPO/compare/$BRANCH?expand=1"
