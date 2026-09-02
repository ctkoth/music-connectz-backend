#!/usr/bin/env bash
# Does the keyboard's voice actually work against Google?
#
# Same reason tools/coach_live_check.sh exists. `MODEL_CHAINS["tts"]` and the
# PCM-to-WAV wrap in keyconnectz.py have never run against the real API — CI
# has no key and neither does a dev box, so every test of them stubs
# `requests`. A stubbed suite going green pins the protocol we BELIEVE in and
# cannot tell us we believed the wrong thing.
#
# This walks the real call, in the same shape the code sends it, and writes the
# audio out so you can listen to it rather than trust a byte count.
#
#     GEMINI_API_KEY=... ./tools/keyvoice_live_check.sh [text] [language]
#
# It costs one generateContent call.
set -o errexit
set -o pipefail

: "${GEMINI_API_KEY:?set GEMINI_API_KEY}"
TEXT="${1:-Where is the studio?}"
LANG_NAME="${2:-Yoruba}"
OUT="${TMPDIR:-/tmp}/keyvoice-check.wav"
BASE="https://generativelanguage.googleapis.com/v1beta"

# Deliberately the SECOND name in the chain is not tried here: this check is
# about whether the first one works, and a silent fallback would hide exactly
# the failure it exists to find.
MODEL="${GEMINI_TTS_MODEL:-gemini-2.5-flash-preview-tts}"

echo "==> asking $MODEL to read: \"$TEXT\" in $LANG_NAME"
BODY=$(python3 - "$TEXT" "$LANG_NAME" <<'PY'
import json, sys
text, lang = sys.argv[1], sys.argv[2]
print(json.dumps({
    "contents": [{"parts": [{"text":
        f"Read the following aloud in {lang}, naturally, as a native speaker "
        f"would say it. Read ONLY these words and add nothing:\n\n{text}"}]}],
    "generationConfig": {
        "responseModalities": ["AUDIO"],
        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}},
    },
}))
PY
)

RESP=$(curl -sS -X POST "$BASE/models/$MODEL:generateContent?key=$GEMINI_API_KEY" \
  -H 'Content-Type: application/json' -d "$BODY")

# The whole point: prove the reply carries inline audio, and that the mime type
# is still the PCM one _wav() is built for. A model that starts returning a
# container instead would make the header we add wrong rather than missing,
# which is the failure that would sound like a corrupt file to a member.
python3 - "$OUT" <<PY
import base64, json, struct, sys
resp = json.loads('''$RESP''')
if "candidates" not in resp:
    print("!! no candidates —", json.dumps(resp)[:400]); sys.exit(1)
part = resp["candidates"][0]["content"]["parts"][0]["inline_data"]
mime = part.get("mime_type", "")
pcm = base64.b64decode(part["data"])
print(f"==> mime={mime}  pcm={len(pcm)} bytes")
if "pcm" not in mime.lower():
    print("!! NOT raw PCM any more — _wav() in keyconnectz.py would corrupt this")
    sys.exit(1)
rate = 24000
for bit in mime.split(";"):
    if bit.strip().startswith("rate="):
        rate = int(bit.strip()[5:])
print(f"==> rate={rate}")
block = 1 * 16 // 8
wav = (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
       + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * block, block, 16)
       + b"data" + struct.pack("<I", len(pcm)) + pcm)
open(sys.argv[1], "wb").write(wav)
print(f"==> wrote {sys.argv[1]} ({len(wav)} bytes)")
PY

echo "==> OK. Play it and check it says the words, in the right language:"
echo "    $OUT"
