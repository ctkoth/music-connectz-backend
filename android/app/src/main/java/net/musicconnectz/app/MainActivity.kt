package net.musicconnectz.app

import android.net.Uri
import com.google.androidbrowserhelper.trusted.LauncherActivity

/**
 * The whole app: a Trusted Web Activity onto musicconnectz.net.
 *
 * Chrome renders the site full-screen with no URL bar once
 * `/.well-known/assetlinks.json` verifies this package's signing fingerprint —
 * which is why the backend serves that file (see apps/omviardz/wellknown.py).
 *
 * The one thing this class adds on top of the library: a first-launch handoff
 * into OmviardZ. Someone who just installed from Play has never seen the
 * platform, so their first screen is Corey's guided tour rather than a feed of
 * names they don't know. Every launch after that goes straight to the site.
 */
class MainActivity : LauncherActivity() {

    override fun getLaunchingUrl(): Uri {
        val url = super.getLaunchingUrl()

        // Opened by tapping a link? Honour that link, don't hijack it.
        if (intent?.data != null) return url

        val prefs = getSharedPreferences(PREFS, MODE_PRIVATE)
        if (prefs.getBoolean(KEY_TOUR_OFFERED, false)) return url

        prefs.edit().putBoolean(KEY_TOUR_OFFERED, true).apply()
        return url.buildUpon().appendQueryParameter(TOUR_PARAM, "1").build()
    }

    private companion object {
        const val PREFS = "musicconnectz"
        const val KEY_TOUR_OFFERED = "omviardz_offered"
        const val TOUR_PARAM = "omviardz"
    }
}
