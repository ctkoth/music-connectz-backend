# Music ConnectZ on Google Play — join, ship, and survive review

Everything needed to get the Android app into the Play Store, in the order you
actually do it. Links go to Google's own docs so you're never taking my word for
a policy that moves.

**What we're shipping:** `android/` is a **Trusted Web Activity** (TWA) — a thin
Android app that opens `https://musicconnectz.net` full-screen in Chrome with no
URL bar. That's Google's *sanctioned* way to publish a web app
([docs](https://developer.chrome.com/docs/android/trusted-web-activity/)), which
matters because a plain WebView wrapper gets rejected (see
[§9](#9-the-three-things-most-likely-to-get-you-rejected)). The mobile design
work lives in the web app, so the Android app inherits it — and OmviardZ opens
on first launch so a brand-new install gets Corey's guided tour instead of a
stranger's feed.

---

## 1. What you need before you touch the Console

| Thing | Why | Where it comes from |
|---|---|---|
| $25 (one-time) | Registration fee | Card, at signup |
| Government ID + address + phone | Mandatory identity verification | You |
| A privacy policy at a public URL | Required for every app | Publish on `musicconnectz.net/privacy` |
| A working account-deletion path | [Required](https://support.google.com/googleplay/android-developer/answer/13327111) for any app with sign-in | ✅ already built: `POST /api/economy/account/delete/` — needs a **web page** too |
| Test login credentials | Reviewers can't get past your login screen without them | Make a real account for review |
| 12 real testers | New personal accounts must run a closed test first (§8) | Friends, artists, group chat |
| The signing key | Every APK/AAB must be signed | §4 |

⚠️ **Account deletion needs a web URL, not just the API.** Google requires a
deletion route reachable *outside* the app. Add a page on the frontend that
calls `POST /api/economy/account/delete/` and give Play that URL.

---

## 2. Create the developer account

1. Go to **[play.google.com/console/signup](https://play.google.com/console/signup)**.
2. Choose the account type — this decision is hard to undo:
   - **Personal** — fast, but you must complete the 12-tester closed test before
     you can go to production
     ([policy](https://support.google.com/googleplay/android-developer/answer/14151465)).
   - **Organization** — needs a
     [D-U-N-S number](https://support.google.com/googleplay/android-developer/answer/13628312)
     (free, takes ~1–2 weeks from Dun & Bradstreet), and shows your business
     name as the developer instead of your legal name. If Music ConnectZ is an
     LLC, this is the one you want.
3. Pay the $25 and complete
   [identity verification](https://support.google.com/googleplay/android-developer/answer/13628312).
   Budget a few days — nothing else can start until it clears.
4. Set up a
   [payments profile](https://support.google.com/googleplay/android-developer/answer/9859434)
   if you'll ever charge money. Required before you can sell anything.

**Docs:** [Developer Policy Center](https://play.google.com/about/developer-content-policy/) ·
[Console home](https://play.google.com/console) ·
[Play Academy course (free, ~2h)](https://playacademy.exceedlms.com/student/catalog)

---

## 3. Build the app

You don't need Android Studio. The build runs in CI and hands you the files:

1. GitHub → **Actions** → **Android APK** → **Run workflow**.
2. When it finishes, download the artifacts:
   - `music-connectz-apk` → **`app-debug.apk`** — sideload this on your own
     phone to test.
   - `music-connectz-playstore-bundle` → **`app-release.aab`** — this is what
     Play wants. [App bundles are mandatory](https://developer.android.com/guide/app-bundle)
     for new apps; you cannot upload an APK.

To install the APK on your phone: copy it over, tap it, allow "install unknown
apps" for your file manager. To build locally instead (needs the
[Android SDK](https://developer.android.com/studio)):

```bash
cd android
./gradlew assembleDebug          # -> app/build/outputs/apk/debug/app-debug.apk
./gradlew bundleRelease          # -> app/build/outputs/bundle/release/app-release.aab
./gradlew assembleDebug -PsiteUrl=https://staging.musicconnectz.net   # point elsewhere
```

---

## 4. Sign it

Play re-signs your app with a key it holds
([Play App Signing](https://support.google.com/googleplay/android-developer/answer/9842756),
mandatory for new apps). You still need your own **upload key**:

```bash
keytool -genkeypair -v -keystore upload.jks -alias upload \
  -keyalg RSA -keysize 2048 -validity 10000
```

🔐 **Back up `upload.jks` and its passwords somewhere you won't lose them.**
Losing the upload key is recoverable (Google can reset it); losing it *and* your
account access is not.

Never commit it. To sign in CI, add these repository secrets
(Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | `base64 -w0 upload.jks` |
| `ANDROID_KEYSTORE_PASSWORD` | keystore password |
| `ANDROID_KEY_ALIAS` | `upload` |
| `ANDROID_KEY_PASSWORD` | key password |

Without them the release bundle is built unsigned, which still uploads fine —
Play's flow can sign it for you. With them, the bundle arrives signed.

---

## 5. Prove the app owns the site (do this or the app looks broken)

A TWA only hides the URL bar when Chrome can verify the app and the site claim
each other. Two halves:

**The app's half** — already in `android/app/src/main/res/values/strings.xml`
(`asset_statements`) and the manifest's `autoVerify` intent filter.

**The site's half** — `https://musicconnectz.net/.well-known/assetlinks.json`
must return your app's signing fingerprint. This backend serves that route
already ([`apps/omviardz/wellknown.py`](apps/omviardz/wellknown.py)); set two
env vars on Render:

```
TWA_PACKAGE_NAME=net.musicconnectz.app
TWA_SHA256_FINGERPRINTS=<Play's app-signing SHA-256>,<your upload-key SHA-256>
```

Get the fingerprints from **Play Console → Release → Setup → App signing**.
List **both** — Play re-signs the app, so the upload key alone won't verify the
copy your users install.

> The app opens `musicconnectz.net` (the frontend), so the file has to be served
> from **that** host. If the frontend is on Vercel, add
> `public/.well-known/assetlinks.json` there with the same JSON this backend
> returns — see [`config_snippets/assetlinks_frontend.md`](config_snippets/assetlinks_frontend.md).
> The Django route covers `admin.musicconnectz.net`.

**Verify it before you ship:**
[Statement List Generator & Tester](https://developers.google.com/digital-asset-links/tools/generator) ·
[Asset links docs](https://developers.google.com/digital-asset-links/v1/getting-started)

Test on a real phone: install the APK, open it. **URL bar visible = verification
failed.** Fix it before review — a URL bar is exactly what makes a reviewer
call your app a repackaged website.

---

## 6. Create the app and fill the store listing

**Console → Create app.** Then **Grow → Store presence → Main store listing**:

| Field | Spec | Use |
|---|---|---|
| App icon | 512×512 PNG, 32-bit | **`brand/play/icon-512.png`** ✅ |
| Feature graphic | 1024×500 PNG/JPG | **`brand/play/feature-graphic-1024x500.png`** ✅ |
| Phone screenshots | 2–8, 16:9 or 9:16, 320–3840px | Screenshot the mobile web app — lead with OmviardZ mid-tour |
| Short description | ≤80 chars | — |
| Full description | ≤4000 chars | — |

Both graphics are generated by
[`tools/make_brand_assets.py`](tools/make_brand_assets.py) from the same
wordless mark as the launcher icon — re-run it if you change a colour.

**Spec reference:**
[Store listing assets](https://support.google.com/googleplay/android-developer/answer/9866151) ·
[Metadata policy](https://support.google.com/googleplay/android-developer/answer/9898842)
(no "#1", no fake urgency, no keyword stuffing in the title)

---

## 7. App content — the declarations that actually get checked

**Console → Policy → App content.** Every one of these is mandatory. Answers
below are derived from what this backend really does:

### Data safety
[Form guide](https://support.google.com/googleplay/android-developer/answer/10787469) ·
[Declaration help](https://support.google.com/googleplay/android-developer/answer/10787469#zippy=%2Cdata-types)

| Data type | Collected? | Why | Evidence in this repo |
|---|---|---|---|
| Name / username | Yes | Account | `apps/accounts` |
| Email address | Yes | Account, password reset | `apps/accounts/passwords.py` |
| Phone number | Yes | Account (optional) | register endpoint |
| Date of birth | Yes | 13+ age gate for rewarded ads | `apps/economy/adz.py` |
| Photos | Yes | Avatar, FaceZ, uploads | `apps/economy/social.py` |
| Audio / video files | Yes | Uploads, DistributeZ | `apps/economy/distributez.py` |
| Messages | Yes | MessageZ, comments | `apps/economy/messages_view.py` |
| Approximate location | Yes, **optional** | Distance filtering, opt-in | `Profile.share_location` |
| Payment info | **Not by us** | Stripe/PayPal handle cards | `apps/economy/payments.py` |
| Device or other IDs | Yes | Ads / offerwall attribution | `apps/economy/rewards.py` |

Also declare: **data is encrypted in transit** (yes — HTTPS), **users can
request deletion** (yes — `/api/economy/account/delete/`), and **users can
export their data** (yes — `/api/economy/account/export/`).

### The rest of the checklist

- **Privacy policy URL** — must be live and mention every data type above.
- **Ads** — say **yes**, the app contains ads (AdMob rewarded video). Then
  follow the [ads policy](https://support.google.com/googleplay/android-developer/answer/9857753).
- **Content rating** — fill in the [IARC questionnaire](https://support.google.com/googleplay/android-developer/answer/9859655)
  honestly: user-to-user messaging, user-generated content, sharing location,
  digital purchases. Lying here is a removal, not a warning.
- **Target audience** — **13+**. Do **not** opt into
  [Families](https://support.google.com/googleplay/android-developer/answer/9893335);
  the app has adult-verified LessonZ bookings and open UGC.
- **App access** — the app requires sign-in, so provide **working test
  credentials** or review fails on the login screen. Give a real account with
  some data in it.
- **Government apps / financial features / health** — no.
- **Account deletion** — provide the **web** deletion URL (§1).
- **News, COVID, blockchain** — no.

---

## 8. The closed test you can't skip (personal accounts)

If your developer account is personal and was created after 13 Nov 2023, Play
requires a **closed test with at least 12 testers who stay opted in for 14
continuous days** before you can apply for production access.
[Policy](https://support.google.com/googleplay/android-developer/answer/14151465)

How it actually goes:

1. **Console → Testing → Internal testing** first. Up to 100 testers, no wait,
   instant installs. Use this to catch the URL bar / login problems.
2. Read the [pre-launch report](https://support.google.com/googleplay/android-developer/answer/9844487)
   Play generates automatically — it runs your app on real devices and finds
   crashes for free.
3. **Console → Testing → Closed testing** → create a track → add ≥12 testers by
   email (a Google Group is easier to manage than a list) → share the opt-in
   link.
4. **The 14 days only count while they stay opted in.** One person leaving the
   group resets your clock. Tell them plainly: install it, leave it installed,
   don't remove it for two weeks.
5. Day 15: **Apply for production access**. Google reviews the *test* too — a
   track where nobody opened the app twice reads as fake and gets bounced.

Getting to 12 without begging: your own devices count as separate testers only
with separate Google accounts (don't fake it — it's detectable). Ask in the
group chats where the actual artists are. Twelve people who'll genuinely poke
at it beats fifty who install and forget.

---

## 9. The three things most likely to get you rejected

### 🔴 Payments — this is the real risk

Play's [Payments policy](https://support.google.com/googleplay/android-developer/answer/10281818)
requires **Google Play Billing** for digital goods bought *inside* the app, at a
15–30% service fee. Music ConnectZ sells Premium, StatZ, wallet top-ups, prompt
packs, and post unlocks — every one of those is a digital good. Shipping a TWA
where an Android user buys Premium through Stripe is the single most likely
reason this app gets rejected or pulled.

Your options, honestly:

1. **Add Play Billing to the TWA** via the
   [Digital Goods API](https://developer.chrome.com/docs/android/trusted-web-activity/receive-payments-play-billing/)
   — the sanctioned path. Real work: `com.android.vending.BILLING` permission,
   products defined in Console, and a purchase-verification endpoint on this
   backend. Plan for it.
2. **Don't sell inside the Android app.** Let purchases happen on the website
   only, and don't link to them from the app. Play permits this but the rules on
   *steering* users out are narrow and enforced — read the policy before you
   rely on it.
3. **Alternative billing** where offered (EEA and some regions) —
   [details](https://support.google.com/googleplay/android-developer/answer/12570971).
   Regional, still carries a fee.

Physical merch and real-world services (in-person lessons) are **exempt** —
those may use Stripe/PayPal.

### 🟠 Minimum functionality

[Policy](https://support.google.com/googleplay/android-developer/answer/9898820).
An app that's just a website in a frame gets rejected. A verified TWA is
explicitly fine — but make sure:

- assetlinks verifies, so **no URL bar** (§5),
- it handles offline without a dead white screen,
- `https://musicconnectz.net/...` links open in the app (the autoVerify filter
  in the manifest does this),
- the app icon isn't a screenshot of the site, and the listing doesn't just say
  "our website".

### 🟡 User-generated content

[UGC policy](https://support.google.com/googleplay/android-developer/answer/9876937)
requires in-app reporting, blocking, and moderation. You already ship
`POST /api/economy/report/` and `POST /api/economy/block/` — make sure both are
reachable in **two taps** from any post, message, or profile in the mobile UI,
and say so in your review notes. Reviewers look for the buttons, not the
endpoints.

---

## 10. Ship it

1. **Console → Production → Create new release** → upload the `.aab`.
2. Write release notes. Pick a **staged rollout** (start at 20%) so a bad build
   doesn't reach everyone — [how](https://support.google.com/googleplay/android-developer/answer/6346149).
3. Review takes anywhere from a few hours to a week; first submissions are
   slower. Rejections come with a reason — fix and resubmit, don't re-argue.
4. **Target API level:** this project builds against **API 35**. Play raises the
   minimum every August, so check
   [the current requirement](https://support.google.com/googleplay/android-developer/answer/11926878)
   before each release and bump `compileSdk` / `targetSdk` in
   `android/app/build.gradle.kts` when it moves.

---

## 11. Succeeding after launch

The install is the start of the work, not the end.

- **[Android vitals](https://support.google.com/googleplay/android-developer/answer/9844486)** —
  crash and ANR rates. Cross the bad-behaviour threshold and Play *demotes your
  discoverability*. Check it weekly; it's the one metric that costs you installs
  silently.
- **[Store listing experiments](https://support.google.com/googleplay/android-developer/answer/9866151)** —
  A/B test the icon, feature graphic, and short description. Cheapest install
  gains you'll ever get. Test one thing at a time.
- **[Custom store listings](https://support.google.com/googleplay/android-developer/answer/9867158)** —
  different copy per audience (producers vs. fans vs. a specific country).
- **[In-app review API](https://developer.android.com/guide/playcore/in-app-review)** —
  ask for a rating *after* something good happens (a drill streak, a released
  track), never on launch. Ratings drive conversion more than screenshots do.
- **[Reply to every review](https://support.google.com/googleplay/android-developer/answer/138230)**,
  especially 1-star ones. Public replies are read by the next person deciding
  whether to install.
- **[Play Console statistics](https://support.google.com/googleplay/android-developer/answer/139628)** —
  watch install→open→retained-day-1. If day-1 retention is bad, the fix is
  onboarding, and onboarding is OmviardZ. Change the tour, not the ads.
- **Ship updates regularly.** Recency feeds ranking, and an app that hasn't
  updated in a year reads abandoned.

---

## 12. Every link in one place

**Joining**
[Signup](https://play.google.com/console/signup) ·
[Console](https://play.google.com/console) ·
[Account types & verification](https://support.google.com/googleplay/android-developer/answer/13628312) ·
[Payments profile](https://support.google.com/googleplay/android-developer/answer/9859434) ·
[Play Academy](https://playacademy.exceedlms.com/student/catalog)

**Policy**
[Policy Center](https://play.google.com/about/developer-content-policy/) ·
[Payments](https://support.google.com/googleplay/android-developer/answer/10281818) ·
[Minimum functionality](https://support.google.com/googleplay/android-developer/answer/9898820) ·
[UGC](https://support.google.com/googleplay/android-developer/answer/9876937) ·
[Families](https://support.google.com/googleplay/android-developer/answer/9893335) ·
[Ads](https://support.google.com/googleplay/android-developer/answer/9857753) ·
[Account deletion](https://support.google.com/googleplay/android-developer/answer/13327111)

**Shipping**
[Target API levels](https://support.google.com/googleplay/android-developer/answer/11926878) ·
[App bundles](https://developer.android.com/guide/app-bundle) ·
[Play App Signing](https://support.google.com/googleplay/android-developer/answer/9842756) ·
[Data safety](https://support.google.com/googleplay/android-developer/answer/10787469) ·
[Content rating](https://support.google.com/googleplay/android-developer/answer/9859655) ·
[Closed testing requirement](https://support.google.com/googleplay/android-developer/answer/14151465) ·
[Staged rollouts](https://support.google.com/googleplay/android-developer/answer/6346149) ·
[Pre-launch report](https://support.google.com/googleplay/android-developer/answer/9844487)

**Trusted Web Activity**
[Overview](https://developer.chrome.com/docs/android/trusted-web-activity/) ·
[Play Billing in a TWA](https://developer.chrome.com/docs/android/trusted-web-activity/receive-payments-play-billing/) ·
[Digital asset links](https://developers.google.com/digital-asset-links/v1/getting-started) ·
[Asset links tester](https://developers.google.com/digital-asset-links/tools/generator) ·
[Bubblewrap CLI](https://github.com/GoogleChromeLabs/bubblewrap)

**Growth**
[Android vitals](https://support.google.com/googleplay/android-developer/answer/9844486) ·
[Store listing experiments](https://support.google.com/googleplay/android-developer/answer/9866151) ·
[Custom store listings](https://support.google.com/googleplay/android-developer/answer/9867158) ·
[In-app reviews](https://developer.android.com/guide/playcore/in-app-review) ·
[Replying to reviews](https://support.google.com/googleplay/android-developer/answer/138230)
