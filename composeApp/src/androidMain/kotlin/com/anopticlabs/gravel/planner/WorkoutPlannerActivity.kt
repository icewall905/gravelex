package com.anopticlabs.gravel.planner

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.CalendarContract
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import coredevices.pebble.health.PebbleFitOxygenExportService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import org.koin.android.ext.android.inject
import java.io.IOException
import java.net.URL
import java.util.concurrent.TimeUnit
import javax.net.ssl.HttpsURLConnection

private const val DefaultHub = "https://ph.tdgs.org"
private const val ReminderChannel = "workout-planner"
private const val NotificationWork = "workout-planner-reminders"
private const val ReminderPreferences = "workout-planner-reminders"

internal class WorkoutPlannerActivity : ComponentActivity() {
    private val healthExport: PebbleFitOxygenExportService by inject()
    private lateinit var web: WebView
    private lateinit var origin: Uri

    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) enableReminders() else toast("Notification permission was declined.")
    }
    private val saveCalendar = registerForActivityResult(ActivityResultContracts.CreateDocument("text/calendar")) { uri ->
        if (uri != null) exportCalendar(uri)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val configured = Uri.parse(healthExport.baseUrl)
        origin = if (configured.scheme == "https" && configured.host != null && configured.userInfo == null) {
            Uri.parse("https://" + configured.encodedAuthority)
        } else {
            Uri.parse(DefaultHub)
        }
        web = WebView(this)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
        }
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false)
        web.webChromeClient = WebChromeClient()
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val target = request.url
                if (target.scheme != origin.scheme || target.encodedAuthority != origin.encodedAuthority) return true
                if (!request.isForMainFrame || !target.path.orEmpty().startsWith("/planner-native/")) return false
                if (Uri.parse(view.url.orEmpty()).path != "/planner.html" || !request.hasGesture()) return true
                when (target.path) {
                    "/planner-native/calendar" -> addToCalendar(target)
                    "/planner-native/export" -> saveCalendar.launch("workouts.ics")
                    "/planner-native/notifications" -> requestReminders()
                    "/planner-native/back" -> finish()
                }
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                CookieManager.getInstance().flush()
            }
        }
        setContentView(web)
        if (savedInstanceState == null || web.restoreState(savedInstanceState) == null) {
            val workout = intent.data?.lastPathSegment?.takeIf { Regex("[a-f0-9]{32}").matches(it) }
            val target = origin.buildUpon().path("/planner.html").appendQueryParameter("android", "1")
            if (workout != null) target.appendQueryParameter("workout", workout)
            web.loadUrl(target.build().toString())
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        web.saveState(outState)
        super.onSaveInstanceState(outState)
    }

    override fun onDestroy() {
        if (::web.isInitialized) web.destroy()
        super.onDestroy()
    }

    private fun requestReminders() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            permission.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            enableReminders()
        }
    }

    private fun enableReminders() {
        getSharedPreferences(ReminderPreferences, MODE_PRIVATE).edit().putString("origin", origin.toString()).apply()
        val work = PeriodicWorkRequestBuilder<WorkoutPlannerReminderWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        runCatching {
            WorkManager.getInstance(this).enqueueUniquePeriodicWork(NotificationWork, ExistingPeriodicWorkPolicy.KEEP, work)
        }.onSuccess {
            toast("Phone reminders enabled. Android may delay background delivery.")
        }.onFailure {
            toast("Android could not schedule background reminders.")
        }
    }

    private fun addToCalendar(target: Uri) {
        val start = target.getQueryParameter("start")?.toLongOrNull() ?: return
        val end = target.getQueryParameter("end")?.toLongOrNull()?.takeIf { it > start } ?: return
        val insert = Intent(Intent.ACTION_INSERT, CalendarContract.Events.CONTENT_URI)
            .putExtra(CalendarContract.Events.TITLE, target.getQueryParameter("title"))
            .putExtra(CalendarContract.Events.DESCRIPTION, target.getQueryParameter("details"))
            .putExtra(CalendarContract.EXTRA_EVENT_BEGIN_TIME, start)
            .putExtra(CalendarContract.EXTRA_EVENT_END_TIME, end)
        try {
            startActivity(insert)
        } catch (_: ActivityNotFoundException) {
            toast("No calendar app is available. Use Export .ics instead.")
        }
    }

    private fun exportCalendar(destination: Uri) {
        lifecycleScope.launch {
            val cookie = CookieManager.getInstance().getCookie(origin.toString())
            try {
                withContext(Dispatchers.IO) {
                    val data = plannerGet(origin.toString(), "/api/planner/calendar.ics", cookie)
                        ?: throw IOException("Sign in again")
                    contentResolver.openOutputStream(destination)?.use { it.write(data) }
                        ?: throw IOException("Cannot open destination")
                }
                toast("Calendar exported.")
            } catch (_: IOException) {
                toast("Could not export the calendar. Check your connection and sign-in.")
            }
        }
    }

    private fun toast(text: String) = Toast.makeText(this, text, Toast.LENGTH_LONG).show()
}

