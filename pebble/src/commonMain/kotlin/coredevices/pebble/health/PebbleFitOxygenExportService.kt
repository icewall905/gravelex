package coredevices.pebble.health

import com.russhwolf.settings.Settings
import coredevices.util.security.EncryptedStringSetting
import coredevices.util.security.SecretCipher
import io.ktor.client.HttpClient
import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.request.get
import io.ktor.client.request.headers
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.contentType
import io.rebble.libpebblecommon.database.entity.HealthDataEntity
import io.rebble.libpebblecommon.database.entity.OverlayDataEntity
import io.rebble.libpebblecommon.health.OverlayType
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.time.Clock
import kotlin.time.TimeSource
import kotlin.time.Duration.Companion.seconds

data class OxygenExportStatus(
    val message: String = "No sync run yet.",
    val uploaded: Int = 0,
    val busy: Boolean = false,
    val retryableFailure: Boolean = false,
)

data class OxygenExportSaveResult(val saved: Boolean, val message: String)

/** A battery value read from the selected watch over its active GATT connection. */
data class WatchBatterySnapshot(
    val batteryPercent: Int,
    val observedAt: Long,
    val deviceId: String? = null,
)

private data class ExportConfig(val url: String, val token: String, val version: Long)

class PebbleFitOxygenExportService(
    private val settings: Settings,
    cipher: SecretCipher,
    httpClient: HttpClient,
    private val readHealth: suspend (Long, Int) -> List<HealthDataEntity>,
    private val readSessions: suspend (Long, Int, List<Int>, Int) -> List<OverlayDataEntity>,
    private val readWatchBattery: suspend () -> WatchBatterySnapshot? = { null },
) {
    private val tokenSetting = EncryptedStringSetting(settings, cipher, TOKEN_KEY)
    private val requestClient = httpClient.config {
        followRedirects = false
        install(HttpTimeout) {
            requestTimeoutMillis = REQUEST_TIMEOUT_MS
            connectTimeoutMillis = 5_000L
            socketTimeoutMillis = 10_000L
        }
    }
    private val syncMutex = Mutex()
    private val _status = MutableStateFlow(OxygenExportStatus())
    val status: StateFlow<OxygenExportStatus> = _status
    private var configurationVersion = 0L

    val lastAttemptAt: Long get() = settings.getLong(LAST_ATTEMPT_KEY, 0L)
    val consecutiveFailures: Int get() = settings.getInt(FAILURES_KEY, 0)
    val nextRetryAt: Long get() = settings.getLong(NEXT_RETRY_KEY, 0L)
    val lastReconciliationAt: Long get() = settings.getLong(RECONCILED_KEY, 0L)

    /** A foreground/manual request may bypass backoff; the periodic worker must respect it. */
    suspend fun syncIfDue(): OxygenExportStatus {
        if (!enabled || Clock.System.now().epochSeconds < maxOf(nextRetryAt, settings.getLong(NEXT_POLL_KEY, 0L))) return _status.value
        return syncNow(automatic = true)
    }

    val baseUrl: String get() = settings.getString(URL_KEY, DEFAULT_URL).trimEnd('/')
    val enabled: Boolean get() = settings.getBoolean("gravelex_export_enabled", false)
    val tokenConfigured: Boolean get() = settings.hasKey(TOKEN_KEY)
    val lastSuccessfulUploadAt: Long? get() =
        if (settings.hasKey(LAST_UPLOAD_AT_KEY)) settings.getLong(LAST_UPLOAD_AT_KEY, 0L) else null
    val lastSuccessfulUploadCount: Int? get() =
        if (settings.hasKey(LAST_UPLOAD_COUNT_KEY)) settings.getInt(LAST_UPLOAD_COUNT_KEY, 0) else null

    fun saveConfiguration(urlInput: String, tokenInput: String, enableExport: Boolean = true): OxygenExportSaveResult {
        val url = urlInput.trim().trimEnd('/')
        if (!isValidBaseUrl(url)) return OxygenExportSaveResult(false, "Enter a valid HTTPS server URL.")
        if (tokenInput.isNotBlank() && tokenInput.any { it.isWhitespace() }) {
            return OxygenExportSaveResult(false, "The bearer token cannot contain whitespace.")
        }
        if (!syncMutex.tryLock()) return OxygenExportSaveResult(false, "Sync is in progress. Try again when it finishes.")
        configurationVersion += 1L
        try {
            val changedServer = url != baseUrl
            settings.putString(URL_KEY, url)
            settings.putBoolean("gravelex_export_enabled", enableExport)
            if (tokenInput.isNotBlank()) tokenSetting.set(tokenInput.trim())
            if (changedServer || tokenInput.isNotBlank()) {
                clearCursors()
                listOf(LAST_ATTEMPT_KEY, FAILURES_KEY, NEXT_RETRY_KEY, RECONCILED_KEY, RECONCILING_KEY, CORRECTIONS_KEY, SWEEP_KEY, NEXT_POLL_KEY, SESSION_WATERMARK_TYPE_KEY).forEach(settings::remove)
                settings.remove(LAST_UPLOAD_AT_KEY)
                settings.remove(LAST_UPLOAD_COUNT_KEY)
            }
            val saved = settings.getString(URL_KEY, "") == url &&
                (tokenInput.isBlank() || settings.hasKey(TOKEN_KEY))
            return if (saved) OxygenExportSaveResult(true, "Settings saved.")
            else OxygenExportSaveResult(false, "Could not securely save the bearer token.")
        } finally {
            configurationVersion += 1L
            syncMutex.unlock()
        }
    }

    suspend fun testConnection(): String {
        val (tokenPresent, config) = syncMutex.withLock {
            val present = settings.hasKey(TOKEN_KEY)
            present to if (present) stableConfig() else null
        }
        if (config == null) return if (tokenPresent) "Settings changed or token is unavailable. Try again." else "Add a bearer token first."
        return try {
            val response = requestClient.get("${config.url}/fitness/records") {
                headers { append(HttpHeaders.Authorization, "Bearer " + config.token) }
            }
            val unchanged = syncMutex.withLock { configurationVersion == config.version }
            if (!unchanged) "Settings changed. Try again."
            else if (response.status.value in 200..299) "Connection successful."
            else "Server returned HTTP ${response.status.value}."
        } catch (_: HttpRequestTimeoutException) { "Connection timed out." }
        catch (_: TimeoutCancellationException) { "Connection timed out." }
        catch (e: CancellationException) { throw e }
        catch (_: Exception) { "Connection failed. Check the URL and network." }
    }

    suspend fun syncNow(automatic: Boolean = false): OxygenExportStatus = syncMutex.withLock {
        // Recheck after acquiring the mutex: another trigger may have just failed
        // or completed while this automatic request was waiting.
        if (automatic && (!enabled || Clock.System.now().epochSeconds <
                maxOf(nextRetryAt, settings.getLong(NEXT_POLL_KEY, 0L)))) return@withLock _status.value
        _status.value = OxygenExportStatus(message = "Syncing…", busy = true)
        try {
            if (enabled) settings.putLong(LAST_ATTEMPT_KEY, Clock.System.now().epochSeconds)
            syncLocked(automatic).also {
                if (enabled && tokenConfigured) {
                    if (it.retryableFailure) {
                        val failures = (consecutiveFailures + 1).coerceAtMost(20)
                        settings.putInt(FAILURES_KEY, failures)
                        val delay = (60L * (1L shl (failures - 1).coerceAtMost(10))).coerceAtMost(21600L)
                        settings.putLong(NEXT_RETRY_KEY, Clock.System.now().epochSeconds + delay)
                    } else {
                        settings.putLong(NEXT_POLL_KEY, Clock.System.now().epochSeconds + 60L)
                        settings.putInt(FAILURES_KEY, 0)
                        settings.putLong(NEXT_RETRY_KEY, 0L)
                    }
                }
                _status.value = it
            }
        } catch (e: CancellationException) {
            _status.value = OxygenExportStatus("Sync cancelled; it can be retried.")
            throw e
        } finally {
            if (_status.value.busy) _status.value = _status.value.copy(busy = false)
        }
    }

    private suspend fun syncLocked(automatic: Boolean): OxygenExportStatus {
        if (!enabled) return OxygenExportStatus("Health data export is disabled.")
        if (!settings.hasKey(TOKEN_KEY)) return OxygenExportStatus("Add a bearer token first.")
        val config = stableConfig() ?: return OxygenExportStatus("Settings changed or token is unavailable. Try again.")
        // Re-use durable page cursors for a weekly full reconciliation. Never declare
        // it complete until both streams reach EOF; process death resumes the scan.
        val due = Clock.System.now().epochSeconds - lastReconciliationAt >= RECONCILE_SECONDS
        if (due && !settings.getBoolean(RECONCILING_KEY, false) &&
            !settings.hasKey(HEALTH_CURSOR_KEY) && !settings.hasKey(SESSION_CURSOR_KEY)) {
            settings.putLong(HEALTH_CURSOR_KEY, MIN_TIMESTAMP - 1L)
            settings.putLong(SESSION_CURSOR_KEY, MIN_TIMESTAMP - 1L)
            settings.putInt(SESSION_TYPE_CURSOR_KEY, -1)
            settings.putBoolean(RECONCILING_KEY, true)
            settings.putBoolean(SWEEP_KEY, true)
        }
        // Routine automatic polling is incremental. Only daily correction sweeps (or
        // an explicit manual request) replay the 14-day window; weekly scans reach EOF.
        val correctionsDue = Clock.System.now().epochSeconds - settings.getLong(CORRECTIONS_KEY, 0L) >= 86400L
        if (!settings.hasKey(HEALTH_CURSOR_KEY) && !settings.hasKey(SESSION_CURSOR_KEY) &&
            (correctionsDue || !automatic)) {
            settings.putLong(HEALTH_CURSOR_KEY, (settings.getLong(HEALTH_WATERMARK_KEY, 0L) - LOOKBACK_SECONDS).coerceAtLeast(0L))
            settings.putLong(SESSION_CURSOR_KEY, (settings.getLong(SESSION_WATERMARK_KEY, 0L) - LOOKBACK_SECONDS).coerceAtLeast(0L))
            settings.putInt(SESSION_TYPE_CURSOR_KEY, -1)
            settings.putBoolean(SWEEP_KEY, true)
        }
        val started = TimeSource.Monotonic.markNow()
        var pages = 0
        var healthWatermark = settings.getLong(HEALTH_WATERMARK_KEY, 0L)
        var sessionWatermark = settings.getLong(SESSION_WATERMARK_KEY, 0L)
        var healthCursor = settings.getLong(HEALTH_CURSOR_KEY, healthWatermark)
        var sessionCursor = settings.getLong(SESSION_CURSOR_KEY, sessionWatermark)
        var sessionTypeCursor = settings.getInt(SESSION_TYPE_CURSOR_KEY, settings.getInt(SESSION_WATERMARK_TYPE_KEY, -1))
        var uploaded = 0
        var skipped = 0
        val watchBattery = try {
            readWatchBattery()
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            null
        }?.takeIf {
            it.batteryPercent in 0..100 && it.observedAt in MIN_TIMESTAMP..(Clock.System.now().epochSeconds + 300L)
        }
        val lastBatteryObservedAt = settings.getLong(LAST_BATTERY_OBSERVED_AT_KEY, 0L)
        val lastBatteryDeviceId = settings.getString(LAST_BATTERY_DEVICE_ID_KEY, "")
        var watchStatusPending = watchBattery?.takeIf {
            it.deviceId != lastBatteryDeviceId || it.observedAt > lastBatteryObservedAt
        }
        return try {
            while (pages < MAX_PAGES_PER_RUN && started.elapsedNow() < 60.seconds) {
                pages++
                val now = Clock.System.now().epochSeconds
                // Scan boundaries come from raw database pages, so rejected records cannot
                // hide later valid records. Acknowledgment still precedes cursor writes.
                val healthPage = readHealth(healthCursor, MAX_PAGE)
                    .filter { it.timestamp > healthCursor }.sortedBy { it.timestamp }.take(MAX_PAGE)
                val sessionPage = readSessions(sessionCursor, sessionTypeCursor, OVERLAY_TYPES, MAX_SESSIONS)
                    .filter { it.startTime > sessionCursor || (it.startTime == sessionCursor && it.type > sessionTypeCursor) }
                    .sortedWith(compareBy({ it.startTime }, { it.type })).take(MAX_SESSIONS)
                if (healthPage.isEmpty() && sessionPage.isEmpty()) {
                    var batteryUploaded = false
                    if (watchStatusPending != null) {
                        if (configurationVersion != config.version) return OxygenExportStatus("Settings changed; upload can be retried.", uploaded)
                        val battery = watchStatusPending
                        val body = buildJsonObject {
                            put("source", "gravelex")
                            put("ts", Clock.System.now().epochSeconds)
                            put("records", buildJsonArray {})
                            put("oxygen", buildJsonArray {})
                            put("sessions", buildJsonArray {})
                            put("watch_status", buildJsonObject {
                                put("battery_percent", battery.batteryPercent)
                                put("observed_at", battery.observedAt)
                                put("source", "gravelex_ble")
                                battery.deviceId?.let { put("device_id", it) }
                            })
                        }.toString()
                        val response = requestClient.post("${config.url}/fitness/records") {
                            headers { append(HttpHeaders.Authorization, "Bearer " + config.token) }
                            contentType(ContentType.Application.Json)
                            setBody(body)
                        }
                        if (configurationVersion != config.version) return OxygenExportStatus("Settings changed; upload can be retried.", uploaded)
                        if (response.status.value !in 200..299) return OxygenExportStatus("Upload failed (HTTP ${response.status.value}); will retry.", uploaded, retryableFailure = true)
                        settings.putLong(LAST_UPLOAD_AT_KEY, Clock.System.now().epochSeconds)
                        settings.putInt(LAST_UPLOAD_COUNT_KEY, 0)
                        settings.putLong(LAST_BATTERY_OBSERVED_AT_KEY, battery.observedAt)
                        if (battery.deviceId != null) {
                            settings.putString(LAST_BATTERY_DEVICE_ID_KEY, battery.deviceId)
                        } else {
                            settings.remove(LAST_BATTERY_DEVICE_ID_KEY)
                        }
                        watchStatusPending = null
                        batteryUploaded = true
                    }
                    if (settings.getBoolean(RECONCILING_KEY, false)) {
                        settings.putLong(RECONCILED_KEY, Clock.System.now().epochSeconds)
                        settings.putBoolean(RECONCILING_KEY, false)
                    }
                    if (settings.getBoolean(SWEEP_KEY, false)) {
                        settings.putLong(CORRECTIONS_KEY, Clock.System.now().epochSeconds)
                        settings.putBoolean(SWEEP_KEY, false)
                    }
                    settings.remove(HEALTH_CURSOR_KEY)
                    settings.remove(SESSION_CURSOR_KEY)
                    settings.remove(SESSION_TYPE_CURSOR_KEY)
                    val message = when {
                        batteryUploaded && uploaded == 0 -> "Uploaded watch battery status."
                        uploaded == 0 -> "No new health data."
                        else -> "Uploaded $uploaded health records and sessions."
                    }
                    return OxygenExportStatus(message + if (skipped > 0) " Skipped $skipped invalid records." else "", uploaded)
                }
                val rows = healthPage.filter { it.timestamp in MIN_TIMESTAMP..(now + 300L) && validHealth(it) }
                val sessions = sessionPage.filter {
                    it.startTime in MIN_TIMESTAMP..(now + 300L) && it.duration in 1L..172800L && sessionType(it.type) != null
                }
                skipped += healthPage.size - rows.size + sessionPage.size - sessions.size
                if (configurationVersion != config.version) return OxygenExportStatus("Settings changed; upload can be retried.", uploaded)
                if (rows.isNotEmpty() || sessions.isNotEmpty() || watchStatusPending != null) {
                    val body = buildJsonObject {
                        put("source", "gravelex")
                        put("ts", Clock.System.now().epochSeconds)
                        put("records", buildJsonArray { rows.forEach { add(it.toExportJson()) } })
                        put("oxygen", buildJsonArray {
                            rows.filter { it.spo2Percent in 1..100 && it.spo2Quality in 0..255 }.forEach { row ->
                                add(buildJsonObject {
                                    put("ts", row.timestamp)
                                    put("percent", row.spo2Percent)
                                    put("quality", row.spo2Quality)
                                })
                            }
                        })
                        put("sessions", buildJsonArray { sessions.forEach { add(it.toExportJson()) } })
                        watchStatusPending?.let { battery ->
                            put("watch_status", buildJsonObject {
                                put("battery_percent", battery.batteryPercent)
                                put("observed_at", battery.observedAt)
                                put("source", "gravelex_ble")
                                battery.deviceId?.let { put("device_id", it) }
                            })
                        }
                    }.toString()
                    val response = requestClient.post("${config.url}/fitness/records") {
                        headers { append(HttpHeaders.Authorization, "Bearer " + config.token) }
                        contentType(ContentType.Application.Json)
                        setBody(body)
                    }
                    if (configurationVersion != config.version) return OxygenExportStatus("Settings changed; upload can be retried.", uploaded)
                    if (response.status.value !in 200..299) return OxygenExportStatus("Upload failed (HTTP ${response.status.value}); will retry.", uploaded, retryableFailure = true)
                    settings.putLong(LAST_UPLOAD_AT_KEY, Clock.System.now().epochSeconds)
                    settings.putInt(LAST_UPLOAD_COUNT_KEY, rows.size + sessions.size)
                    watchStatusPending?.let {
                        settings.putLong(LAST_BATTERY_OBSERVED_AT_KEY, it.observedAt)
                        if (it.deviceId != null) {
                            settings.putString(LAST_BATTERY_DEVICE_ID_KEY, it.deviceId)
                        } else {
                            settings.remove(LAST_BATTERY_DEVICE_ID_KEY)
                        }
                        watchStatusPending = null
                    }
                }
                if (healthPage.isNotEmpty()) {
                    healthCursor = healthPage.last().timestamp
                    if (rows.isNotEmpty()) healthWatermark = maxOf(healthWatermark, rows.maxOf { it.timestamp })
                    settings.putLong(HEALTH_WATERMARK_KEY, healthWatermark)
                    settings.putLong(HEALTH_CURSOR_KEY, healthCursor)
                }
                if (sessionPage.isNotEmpty()) {
                    val last = sessionPage.last()
                    sessionCursor = last.startTime
                    sessionTypeCursor = last.type
                    if (sessions.isNotEmpty()) {
                        val newest = sessions.maxWith(compareBy({ it.startTime }, { it.type }))
                        if (newest.startTime > sessionWatermark) {
                            sessionWatermark = newest.startTime
                            settings.putInt(SESSION_WATERMARK_TYPE_KEY, newest.type)
                        } else if (newest.startTime == sessionWatermark) {
                            settings.putInt(SESSION_WATERMARK_TYPE_KEY, maxOf(settings.getInt(SESSION_WATERMARK_TYPE_KEY, -1), newest.type))
                        }
                    }
                    settings.putLong(SESSION_WATERMARK_KEY, sessionWatermark)
                    settings.putLong(SESSION_CURSOR_KEY, sessionCursor)
                    settings.putInt(SESSION_TYPE_CURSOR_KEY, sessionTypeCursor)
                }
                uploaded += rows.size + sessions.size
            }
            OxygenExportStatus("Uploaded $uploaded records; more history remains for the next run.", uploaded)
        } catch (_: HttpRequestTimeoutException) { OxygenExportStatus("Upload timed out; will retry.", uploaded, retryableFailure = true) }
        catch (_: TimeoutCancellationException) { OxygenExportStatus("Upload timed out; will retry.", uploaded, retryableFailure = true) }
        catch (e: CancellationException) { throw e }
        catch (_: Exception) { OxygenExportStatus("Upload failed; will retry.", uploaded, retryableFailure = true) }
    }

    private fun stableConfig(): ExportConfig? {
        val before = configurationVersion
        if (before % 2L != 0L) return null
        val url = baseUrl
        val token = tokenSetting.get()?.takeIf { it.isNotBlank() } ?: return null
        val after = configurationVersion
        if (before != after || after % 2L != 0L) return null
        return ExportConfig(url, token, after)
    }

    private fun clearCursors() {
        listOf(HEALTH_WATERMARK_KEY, HEALTH_CURSOR_KEY, SESSION_WATERMARK_KEY, SESSION_CURSOR_KEY, SESSION_TYPE_CURSOR_KEY).forEach(settings::remove)
    }

    private fun isValidBaseUrl(url: String): Boolean {
        if (!url.startsWith("https://", ignoreCase = true)) return false
        val authority = url.substringAfter("://").substringBefore('/')
        return authority.isNotBlank() && '@' !in authority && '?' !in url && '#' !in url && url.none { it.isWhitespace() }
    }

    private companion object {
        const val NEXT_POLL_KEY = "gravelex_export_next_poll"
        const val SWEEP_KEY = "gravelex_export_sweeping"
        const val CORRECTIONS_KEY = "gravelex_export_corrections"
        const val SESSION_WATERMARK_TYPE_KEY = "gravelex_session_watermark_type"
        const val LAST_ATTEMPT_KEY = "gravelex_export_last_attempt"
        const val FAILURES_KEY = "gravelex_export_failures"
        const val NEXT_RETRY_KEY = "gravelex_export_next_retry"
        const val RECONCILED_KEY = "gravelex_export_reconciled"
        const val RECONCILING_KEY = "gravelex_export_reconciling"
        const val RECONCILE_SECONDS = 7L * 86400L
        const val MAX_PAGES_PER_RUN = 4
        const val URL_KEY = "pebblefit_oxygen_url"
        private const val LAST_UPLOAD_AT_KEY = "gravelex_last_upload_at"
        private const val LAST_UPLOAD_COUNT_KEY = "gravelex_last_upload_count"
        private const val LAST_BATTERY_OBSERVED_AT_KEY = "gravelex_last_battery_observed_at"
        private const val LAST_BATTERY_DEVICE_ID_KEY = "gravelex_last_battery_device_id"
        const val TOKEN_KEY = "pebblefit_oxygen_token"
        const val HEALTH_WATERMARK_KEY = "pebblefit_health_watermark"
        const val HEALTH_CURSOR_KEY = "pebblefit_health_scan_cursor"
        const val SESSION_WATERMARK_KEY = "pebblefit_session_watermark"
        const val SESSION_CURSOR_KEY = "pebblefit_session_scan_cursor"
        const val SESSION_TYPE_CURSOR_KEY = "pebblefit_session_scan_type"
        const val MIN_TIMESTAMP = 946684800L
        const val MAX_SESSIONS = 1000
        const val DEFAULT_URL = ""
        const val MAX_PAGE = 3000
        const val LOOKBACK_SECONDS = 14L * 24L * 60L * 60L
        const val REQUEST_TIMEOUT_MS = 20_000L
        val OVERLAY_TYPES = listOf(1, 2, 3, 4, 5, 6, 7)
    }
}

