# Music ConnectZ — Android app

A **Trusted Web Activity**: it opens `https://musicconnectz.net` full-screen in
Chrome with no URL bar, so the mobile web app *is* the Android app. That's
Google's sanctioned route for shipping a web app — a plain WebView wrapper gets
rejected under the minimum-functionality policy.

The whole app is one Kotlin file. Everything else is icons, splash, and link
verification.

## Get an APK

No Android Studio needed — GitHub → **Actions** → **Android APK** → **Run
workflow**, then download the `music-connectz-apk` artifact.

Locally (needs the [Android SDK](https://developer.android.com/studio)):

```bash
./gradlew assembleDebug     # app/build/outputs/apk/debug/app-debug.apk
./gradlew bundleRelease     # app/build/outputs/bundle/release/app-release.aab  (Play wants this)
./gradlew assembleDebug -PsiteUrl=https://staging.musicconnectz.net
```

## What's in it

| File | Does |
|---|---|
| `app/src/main/java/net/musicconnectz/app/MainActivity.kt` | The TWA launcher. Adds `?omviardz=1` on first launch so a new install opens the guided tour. |
| `app/src/main/AndroidManifest.xml` | Default URL, splash, deep-link filter, Chrome delegation service. Declares **no permissions**. |
| `app/src/main/res/values/strings.xml` | `asset_statements` — the app's half of link verification. |
| `app/src/main/res/drawable/ic_launcher_*.xml` | The wordless mark, generated. |
| `app/src/main/res/mipmap-anydpi-v26/` | Adaptive icon (+ monochrome for Android 13 themed icons). |
| `app/build.gradle.kts` | `siteUrl` property, release signing from env, asset-statement sync check. |

**The icons are generated — don't hand-edit them.** Change a colour or a bar in
[`tools/make_brand_assets.py`](../tools/make_brand_assets.py) and re-run it; the
same geometry feeds the SVG master, the Android vectors, and the Play Store PNGs.

```bash
python tools/make_brand_assets.py
```

## Signing

Release signing reads four env vars, so no keystore is ever committed:

```
ANDROID_KEYSTORE_PATH  ANDROID_KEYSTORE_PASSWORD  ANDROID_KEY_ALIAS  ANDROID_KEY_PASSWORD
```

Unset → the release build stays unsigned, which Play can still sign on upload.
In CI the same values come from repository secrets (`ANDROID_KEYSTORE_BASE64`
holds the keystore).

## The one thing that will look broken

If `https://musicconnectz.net/.well-known/assetlinks.json` doesn't list this
app's signing fingerprint, the app opens **with a URL bar** — and that's what
makes a Play reviewer call it a repackaged website. Setup and verification:
[GOOGLE_PLAY.md §5](../GOOGLE_PLAY.md#5-prove-the-app-owns-the-site-do-this-or-the-app-looks-broken)
and [`config_snippets/assetlinks_frontend.md`](../config_snippets/assetlinks_frontend.md).

## Before you publish

Read [GOOGLE_PLAY.md](../GOOGLE_PLAY.md). The short version of the risk: selling
Premium/StatZ/wallet top-ups inside the Android app requires **Google Play
Billing**, not Stripe. That's the most likely reason this app gets rejected.
