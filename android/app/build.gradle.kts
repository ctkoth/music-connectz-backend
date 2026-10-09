plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Where the app points. Override per build without editing the file:
//   ./gradlew assembleRelease -PsiteUrl=https://staging.musicconnectz.net
val siteUrl: String = (project.findProperty("siteUrl") as String?) ?: "https://musicconnectz.net"
// BodieZ is its OWN site, not a path on the main one: the BodieZ-only build in
// the frontend repo (`npm run build:bodiez`, hosted on its own origin). Chrome
// verifies a TWA against the host it opens, so this app proves ownership of THIS
// host and the main site's assetlinks.json is irrelevant to it.
//   ./gradlew bundleBodiezRelease -PbodiezUrl=https://bodiez.example.net
val bodiezUrl: String = (project.findProperty("bodiezUrl") as String?) ?: "https://bodiez.musicconnectz.net"
fun hostOf(url: String): String = url.removePrefix("https://").removePrefix("http://").trimEnd('/')

android {
    namespace = "net.musicconnectz.app"
    compileSdk = 35

    defaultConfig {
        // 26 = Android 8.0. Adaptive icons and Trusted Web Activity both need
        // it, and dropping below would mean shipping legacy icon PNGs to reach
        // a slice of devices that can't run a modern Chrome anyway.
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"

        // The manifest's `launchUrl` (what the TWA opens) and `siteHost` (whose
        // links it may capture) are per flavor, below.
    }

    // Two apps from one project, one Play listing each. They share the Kotlin
    // and differ in what a member sees before they open it — name, icon, splash —
    // and in WHICH SITE they open.
    //
    //   mcz     Music ConnectZ — the whole platform, on musicconnectz.net.
    //   bodiez  BodieZ         — the BodieZ-only build on its own origin. Same
    //                            accounts and data, but the shell contains BodieZ
    //                            and nothing else: not the profile, orientation,
    //                            substance or attractiveness-rating screens that
    //                            make the main app a Data safety / Families
    //                            question, and not the Premium purchase flow that
    //                            makes it a Play Billing one (frontend:
    //                            play/bodiez/README.md). Pointing this at
    //                            /bodie on the main site would have inherited
    //                            every one of those.
    //
    // Commands become assembleMczDebug / bundleBodiezRelease and so on; plain
    // `bundleRelease` still builds both.
    flavorDimensions += "app"
    productFlavors {
        create("mcz") {
            dimension = "app"
            applicationId = "net.musicconnectz.app"
            manifestPlaceholders["launchUrl"] = siteUrl
            manifestPlaceholders["siteHost"] = hostOf(siteUrl)
            // A first install of the whole platform opens OmviardZ's guided tour.
            buildConfigField("boolean", "FIRST_LAUNCH_TOUR", "true")
        }
        create("bodiez") {
            dimension = "app"
            applicationId = "net.musicconnectz.bodiez"
            manifestPlaceholders["launchUrl"] = bodiezUrl.trimEnd('/') + "/"
            manifestPlaceholders["siteHost"] = hostOf(bodiezUrl)
            // Someone who installed a fitness tracker is not here for a tour of
            // a music platform, and the BodieZ-only shell has no tour to open.
            buildConfigField("boolean", "FIRST_LAUNCH_TOUR", "false")
        }
    }

    signingConfigs {
        // Release signing comes from the environment so no keystore is ever
        // committed. Unset locally -> the release build stays unsigned and
        // Play's upload flow (or CI) signs it.
        create("release") {
            val store = System.getenv("ANDROID_KEYSTORE_PATH")
            if (!store.isNullOrBlank() && file(store).exists()) {
                storeFile = file(store)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfigs.getByName("release").storeFile?.let {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        buildConfig = true
    }
}

// Each app's asset_statements string has to name the same site that app opens.
// Android can't nest string resources, so the URL is duplicated there — this
// fails the build the moment the two drift, instead of shipping an app that
// quietly shows a URL bar. Per flavor, because they open different sites: the
// bodiez source set overrides main's string with its own.
val checkAssetStatements by tasks.registering {
    val checks = mapOf(
        "src/main/res/values/strings.xml" to siteUrl,
        "src/bodiez/res/values/strings.xml" to bodiezUrl.trimEnd('/'),
    )
    checks.keys.forEach { inputs.file(file(it)) }
    inputs.property("siteUrl", siteUrl)
    inputs.property("bodiezUrl", bodiezUrl)
    outputs.upToDateWhen { true }
    doLast {
        checks.forEach { (path, url) ->
            if (!file(path).readText().contains(url)) {
                throw GradleException(
                    "asset_statements in $path does not mention $url. " +
                        "Update the <string name=\"asset_statements\"> site value to match, " +
                        "or build with -PsiteUrl / -PbodiezUrl set to the url that string names."
                )
            }
        }
    }
}

tasks.named("preBuild") { dependsOn(checkAssetStatements) }

dependencies {
    // Trusted Web Activity: opens the real site full-screen in Chrome with no
    // URL bar (once assetlinks.json verifies), so the mobile web app IS the app.
    implementation("com.google.androidbrowserhelper:androidbrowserhelper:2.5.0")
    implementation("androidx.browser:browser:1.8.0")
    // FileProvider, for handing the splash bitmap to Chrome. The splash screen
    // itself needs no library: Android 12+ uses the platform attributes in
    // values-v31, older versions use the window background.
    implementation("androidx.core:core-ktx:1.13.1")
}