private fun validHealth(row: HealthDataEntity): Boolean =
    row.steps in 0..10000 && row.intensity >= 0 && row.lightIntensity >= 0 && row.activeMinutes >= 0 &&
        row.restingGramCalories >= 0 && row.activeGramCalories >= 0 && row.distanceCm >= 0 &&
        (row.heartRate == 0 || row.heartRate in 1..255)

private fun HealthDataEntity.toExportJson() = buildJsonObject {
    put("ts", timestamp)
    if (heartRate in 1..255) put("hr", heartRate) else put("hr", JsonNull)
    put("steps", steps)
    put("active", if (activeMinutes > 0) 1 else 0)
    put("intensity", intensity)
    put("light_intensity", lightIntensity)
    put("active_kcal", activeGramCalories / 1000.0)
    put("resting_kcal", restingGramCalories / 1000.0)
    put("distance_m", distanceCm / 100.0)
    put("hr_zone", heartRateZone)
}

private fun sessionType(type: Int): String? = when (OverlayType.fromValue(type)) {
    OverlayType.Sleep, OverlayType.Nap -> "sleep"
    OverlayType.DeepSleep, OverlayType.DeepNap -> "restful_sleep"
    OverlayType.Walk -> "walk"
    OverlayType.Run -> "run"
    OverlayType.OpenWorkout -> "workout"
    null -> null
}

private fun OverlayDataEntity.toExportJson() = buildJsonObject {
    put("start", startTime)
    put("seconds", duration)
    put("type", sessionType(type) ?: "workout")
    put("id", "$startTime:$type")
    put("raw_overlay_type", type)
}
