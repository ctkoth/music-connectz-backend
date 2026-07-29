# Serve `/.well-known/assetlinks.json` from the frontend

The Android app (`android/`) opens **`https://musicconnectz.net`** — the
frontend. Chrome verifies the app against the file on **that** host, so this
backend's route only covers `admin.musicconnectz.net`. Without the frontend
copy, the app opens with a visible URL bar.

## Vercel / any static frontend

Create **`public/.well-known/assetlinks.json`**:

```json
[
  {
    "relation": [
      "delegate_permission/common.handle_all_urls",
      "delegate_permission/common.get_login_creds"
    ],
    "target": {
      "namespace": "android_app",
      "package_name": "net.musicconnectz.app",
      "sha256_cert_fingerprints": [
        "REPLACE_WITH_PLAY_APP_SIGNING_SHA256",
        "REPLACE_WITH_UPLOAD_KEY_SHA256"
      ]
    }
  }
]
```

Files in `public/` are served at the domain root, so this lands at
`https://musicconnectz.net/.well-known/assetlinks.json`. It must be served over
HTTPS with `Content-Type: application/json` and **no redirect** — Google does not
follow one here.

## Where the fingerprints come from

**Play Console → Release → Setup → App signing.** List **both**:

- **App signing key certificate** SHA-256 — the copy your users install, because
  Play re-signs it.
- **Upload key certificate** SHA-256 — the build you sideload while testing.

For a locally signed debug/upload keystore:

```bash
keytool -list -v -keystore upload.jks -alias upload | grep -A1 SHA256
```

## Verify

Paste the site and package into the
[Statement List Generator & Tester](https://developers.google.com/digital-asset-links/tools/generator),
then install the app on a phone. **URL bar visible = verification failed.**

Keeping the two copies identical is easiest if you generate them from the same
values the backend uses (`TWA_PACKAGE_NAME`, `TWA_SHA256_FINGERPRINTS` — see
`apps/omviardz/wellknown.py`).
