#!/usr/bin/env bash
# Prove Parcel Primate's send path against the REAL SendGrid API.
#
# Why this exists: apps/economy/parcelprimate.py's _send_one() has never run
# against SendGrid — CI has no key, and every test of the module stubs
# `requests`. A stub pins the protocol we BELIEVE SendGrid's v3 Mail Send API
# wants and cannot tell us we believed the wrong thing (wrong auth header
# shape, wrong content type, a from-address SendGrid hasn't verified).
#
# Run it after setting SENDGRID_API_KEY, after rotating it, and after
# touching the send code. It costs exactly one real email send — point it at
# an address YOU control and can check.
#
#   SENDGRID_API_KEY=...  PARCEL_TEST_TO=you@example.com  ./tools/parcelprimate_live_check.sh
#
# It does not touch the database or go through Django at all — this is a
# transport check, not an integration test, so it can be run with nothing
# but the key and curl.

set -euo pipefail

if [ -z "${SENDGRID_API_KEY:-}" ]; then
  echo "SENDGRID_API_KEY is not set — nothing to check." >&2
  exit 1
fi
if [ -z "${PARCEL_TEST_TO:-}" ]; then
  echo "Set PARCEL_TEST_TO to an address you control and can check for delivery." >&2
  exit 1
fi

FROM="${PARCEL_FROM_EMAIL:-no-reply@musicconnectz.com}"

BODY=$(cat <<JSON
{
  "personalizations": [{"to": [{"email": "${PARCEL_TEST_TO}"}]}],
  "from": {"email": "${FROM}"},
  "subject": "Parcel Primate live check",
  "content": [{"type": "text/plain", "value": "If you got this, the real SendGrid send path works.\n\n---\nUnsubscribe: https://example.invalid/unsubscribe/0/test/"}]
}
JSON
)

HTTP_CODE=$(curl -sS -o /tmp/parcelprimate_live_check.out -w "%{http_code}" \
  -X POST "https://api.sendgrid.com/v3/mail/send" \
  -H "Authorization: Bearer ${SENDGRID_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "${BODY}")

echo "HTTP ${HTTP_CODE}"
cat /tmp/parcelprimate_live_check.out || true
echo

if [ "$HTTP_CODE" = "202" ]; then
  echo "OK — SendGrid accepted the send. Check ${PARCEL_TEST_TO} for delivery, and click the unsubscribe link in a real send to confirm that endpoint separately."
  exit 0
else
  echo "FAILED — SendGrid did not accept the send (see body above)." >&2
  exit 1
fi
