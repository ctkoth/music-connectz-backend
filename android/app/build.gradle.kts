plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Where the app points. Override per build without editing the file:
//   ./gradlew assembleRelease -PsiteUrl=https://staging.musicconnectz.net
val siteUrl: String = (project.findProperty("siteUrl") as String?) ?: "https://musicconnectz.net"
val siteHost: String = siteUrl.removePrefix("https://").removePrefix("http://").trimEnd('/')

android {
    namespace = "net.musicconnectz.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "net.musicconnectz.app"
        // 26 = Android 8.0. Adaptive icons and Trusted Web Activity both need
        // it, and dropping below would mean shipping legacy icon PNGs to reach
        // a slice of devices that can't run a modern Chrome anyway.
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"

        // Read by the manifest: the URL the TWA opens and the host whose links
        // this app is allowed to capture.
        manifestPlaceholders["siteUrl"] = siteUrl
        manifestPlaceholders["siteHost"] = siteHost
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

// The asset_statements string in strings.xml has to name the same site the TWA
// opens. Android can't nest string resources, so the URL is duplicated there —
// this fails the build the moment the two drift, instead of shipping an app
// that quietly shows a URL bar.
val checkAssetStatements by tasks.registering {
    val strings = file("src/main/res/values/strings.xml")
    inputs.file(strings)
    inputs.property("siteUrl", siteUrl)
    outputs.upToDateWhen { true }
    doLast {
        if (!strings.readText().contains(siteUrl)) {
            throw GradleException(
                "asset_statements in ${strings.name} does not mention $siteUrl. " +
                    "Update the <string name=\"asset_statements\"> site value to match, " +
                    "or build with -PsiteUrl=<the url that string names>."
            )
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
