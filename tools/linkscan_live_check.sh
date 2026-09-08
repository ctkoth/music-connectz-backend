#!/usr/bin/env bash
# Prove the link scanner against the REAL API, whichever one you're licensed for.
#
# Why this exists: apps/economy/links.py talks to Google over HTTP and every
# test of it stubs urlopen. A stub pins the protocol we BELIEVE in and cannot
# tell us we believed the wrong thing — and here that failure is invisible,
# because `safe_browsing_check` answers "safe" on any error. A wrong URL, a
# wrong method, a key with the wrong API enabled, an unbilled project: every
# one of them looks identical to a platform where no link is ever malicious.
#
# So run this after setting a key, after rotating one, and after touching the
# scan. It costs two lookups.
#
#   1. a URL Google publishes as a test threat -> must come back FLAGGED
#   2. a URL that is obviously fine            -> must come back CLEAN
#
# Step 1 is the one that matters. A scanner that says "clean" to everything
# passes a check that only ever asks about clean things.
#
#   WEB_RISK_API_KEY=...      ./tools/linkscan_live_check.sh
#   SAFE_BROWSING_API_KEY=... ./tools/linkscan_live_check.sh
set -uo pipefail

MALWARE="http://testsafebrowsing.appspot.com/s/malware.html"
CLEAN="https://www.google.com/"

if [[ -n "${WEB_RISK_API_KEY:-}" ]]; then
  WHICH="Web Risk"
  lookup() {
    curl -sS -G "https://webrisk.googleapis.com/v1/uris:search" \
      --data-urlencode "key=${WEB_RISK_API_KEY}" \
      --data-urlencode "uri=$1" \
      -d threatTypes=MALWARE -d threatTypes=SOCIAL_ENGINEERING \
      -d threatTypes=UNWANTED_SOFTWARE
  }
  # Web Risk answers {} for a clean URL and {"threat":{...}} for a flagged one.
  flagged() { grep -q '"threat"' <<<"$1"; }
elif [[ -n "${SAFE_BROWSING_API_KEY:-}" ]]; then
  WHICH="Safe Browsing v4"
  lookup() {
    curl -sS -X POST \
      "https://safebrowsing.googleapis.com/v4/threatMatches:find?key=${SAFE_BROWSING_API_KEY}" \
      -H 'Content-Type: application/json' \
      -d "{\"client\":{\"clientId\":\"music-connectz\",\"clientVersion\":\"1.0\"},
           \"threatInfo\":{\"threatTypes\":[\"MALWARE\",\"SOCIAL_ENGINEERING\",
           \"UNWANTED_SOFTWARE\",\"POTENTIALLY_HARMFUL_APPLICATION\"],
           \"platformTypes\":[\"ANY_PLATFORM\"],\"threatEntryTypes\":[\"URL\"],
           \"threatEntries\":[{\"url\":\"$1\"}]}}"
  }
  flagged() { grep -q '"matches"' <<<"$1"; }
else
  echo "Set WEB_RISK_API_KEY (or SAFE_BROWSING_API_KEY) and run again." >&2
  exit 2
fi

echo "== $WHICH =="
fail=0

echo "-- a URL Google publishes as a threat: $MALWARE"
out=$(lookup "$MALWARE")
echo "$out"
if grep -q '"error"' <<<"$out"; then
  echo "!! the API returned an error. Read it above — the usual causes are the"
  echo "!! API not enabled on the project, billing off, or a key restricted to"
  echo "!! a different API." >&2
  fail=1
elif flagged "$out"; then
  echo "OK — flagged, which is what a working scanner does."
else
  echo "!! NOT flagged. The call succeeded and found nothing, which means the"
  echo "!! scanner is answering 'clean' to a known-bad URL — every member link"
  echo "!! would pass. Do not treat this as working." >&2
  fail=1
fi

echo
echo "-- a URL that is fine: $CLEAN"
out=$(lookup "$CLEAN")
echo "$out"
if grep -q '"error"' <<<"$out"; then
  echo "!! error on a clean URL too." >&2; fail=1
elif flagged "$out"; then
  echo "!! flagged a clean URL. Something is wrong with the request shape." >&2; fail=1
else
  echo "OK — clean."
fi

echo
[[ $fail -eq 0 ]] && echo "Scanner is live. WidgetZ page widgets can be cleared." \
                  || echo "Scanner is NOT working. Page widgets stay refused, which is correct."
exit $fail
