"""Digital Asset Links — proves the Android app and the website are the same us.

The Play-sanctioned way to ship a web app is a Trusted Web Activity: the app
opens the real site full-screen with no browser chrome. Chrome only drops the
URL bar if it can fetch ``https://<origin>/.well-known/assetlinks.json`` and
find the app's signing certificate fingerprint in it. Fail that check and the
app still works but shows a URL bar — which looks broken and reads as a
repackaged website to a Play reviewer.

Configure on Render, then verify with:
  https://developers.google.com/digital-asset-links/tools/generator

    TWA_PACKAGE_NAME=net.musicconnectz.app
    TWA_SHA256_FINGERPRINTS=AA:BB:CC:…   (comma-separate several)

Use the fingerprint Play shows under **Release > Setup > App signing** — Play
re-signs your upload, so the upload key fingerprint alone will not verify the
production app. List both (upload + Play) while you're testing.
"""
import os

from django.http import JsonResponse
from django.views import View


def _fingerprints():
    raw = os.environ.get("TWA_SHA256_FINGERPRINTS", "")
    out = []
    for fp in raw.replace(" ", "").split(","):
        fp = fp.strip().upper()
        if fp and fp not in out:
            out.append(fp)
    return out


def assetlinks_payload(package=None, fingerprints=None):
    package = package or os.environ.get("TWA_PACKAGE_NAME", "net.musicconnectz.app")
    fingerprints = fingerprints if fingerprints is not None else _fingerprints()
    if not fingerprints:
        return []
    return [
        {
            "relation": [
                "delegate_permission/common.handle_all_urls",
                "delegate_permission/common.get_login_creds",
            ],
            "target": {
                "namespace": "android_app",
                "package_name": package,
                "sha256_cert_fingerprints": fingerprints,
            },
        }
    ]


class AssetLinksView(View):
    """GET /.well-known/assetlinks.json — public, unauthenticated by design.

    Serves ``[]`` until the fingerprints are set. An empty list is valid JSON
    that simply verifies nothing, which is the honest answer before a signing
    key exists — and it keeps the route from 404ing while you set Play up.
    """

    def get(self, _request):
        return JsonResponse(assetlinks_payload(), safe=False)