private fun plannerGet(origin: String, path: String, cookie: String?): ByteArray? {
    if (cookie.isNullOrEmpty()) return null
    val connection = URL(origin + path).openConnection() as HttpsURLConnection
    return try {
        connection.instanceFollowRedirects = false
        connection.connectTimeout = 8000
        connection.readTimeout = 10000
        connection.setRequestProperty("Cookie", cookie)
        when (connection.responseCode) {
            200 -> connection.inputStream.use { it.readBytes() }
            401 -> null
            else -> throw IOException("Planner request failed")
        }
    } finally {
        connection.disconnect()
    }
}

internal class WorkoutPlannerReminderWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val preferences = applicationContext.getSharedPreferences(ReminderPreferences, Context.MODE_PRIVATE)
        val origin = preferences.getString("origin", null) ?: return Result.success()
        val notifications = applicationContext.getSystemService(NotificationManager::class.java)
        if (!notifications.areNotificationsEnabled()) return Result.success()
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(
                applicationContext, Manifest.permission.POST_NOTIFICATIONS
            ) != PackageManager.PERMISSION_GRANTED
        ) return Result.success()

        val cookie = withContext(Dispatchers.Main) { CookieManager.getInstance().getCookie(origin) }
        val data = try {
            withContext(Dispatchers.IO) { plannerGet(origin, "/api/planner/reminders", cookie) }
        } catch (_: IOException) {
            return Result.retry()
        } ?: return Result.success()

        // Deduplication keys include the account so switching users can't suppress a reminder.
        val response = JSONObject(data.decodeToString())
        val due = response.getJSONArray("reminders")
        val account = response.getString("account")
        val seen = preferences.getStringSet("delivered", emptySet()).orEmpty().toMutableSet()
        val now = System.currentTimeMillis() / 1000
        seen.removeAll { (it.substringAfterLast(':').toLongOrNull() ?: 0) < now - 86_400 }

        notifications.createNotificationChannel(
            NotificationChannel(ReminderChannel, "Workout planner", NotificationManager.IMPORTANCE_DEFAULT)
        )
        for (index in 0 until due.length()) {
            val reminder = due.getJSONObject(index)
            val workout = reminder.getString("id")
            val kind = reminder.getString("kind")
            val key = "$account:$workout:$kind:${reminder.getLong("at")}"
            if (!seen.add(key)) continue
            val open = Intent(applicationContext, WorkoutPlannerActivity::class.java)
                .setData(Uri.parse("gravel-planner://workout/$workout"))
            val pending = PendingIntent.getActivity(applicationContext, 0, open, PendingIntent.FLAG_IMMUTABLE)
            val title = if (kind == "morning") "You have a workout today" else "How did training go?"
            notifications.notify(key, 1, NotificationCompat.Builder(applicationContext, ReminderChannel)
                .setSmallIcon(android.R.drawable.ic_popup_reminder)
                .setContentTitle(title)
                .setContentText("Open your workout and reply to Trainer.")
                .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                .setContentIntent(pending)
                .addAction(0, "Open Trainer", pending)
                .setAutoCancel(true)
                .build())
        }
        preferences.edit().putStringSet("delivered", seen).apply()
        return Result.success()
    }
}
