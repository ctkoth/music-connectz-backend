#!/usr/bin/env bash
# Prove the coach's big-take path against the REAL Gemini API.
#
# Why this exists: apps/economy/gemini_files.py and the model chain in
# gemini.py both shipped without ever running against Google. Neither CI nor a
# dev box has a key, so every test of them is a test of a stub — which pins the
# protocol we BELIEVE in, and cannot tell us we believed the wrong thing. This
# is the one check that can, and it needs nothing but a key.
#
# Run it after any change to the upload path or the model chain, and after a
# key or project rotation. It costs one generateContent call.
#
# Walks exactly what apps/economy/gemini_files.py does, in the same order, with
# the same headers — so a failure here is a failure there, at a named step,
# before a member ever sees it.
#
#   1. resumable upload: start   -> one-time upload URL (a response HEADER)
#   2. resumable upload: finalize-> {file: {uri, name, state}}
#   3. poll until state == ACTIVE
#   4. generateContent with a file_data part (NOT inline_data)
#   5. delete the file
#
# Usage:
#   GEMINI_API_KEY=... ./coach_live_check.sh [take.m4a]
#
# With no file it generates a ~30MB WAV — bigger than the 14MB inline ceiling,
# so it is guaranteed to exercise the upload road rather than the old one.
# It is silence, so expect a poor score and no useful coaching: this is a test
# of the TRANSPORT, not of the rubric. A score coming back at all is the pass.

set -uo pipefail
KEY="${GEMINI_API_KEY:-}"
[ -n "$KEY" ] || { echo "set GEMINI_API_KEY (Render → Environment)"; exit 1; }

MODEL="${GEMINI_AUDIO_MODEL:-gemini-2.5-flash}"
B=https://generativelanguage.googleapis.com
TAKE="${1:-}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

if [ -z "$TAKE" ]; then
  TAKE="$TMP/take.wav"; MIME=audio/wav
  echo "→ generating a 30MB WAV (no file given)…"
  python3 - "$TAKE" <<'PY'
import struct, sys
rate, secs = 44100, 350          # ~30MB of 16-bit mono PCM
n = rate * secs
hdr = b'RIFF' + struct.pack('<I', 36 + n*2) + b'WAVEfmt ' + struct.pack(
    '<IHHIIHH', 16, 1, 1, rate, rate*2, 2, 16) + b'data' + struct.pack('<I', n*2)
with open(sys.argv[1], 'wb') as f:
    f.write(hdr)
    f.write(b'\x00\x00' * n)
PY
else
  case "$TAKE" in
    *.m4a|*.mp4) MIME=video/mp4 ;; *.mp3) MIME=audio/mpeg ;;
    *.wav) MIME=audio/wav ;; *.ogg) MIME=audio/ogg ;;
    *.webm) MIME=video/webm ;; *) MIME=audio/mpeg ;;
  esac
fi

SIZE=$(wc -c < "$TAKE")
echo "→ take: $TAKE  ${MIME}  $((SIZE/1024/1024))MB"
[ "$SIZE" -gt $((14*1024*1024)) ] \
  || echo "  ! under the 14MB inline ceiling — this will NOT test the upload road"

echo "→ 1/5 start resumable upload"
H="$TMP/h"
curl -sS -D "$H" -o "$TMP/start.json" -X POST "$B/upload/v1beta/files?key=$KEY" \
  -H "X-Goog-Upload-Protocol: resumable" -H "X-Goog-Upload-Command: start" \
  -H "X-Goog-Upload-Header-Content-Length: $SIZE" \
  -H "X-Goog-Upload-Header-Content-Type: $MIME" \
  -H "Content-Type: application/json" \
  -d "{\"file\":{\"display_name\":\"live check\"}}" || { echo "  ✗ unreachable"; exit 1; }
PUT=$(tr -d '\r' < "$H" | awk 'tolower($1)=="x-goog-upload-url:"{print $2}')
[ -n "$PUT" ] || { echo "  ✗ no X-Goog-Upload-URL header"; cat "$H" "$TMP/start.json"; exit 1; }
echo "  ✓ got a one-time upload URL"

echo "→ 2/5 upload + finalize ($((SIZE/1024/1024))MB)"
curl -sS -o "$TMP/up.json" -X POST "$PUT" \
  -H "Content-Length: $SIZE" -H "X-Goog-Upload-Offset: 0" \
  -H "X-Goog-Upload-Command: upload, finalize" \
  --data-binary "@$TAKE" || { echo "  ✗ upload failed"; exit 1; }
URI=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["file"]["uri"])' "$TMP/up.json" 2>/dev/null)
NAME=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["file"]["name"])' "$TMP/up.json" 2>/dev/null)
[ -n "$URI" ] || { echo "  ✗ no uri in reply:"; head -c 400 "$TMP/up.json"; exit 1; }
echo "  ✓ $NAME"

echo "→ 3/5 wait for ACTIVE"
for i in $(seq 1 40); do
  ST=$(curl -sS "$B/v1beta/${NAME}?key=$KEY" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("state",""))' 2>/dev/null)
  [ "$ST" = "ACTIVE" ] && { echo "  ✓ ACTIVE after ${i} poll(s)"; break; }
  [ "$ST" = "FAILED" ] && { echo "  ✗ processing FAILED"; exit 1; }
  sleep 1.5
done
[ "$ST" = "ACTIVE" ] || { echo "  ✗ never went ACTIVE (last: ${ST:-unknown})"; exit 1; }

echo "→ 4/5 generateContent by URI on $MODEL"
cat > "$TMP/req.json" <<JSON
{"contents":[{"parts":[
  {"text":"Score this audio 1-10 for pitch and timing. Reply ONLY as JSON: {\"score\": <1-10>, \"verdict\": \"<one sentence>\"}"},
  {"file_data":{"mime_type":"$MIME","file_uri":"$URI"}}
]}]}
JSON
CODE=$(curl -sS -o "$TMP/gen.json" -w '%{http_code}' -X POST \
  "$B/v1beta/models/$MODEL:generateContent?key=$KEY" \
  -H "Content-Type: application/json" --data-binary "@$TMP/req.json")
echo "  HTTP $CODE"
head -c 700 "$TMP/gen.json"; echo

echo "→ 5/5 delete"
curl -sS -o /dev/null -w "  HTTP %{http_code}\n" -X DELETE "$B/v1beta/${NAME}?key=$KEY"

echo
[ "$CODE" = "200" ] \
  && echo "PASS — a $((SIZE/1024/1024))MB take went up, was read by URI, and came back scored." \
  || echo "FAIL at step 4 — the upload road works, generateContent did not. See the body above."
