package com.anopticlabs.gravel.workout

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import kotlinx.coroutines.flow.MutableStateFlow
import java.util.UUID

internal data class LiveWorkout(
    val workout: Workout,
    val active: Long = 0,
    val paused: Boolean = false,
    val route: List<Fix> = emptyList(),
    val distance: Double = 0.0,
    val gpsStatus: String = "",
    val strapStatus: String = "",
    val bpm: Int? = null,
    val laps: Int = 0,
    val sets: Int = 0,
)

internal class WorkoutRecorder : Service(), LocationListener {
    private val store by lazy { WorkoutStore.get(this) }
    private val location by lazy { getSystemService(LocationManager::class.java) }
    private val handler = Handler(Looper.getMainLooper())
    private var runStart: Long? = null
    private var accumulated = 0L
    private var sessionStart = 0L
    private var sessionWall = 0L
    private var lastPulseTime = 0L
    private var lastBpm: Int? = null
    private var lastFix: Fix? = null
    private var lastGpsTime = 0L
    private var segment = 0
    private var wantsGps = false
    private var strap: ChestStrap? = null
    private var seconds = 0
    private var previewStride = 1
    private var acceptedFixes = 0

    private val ticker = object : Runnable {
        override fun run() {
            val state = live.value ?: return
            val active = activeMs()
            if (seconds++ % 5 == 0) {
                if (!persist { store.checkpoint(state.workout.id, wallTime(), active) }) return
                getSystemService(NotificationManager::class.java).notify(NOTIFICATION, notification(state.workout.sport))
            }
            live.value = state.copy(
                active = active,
                bpm = lastBpm.takeIf { runStart != null && SystemClock.elapsedRealtime() - lastPulseTime <= 5000 },
                gpsStatus = if (wantsGps && runStart != null && state.gpsStatus == "GPS recording" &&
                    SystemClock.elapsedRealtime() - lastGpsTime > 15_000) "Waiting for GPS…" else state.gpsStatus,
            )
            if (active >= MAX_ACTIVE_MS || SystemClock.elapsedRealtime() - sessionStart >= MAX_ACTIVE_MS) {
                finish()
            } else {
                handler.postDelayed(this, 1000)
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            START -> if (live.value == null) {
                val sport = intent.getStringExtra("sport")?.let { Sport.valueOf(it) }
                if (sport == null) stopSelf() else start(sport, intent.getBooleanExtra("gps", false), intent.getStringExtra("strap"))
            }
            PAUSE -> pause()
            RESUME -> resume()
            LAP -> live.value?.takeIf { !it.paused }?.let { state ->
                if (persist { store.lap(state.workout.id, Lap(activeMs(), state.distance)) }) {
                    live.value = state.copy(laps = state.laps + 1)
                }
            }
            SET -> {
                val state = live.value
                val exercise = intent.getStringExtra("exercise").orEmpty().trim()
                val reps = intent.getIntExtra("reps", 0)
                val kg = intent.getDoubleExtra("kg", Double.NaN).takeIf { it.isFinite() && it >= 0 }
                if (state?.workout?.sport == Sport.strength && exercise.length in 1..100 && reps in 1..999 &&
                    persist { store.set(state.workout.id, StrengthSet(exercise, reps, kg)) }
                ) {
                    live.value = state.copy(sets = state.sets + 1)
                }
            }
            FINISH -> finish()
            else -> if (live.value == null) stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun start(sport: Sport, gps: Boolean, address: String?) {
        wantsGps = gps && granted(Manifest.permission.ACCESS_FINE_LOCATION)
        val hasStrap = address != null && (Build.VERSION.SDK_INT < 31 || granted(Manifest.permission.BLUETOOTH_CONNECT))
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "Workout recording", NotificationManager.IMPORTANCE_LOW)
        )
        try {
            val types = (if (wantsGps) ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION else 0) or
                (if (hasStrap) ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE else 0)
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(NOTIFICATION, notification(sport), if (types == 0) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else types)
            } else if (Build.VERSION.SDK_INT >= 29) {
                startForeground(NOTIFICATION, notification(sport), types)
            } else {
                startForeground(NOTIFICATION, notification(sport))
            }
        } catch (_: RuntimeException) {
            error.value = "Android could not start recording. Check the workout permissions and try again."
            stopSelf()
            return
        }

        val now = System.currentTimeMillis()
        val workout = Workout(UUID.randomUUID().toString(), sport, now, now, 0)
        if (!persist { store.start(workout) }) return
        error.value = null
        finished.value = null
        live.value = LiveWorkout(workout, gpsStatus = if (gps && !wantsGps) "Precise location permission unavailable" else "")
        sessionWall = now
        sessionStart = SystemClock.elapsedRealtime()
        runStart = sessionStart
        requestGps()
        if (hasStrap) {
            strap = ChestStrap(this, address, { status ->
                lastBpm = null
                live.value?.let { live.value = it.copy(strapStatus = status, bpm = null) }
            }, ::recordPulse).also { it.connect() }
        }
        handler.post(ticker)
    }

    private fun granted(permission: String) = checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

    private fun wallTime(now: Long = SystemClock.elapsedRealtime()) = sessionWall + (now - sessionStart)

