#!/usr/bin/env bash
# The only check that can tell you pass 2 and the gear advice work against the
# REAL Anthropic API. The test suite stubs the SDK; nothing in CI has a key.
#   ANTHROPIC_API_KEY=... ./tools/coach_think_live_check.sh
# Costs a few cents (one logic pass, one gear-advice run with up to 4 searches).
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY}"
PY="${PYTHON:-python}"
DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-music_connectz.settings}" "$PY" - <<'PY'
import django, json
django.setup()
from apps.economy import coach_think, coach_upgrades
from apps.economy.deadline import Deadline
payload = {"score": 6, "scores": {"pitch": 4, "tone": 7, "breath": 6, "range": 6, "agility": 6, "style_match": 5},
           "verdict": "v", "now": "n", "goal": "g", "strengths": ["tone"], "fixes": ["prop your ribcage upright"],
           "next_drill": "lip trills", "rated_lyrics": False, "rated_mix": False,
           "heard": [{"t": "0:24", "what": "Pitch sags under the long note.", "dim": "pitch", "confidence": 3}]}
out = coach_think.apply("singz", payload, user=None, genre="R&B", target="tenor",
                        difficulty="builder", style="", deadline=Deadline(120), trial=True)
print("PASS 2:", json.dumps({k: out.get(k) for k in ("think", "verdict", "fixes_detail", "honesty")}, indent=2, ensure_ascii=False))
from types import SimpleNamespace as NS
take = NS(pk=0, app_key="singz", overall=6, scores=payload["scores"], weakest="pitch", genre="R&B",
          target="tenor", style="", difficulty="builder", upgrades={"context": {"heard": payload["heard"]}})
res, _, err = coach_upgrades.run_model(take, None, coach_upgrades.DEFAULT_MARKETS, Deadline(100))
print("UPGRADES err:", err)
if res:
    print(json.dumps(res, indent=2, ensure_ascii=False)[:6000])
    assert res["references"], "no verified references came back"
