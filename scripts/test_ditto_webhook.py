import argparse
import hashlib
import hmac
import json
from datetime import datetime, timezone

import requests


def build_payload(args):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "event_type": args.event_type,
        "status": args.status,
        "provider_release_id": args.provider_release_id,
        "local_release_id": args.local_release_id,
        "event_time": now,
        "data": {
            "provider_release_id": args.provider_release_id,
            "status": args.status,
            "note": args.note,
        },
    }


def compute_signature(secret, body_bytes):
    return hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


def main():
    parser = argparse.ArgumentParser(
        description="Send a signed Ditto-style webhook to the Music ConnectZ backend."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--provider", default="ditto", help="Provider key in webhook route")
    parser.add_argument("--secret", required=True, help="DITTO_WEBHOOK_SECRET value")
    parser.add_argument("--provider-release-id", required=True, help="Provider release id to match")
    parser.add_argument("--local-release-id", type=int, default=0, help="Optional local release id fallback")
    parser.add_argument("--event-type", default="release.updated", help="Webhook event type")
    parser.add_argument("--status", default="processing", help="Provider status value")
    parser.add_argument("--note", default="manual webhook test", help="Optional note for payload data")
    parser.add_argument("--timeout", type=int, default=20, help="Request timeout in seconds")

    args = parser.parse_args()

    endpoint = f"{args.base_url.rstrip('/')}/api/distribution/webhooks/{args.provider}/"
    payload = build_payload(args)
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = compute_signature(args.secret, body)

    headers = {
        "Content-Type": "application/json",
        "X-Ditto-Signature": signature,
    }

    print("POST", endpoint)
    print("X-Ditto-Signature:", signature)
    print("Payload:")
    print(json.dumps(payload, indent=2))

    response = requests.post(endpoint, data=body, headers=headers, timeout=args.timeout)

    print("Response status:", response.status_code)
    try:
        print(json.dumps(response.json(), indent=2))
    except Exception:
        print(response.text)


if __name__ == "__main__":
    main()
