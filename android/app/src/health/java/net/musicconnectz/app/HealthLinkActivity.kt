package net.musicconnectz.app

import android.content.Context
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.AggregateGroupByPeriodRequest
import androidx.health.connect.client.time.TimeRangeFilter
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.Period

/**
 * Sends the member's step counts from Health Connect to their account, and nothing else.
 *
 * Why this is a native screen: the app is a Trusted Web Activity (Chrome), and neither a web page nor Chrome can read
 * Health Connect or a watch. This is the one place the app asks for a health permission, and it asks for exactly one,
 * READ_STEPS. It is compiled into the Music ConnectZ and BodieZ apps only; the SkillZ and IntelligenceZ builds do not
 * contain it and do not declare the permission.
 *
 * What it does, in the order the member sees it:
 *  1. BodieZ shows a short code. The member types it here; the server swaps it for a long token kept on this phone.
 *  2. The member allows steps in Health Connect's own dialog. Nothing is read before that.
 *  3. It reads the last fourteen days as Health Connect's AGGREGATE — which removes the double count when a phone and a
 *     watch both recorded the same walk — and sends whole days. Nothing else (no heart rate, no location, no workouts).
 *  4. "Unlink" forgets the token here and asks the server to delete every day it holds.
 *
 * The count is what the device says; the server cannot check it, so it pays nothing and moves no rating.
 */
class HealthLinkActivity : ComponentActivity() {

    private lateinit var status: TextView
    private lateinit var codeBox: EditText
    private lateinit var linkBtn: Button
    private lateinit var syncBtn: Button
    private lateinit var unlinkBtn: Button

    private val permissions = setOf(HealthPermission.getReadPermission(StepsRecord::class))