    private fun activeMs(now: Long = SystemClock.elapsedRealtime()) =
        accumulated + (runStart?.let { (now - it).coerceAtLeast(0) } ?: 0)

    @SuppressLint("MissingPermission")
    private fun requestGps() {
        if (!wantsGps) return
        val status = try {
            location.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000, 0f, this, Looper.getMainLooper())
            if (location.isProviderEnabled(LocationManager.GPS_PROVIDER)) "Waiting for GPS…" else "Turn on phone location"
        } catch (_: RuntimeException) {
            "Phone GPS unavailable"
        }
        live.value?.let { live.value = it.copy(gpsStatus = status) }
    }

    override fun onProviderDisabled(provider: String) {
        live.value?.let { live.value = it.copy(gpsStatus = "Turn on phone location") }
    }

    override fun onProviderEnabled(provider: String) {
        live.value?.let { live.value = it.copy(gpsStatus = "Waiting for GPS…") }
    }

    override fun onLocationChanged(fix: Location) {
        val state = live.value ?: return
        val stamp = fix.elapsedRealtimeNanos / 1_000_000
        if (stamp < (runStart ?: return) || SystemClock.elapsedRealtime() - stamp !in 0..10_000 ||
            !fix.hasAccuracy() || fix.accuracy !in 0f..25f) return
        lastGpsTime = stamp
        if (state.gpsStatus != "GPS recording") live.value = state.copy(gpsStatus = "GPS recording")
        val point = appendFix(lastFix, Fix(wallTime(stamp), activeMs(stamp), segment, fix.latitude, fix.longitude,
            fix.altitude.takeIf { fix.hasAltitude() && it.isFinite() }, fix.accuracy, 0.0)) ?: return
        if (!persist { store.fix(state.workout.id, point) }) return
        segment = point.segment
        lastFix = point
        val current = live.value ?: return
        acceptedFixes++
        var preview = current.route
        if (preview.size >= 1200) {
            preview = preview.filterIndexed { index, _ -> index % 2 == 0 }
            previewStride = (previewStride * 2).coerceAtMost(1024)
        }
        if (acceptedFixes % previewStride == 0 || preview.lastOrNull()?.segment != point.segment) preview = preview + point
        live.value = current.copy(distance = point.meters, route = preview)
    }

    private fun recordPulse(bpm: Int) {
        val state = live.value ?: return
        if (state.paused) return
        val now = SystemClock.elapsedRealtime()
        if (now - lastPulseTime < 500) return
        if (!persist { store.pulse(state.workout.id, Pulse(activeMs(now), bpm, wallTime(now), segment)) }) return
        lastPulseTime = now
        lastBpm = bpm
        live.value = state.copy(bpm = bpm)
    }

    private fun pause() {
        val state = live.value?.takeIf { !it.paused } ?: return
        accumulated = activeMs()
        runStart = null
        segment++
        lastBpm = null
        runCatching { location.removeUpdates(this) }
        if (persist { store.checkpoint(state.workout.id, wallTime(), accumulated) }) {
            live.value = state.copy(active = accumulated, paused = true, bpm = null, gpsStatus = if (wantsGps) "GPS paused" else "")
        }
    }

    private fun resume() {
        val state = live.value?.takeIf { it.paused } ?: return
        runStart = SystemClock.elapsedRealtime()
        live.value = state.copy(paused = false)
        requestGps()
    }

    private fun finish() {
        val state = live.value ?: return
        if (persist { store.checkpoint(state.workout.id, wallTime(), activeMs(), finished = true) }) {
            finished.value = state.workout.id
            shutdown()
        }
    }

    private fun persist(operation: () -> Unit): Boolean = try {
        operation()
        true
    } catch (_: android.database.sqlite.SQLiteException) {
        error.value = "Recording stopped because the workout could not be written to storage."
        runCatching { store.recover() }
        shutdown()
        false
    }

    private fun shutdown() {
        handler.removeCallbacksAndMessages(null)
        runCatching { location.removeUpdates(this) }
        strap?.close()
        strap = null
        live.value = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        live.value?.let { runCatching { store.recover() } }
        shutdown()
        super.onDestroy()
    }

    private fun notification(sport: Sport): Notification {
        val open = Intent(this, WorkoutActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val pending = PendingIntent.getActivity(this, 0, open,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle(sport.label)
            .setContentText(if (live.value?.paused == true) "Workout paused" else "Workout recording")
            .setContentIntent(pending)
            .setOnlyAlertOnce(true)
            .setOngoing(true)
            .build()
    }

    companion object {
        const val START = "start"
        const val PAUSE = "pause"
        const val RESUME = "resume"
        const val LAP = "lap"
        const val SET = "set"
        const val FINISH = "finish"
        private const val CHANNEL = "gravel_workouts"
        private const val NOTIFICATION = 0x3712
        private const val MAX_ACTIVE_MS = 172_800_000L
        val live = MutableStateFlow<LiveWorkout?>(null)
        val finished = MutableStateFlow<String?>(null)
        val error = MutableStateFlow<String?>(null)

        fun command(context: Context, action: String, configure: Intent.() -> Unit = {}) {
            val intent = Intent(context, WorkoutRecorder::class.java).setAction(action).apply(configure)
            if (action == START) context.startForegroundService(intent) else context.startService(intent)
        }
    }
}
