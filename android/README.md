# Music ConnectZ + BodieZ — Android apps

Two apps from one project (Gradle product flavors), one Play listing each:

| Flavor | App | Package | Opens | Icon |
|---|---|---|---|---|
| `mcz` | Music ConnectZ | `net.musicconnectz.app` | `https://musicconnectz.net` | the equalizer mark |
| `bodiez` | BodieZ | `net.musicconnectz.bodiez` | `https://bodiez.musicconnectz.net` — the BodieZ-only web build, its own host | the neon athletes, same art as the in-app tab |

Each is a **Trusted Web Activity**: it opens its site full-screen in Chrome with
no URL bar, so the mobile web app *is* the Android app. That's
Google's sanctioned route for shipping a web app — a plain WebView wrapper gets
rejected under the minimum-functionality policy.

Both share one Kotlin file. Everything else is icons, splash, and link
verification — and the differences between the two apps are all in
`app/build.gradle.kts` (the flavors) and `app/src/bodiez/res/` (name, icon,
splash, colour).

## Get an APK

No Android Studio needed — GitHub → **Actions** → **Android APK** → **Run
workflow**, then download `music-connectz-apk` or `bodiez-apk`. The Play bundles
are `music-connectz-playstore-bundle` and `bodiez-playstore-bundle`.

Locally (needs the [Android SDK](https://developer.android.com/studio)):

```bash
./gradlew assembleBodiezDebug   # app/build/outputs/apk/bodiez/debug/app-bodiez-debug.apk
./gradlew bundleBodiezRelease   # app/build/outputs/bundle/bodiezRelease/app-bodiez-release.aab  (Play wants this)
./gradlew assembleMczDebug      # the Music ConnectZ equivalents
./gradlew bundleMczRelease
./gradlew assembleMczDebug -PsiteUrl=https://staging.musicconnectz.net
./gradlew bundleBodiezRelease -PbodiezUrl=https://bodiez.example.net   # a different host for BodieZ
```

**BodieZ opens its own site, not a path on the main one.** That site is the
BodieZ-only build in the frontend repo (`npm run build:bodiez`, folder
`dist-bodiez/`) and has to be hosted on the host named by `-PbodiezUrl`
(default `bodiez.musicconnectz.net`) before the app does anything. The reason is
policy as much as design: the main site's profile, orientation, substance and
attractiveness-rating screens, and its Premium purchase flow, are what make the
main app a Data safety and Play Billing question, and the BodieZ-only shell
contains none of them. See `play/bodiez/README.md` in the frontend repo.

## What's in it

| File | Does |
|---|---|
| `app/src/main/java/net/musicconnectz/app/MainActivity.kt` | The TWA launcher. In the `mcz` flavor it adds `?omviardz=1` on first launch so a new install opens the guided tour; BodieZ does not. |
| `app/src/main/AndroidManifest.xml` | Default URL, splash, deep-link filter, Chrome delegation service. Declares **no permissions**. |
| `app/src/main/res/values/strings.xml` | `asset_statements` — the app's half of link verification. |
| `app/src/main/res/drawable/ic_launcher_*.xml` | The wordless mark, generated. |
| `app/src/main/res/mipmap-anydpi-v26/` | Adaptive icon (+ monochrome for Android 13 themed icons). |
| `app/build.gradle.kts` | The two flavors, `siteUrl` property, release signing from env, asset-statement sync check. |
| `app/src/bodiez/res/` | BodieZ's name, adaptive icon, splash and ink colour. Overrides `main` for that flavor only. |

**The icons are generated — don't hand-edit them.** Change a colour or a bar in
[`tools/make_brand_assets.py`](../tools/make_brand_assets.py) and re-run it; the
same geometry feeds the SVG master, the Android vectors, and the Play Store PNGs.

```bash
python tools/make_brand_assets.py
```

**BodieZ's icon is the artwork members already see on the BodieZ tab**, not a
redrawn mark — a launcher icon that differs from the in-app one is two
identities for one app. It is generated from `brand/bodiez/source-384.png`:

```bash
python tools/make_bodiez_assets.py
```

That source is 384px, so the 512px Play icon and the 432px adaptive layers are
upscales. A larger master dropped in as `brand/bodiez/source-*.png` (and
`SOURCE` changed) sharpens everything with no other edit.

## Signing

Release signing reads four env vars, so no keystore is ever committed:

```
ANDROID_KEYSTORE_PATH  ANDROID_KEYSTORE_PASSWORD  ANDROID_KEY_ALIAS  ANDROID_KEY_PASSWORD
```

Unset → the release build stays unsigned, which Play can still sign on upload.
In CI the same values come from repository secrets (`ANDROID_KEYSTORE_BASE64`
holds the keystore).

## The one thing that will look broken

If the host an app opens doesn't list its signing fingerprint in
`/.well-known/assetlinks.json` — **each app has its own host and its own file**:
`musicconnectz.net` for Music ConnectZ, the BodieZ host for BodieZ — the app opens **with a URL bar** — and that's what
makes a Play reviewer call it a repackaged website. Setup and verification:
[GOOGLE_PLAY.md §5](../GOOGLE_PLAY.md#5-prove-the-app-owns-the-site-do-this-or-the-app-looks-broken)
and [`config_snippets/assetlinks_frontend.md`](../config_snippets/assetlinks_frontend.md).

## Before you publish

Read [GOOGLE_PLAY.md](../GOOGLE_PLAY.md). The short version of the risk: selling
Premium/StatZ/wallet top-ups inside the Android app requires **Google Play
Billing**, not Stripe. That's the most likely reason this app gets rejected.