    private val askPermission = registerForActivityResult(
        PermissionController.createRequestPermissionResultContract()
    ) { granted ->
        if (granted.containsAll(permissions)) syncNow() else say("Steps weren't allowed in Health Connect, so nothing was read or sent.")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (20 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad * 2, pad, pad)
            setBackgroundColor(0xFF0B0B14.toInt())
        }
        fun text(s: String, size: Float = 16f) = TextView(this).apply {
            this.text = s; textSize = size; setTextColor(0xFFE8E8F0.toInt()); setPadding(0, pad / 2, 0, pad / 2)
        }
        root.addView(text("Link steps", 24f))
        root.addView(text(
            "Sends your daily step count from Health Connect (your phone and any watch that writes to it) to your account, " +
                "so BodieZ can show it. Only steps — no heart rate, location or workouts. It pays nothing and changes no rating."
        ))
        codeBox = EditText(this).apply {
            hint = "Code from BodieZ"; inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS
            setTextColor(0xFFFFFFFF.toInt()); setHintTextColor(0xFF888899.toInt()); gravity = Gravity.CENTER
        }
        linkBtn = Button(this).apply { text = "Link this phone"; setOnClickListener { link() } }
        syncBtn = Button(this).apply { text = "Send steps now"; setOnClickListener { requestThenSync() } }
        unlinkBtn = Button(this).apply { text = "Unlink and delete my steps"; setOnClickListener { unlink() } }
        status = text("")
        listOf(codeBox, linkBtn, syncBtn, unlinkBtn, status).forEach { root.addView(it) }
        setContentView(root)
        refreshUi()
    }

    private fun prefs() = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private fun token() = prefs().getString(KEY_TOKEN, "") ?: ""

    private fun refreshUi() {
        val linked = token().isNotEmpty()
        codeBox.visibility = if (linked) LinearLayout.GONE else LinearLayout.VISIBLE
        linkBtn.visibility = if (linked) LinearLayout.GONE else LinearLayout.VISIBLE
        syncBtn.visibility = if (linked) LinearLayout.VISIBLE else LinearLayout.GONE
        unlinkBtn.visibility = if (linked) LinearLayout.VISIBLE else LinearLayout.GONE
        if (status.text.isNullOrEmpty()) say(if (linked) "Linked." else "Open BodieZ → Steps → Link steps for a code, then type it here.")
    }

    private fun say(s: String) { runOnUiThread { status.text = s } }

    private fun link() {
        val code = codeBox.text.toString().trim()
        if (code.isEmpty()) return say("Type the code BodieZ showed you.")
        say("Linking…")
        lifecycleScope.launch {
            val (ok, body) = withContext(Dispatchers.IO) { post("health/link/", JSONObject().put("code", code), null) }
            if (ok) {
                prefs().edit().putString(KEY_TOKEN, body.optString("token")).apply()
                say("Linked. Now allow steps."); refreshUi(); requestThenSync()
            } else say(body.optString("detail", "Couldn't link. Check your connection and the code."))
        }
    }

    private fun requestThenSync() {
        when (HealthConnectClient.getSdkStatus(this)) {
            HealthConnectClient.SDK_UNAVAILABLE -> return say("Health Connect isn't available on this phone.")
            HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED ->
                return say("Update Health Connect from the Play Store, then try again.")
        }
        lifecycleScope.launch {
            val client = HealthConnectClient.getOrCreate(this@HealthLinkActivity)
            val have = client.permissionController.getGrantedPermissions()
            if (have.containsAll(permissions)) syncNow() else askPermission.launch(permissions)
        }
    }

    private fun syncNow() {
        say("Reading steps…")
        lifecycleScope.launch {
            try {
                val client = HealthConnectClient.getOrCreate(this@HealthLinkActivity)
                val start = LocalDate.now().minusDays(13).atStartOfDay()
                val rows = client.aggregateGroupByPeriod(
                    AggregateGroupByPeriodRequest(
                        metrics = setOf(StepsRecord.COUNT_TOTAL),
                        timeRangeFilter = TimeRangeFilter.between(start, LocalDateTime.now()),
                        timePeriod = Period.ofDays(1),
                    )
                )
                val days = JSONArray()
                rows.forEach { r ->
                    // A day with no record at all is left out, never sent as 0: not-recorded is not zero steps.
                    val n = r.result[StepsRecord.COUNT_TOTAL] ?: return@forEach
                    days.put(JSONObject().put("day", r.startTime.toLocalDate().toString()).put("steps", n))
                }
                val (ok, body) = withContext(Dispatchers.IO) { post("health/steps/", JSONObject().put("days", days), token()) }
                when {
                    ok -> say("Sent ${body.optInt("saved")} days. Open BodieZ to see them.")
                    body.optString("detail").contains("not linked") -> {
                        prefs().edit().remove(KEY_TOKEN).apply(); say(body.optString("detail")); refreshUi()
                    }
                    else -> say(body.optString("detail", "Couldn't send. Try again."))
                }
            } catch (e: Exception) {
                say("Couldn't read steps: ${e.message ?: "unknown error"}")
            }
        }
    }

    private fun unlink() {
        say("Unlinking…")
        lifecycleScope.launch {
            // The server's days are deleted from BodieZ (signed in); the phone can only forget its own token.
            prefs().edit().remove(KEY_TOKEN).apply()
            say("Unlinked on this phone. To delete the steps already saved, press Unlink in BodieZ → Steps.")
            refreshUi()
        }
    }

    /** One JSON POST. Returns (success, body); a network failure is (false, {"detail": …}) and never throws. */
    private fun post(path: String, json: JSONObject, token: String?): Pair<Boolean, JSONObject> = try {
        val c = (URL(BuildConfig.API_BASE.trimEnd('/') + "/api/economy/" + path).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"; connectTimeout = 15_000; readTimeout = 20_000; doOutput = true
            setRequestProperty("Content-Type", "application/json")
            if (!token.isNullOrEmpty()) setRequestProperty("X-Health-Token", token)
        }
        c.outputStream.use { it.write(json.toString().toByteArray()) }
        val ok = c.responseCode in 200..299
        val raw = (if (ok) c.inputStream else c.errorStream)?.bufferedReader()?.use { it.readText() } ?: "{}"
        Pair(ok, runCatching { JSONObject(raw) }.getOrDefault(JSONObject()))
    } catch (e: Exception) {
        Pair(false, JSONObject().put("detail", "No connection to the server."))
    }

    private companion object {
        const val PREFS = "musicconnectz_health"
        const val KEY_TOKEN = "token"
    }
}
