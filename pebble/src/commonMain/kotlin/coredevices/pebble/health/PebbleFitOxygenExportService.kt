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
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.time.Clock

data class OxygenExportStatus(
    val message: String = "No sync run yet.",
    val uploaded: Int = 0,
    val busy: Boolean = false,
)

data class OxygenExportSaveResult(val saved: Boolean, val message: String)

private data class OxygenExportConfig(val url: String, val token: String, val version: Long)

class PebbleFitOxygenExportService(
    private val settings: Settings,
    cipher: SecretCipher,
    private val httpClient: HttpClient,
    private val readSamples: suspend (Long, Int) -> List<HealthDataEntity>,
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

    val baseUrl: String get() = settings.getString(URL_KEY, DEFAULT_URL).trimEnd('/')
    val tokenConfigured: Boolean get() = settings.hasKey(TOKEN_KEY)

    fun saveConfiguration(urlInput: String, tokenInput: String): OxygenExportSaveResult {
        val url = urlInput.trim().trimEnd('/')
        if (!isValidBaseUrl(url)) return OxygenExportSaveResult(false, "Enter a valid HTTPS server URL.")
        if (tokenInput.isNotBlank() && tokenInput.any { it.isWhitespace() }) {
            return OxygenExportSaveResult(false, "The bearer token cannot contain whitespace.")
        }
        if (!syncMutex.tryLock()) {
            return OxygenExportSaveResult(false, "Sync is in progress. Try again when it finishes.")
        }
        configurationVersion += 1L
        try {
            val changedServer = url != baseUrl
            settings.putString(URL_KEY, url)
            if (tokenInput.isNotBlank()) tokenSetting.set(tokenInput.trim())
            if (changedServer || tokenInput.isNotBlank()) {
                settings.remove(WATERMARK_KEY)
                settings.remove(SCAN_CURSOR_KEY)
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
        if (config == null) {
            return if (tokenPresent) "Settings changed or token is unavailable. Try again."
            else "Add a bearer token first."
        }
        return try {
            val response = requestClient.get("${config.url}/fitness/records") {
                headers { append(HttpHeaders.Authorization, "Bearer " + config.token) }
            }
            val unchanged = syncMutex.withLock { configurationVersion == config.version }
            if (!unchanged) "Settings changed. Try again."
            else if (response.status.value in 200..299) "Connection successful."
            else "Server returned HTTP ${response.status.value}."
        } catch (_: HttpRequestTimeoutException) {
            "Connection timed out."
        } catch (_: TimeoutCancellationException) {
            "Connection timed out."
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            "Connection failed. Check the URL and network."
        }
    }

    suspend fun syncNow(): OxygenExportStatus = syncMutex.withLock {
        _status.value = OxygenExportStatus(message = "Syncing…", busy = true)
        try {
            val result = syncLocked()
            _status.value = result
            result
        } catch (e: CancellationException) {
            _status.value = OxygenExportStatus("Sync cancelled; it can be retried.")
            throw e
        } finally {
            if (_status.value.busy) _status.value = _status.value.copy(busy = false)
        }
    }

    private suspend fun syncLocked(): OxygenExportStatus {
        if (!settings.hasKey(TOKEN_KEY)) return OxygenExportStatus("Add a bearer token first.")
        val config = stableConfig()
            ?: return OxygenExportStatus("Settings changed or token is unavailable. Try again.")
        var watermark = settings.getLong(WATERMARK_KEY, 0L)
        var pageCursor = if (settings.hasKey(SCAN_CURSOR_KEY)) {
            settings.getLong(SCAN_CURSOR_KEY, 0L)
        } else {
            (watermark - LOOKBACK_SECONDS).coerceAtLeast(0L)
        }
        var uploaded = 0

        return try {
            while (true) {
                val rows = readSamples(pageCursor, MAX_BATCH)
                    .asSequence()
                    .filter {
                        it.timestamp > pageCursor &&
                            it.spo2Percent in 1..100 &&
                            it.spo2Quality in 0..255
                    }
                    .sortedBy { it.timestamp }
                    .take(MAX_BATCH)
                    .toList()

                if (rows.isEmpty()) {
                    settings.remove(SCAN_CURSOR_KEY)
                    return OxygenExportStatus(
                        if (uploaded == 0) "No new SpO₂ samples." else "Uploaded $uploaded samples.",
                        uploaded,
                    )
                }
                if (configurationVersion != config.version) {
                    return OxygenExportStatus("Settings changed; upload can be retried.", uploaded)
                }

                val body = buildJsonObject {
                    put("source", "phone-oxygen")
                    put("ts", Clock.System.now().epochSeconds)
                    put("oxygen", buildJsonArray {
                        rows.forEach { row ->
                            add(buildJsonObject {
                                put("ts", row.timestamp)
                                put("percent", row.spo2Percent)
                                put("quality", row.spo2Quality)
                            })
                        }
                    })
                }.toString()

                val response = requestClient.post("${config.url}/fitness/records") {
                    headers { append(HttpHeaders.Authorization, "Bearer " + config.token) }
                    contentType(ContentType.Application.Json)
                    setBody(body)
                }
                if (configurationVersion != config.version) {
                    return OxygenExportStatus("Settings changed; upload can be retried.", uploaded)
                }
                if (response.status.value !in 200..299) {
                    return OxygenExportStatus("Upload failed (HTTP ${response.status.value}); will retry.", uploaded)
                }

                pageCursor = rows.maxOf { it.timestamp }
                watermark = maxOf(watermark, pageCursor)
                settings.putLong(WATERMARK_KEY, watermark)
                if (rows.size == MAX_BATCH) settings.putLong(SCAN_CURSOR_KEY, pageCursor)
                else settings.remove(SCAN_CURSOR_KEY)
                uploaded += rows.size
            }
            @Suppress("UNREACHABLE_CODE")
            OxygenExportStatus("Sync complete.", uploaded)
        } catch (_: HttpRequestTimeoutException) {
            OxygenExportStatus("Upload timed out; will retry.", uploaded)
        } catch (_: TimeoutCancellationException) {
            OxygenExportStatus("Upload timed out; will retry.", uploaded)
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            OxygenExportStatus("Upload failed; will retry.", uploaded)
        }
    }

    private fun stableConfig(): OxygenExportConfig? {
        val before = configurationVersion
        if (before % 2L != 0L) return null
        val url = baseUrl
        val token = tokenSetting.get()?.takeIf { it.isNotBlank() } ?: return null
        val after = configurationVersion
        if (before != after || after % 2L != 0L) return null
        return OxygenExportConfig(url, token, after)
    }

    private fun isValidBaseUrl(url: String): Boolean {
        if (!url.startsWith("https://", ignoreCase = true)) return false
        val authority = url.substringAfter("://").substringBefore('/')
        return authority.isNotBlank() && '@' !in authority && '?' !in url && '#' !in url &&
            url.none { it.isWhitespace() }
    }

    private companion object {
        const val URL_KEY = "pebblefit_oxygen_url"
        const val TOKEN_KEY = "pebblefit_oxygen_token"
        const val WATERMARK_KEY = "pebblefit_oxygen_watermark"
        const val SCAN_CURSOR_KEY = "pebblefit_oxygen_scan_cursor"
        const val DEFAULT_URL = "https://ph.tdgs.org"
        const val MAX_BATCH = 3000
        const val LOOKBACK_SECONDS = 14L * 24L * 60L * 60L
        const val REQUEST_TIMEOUT_MS = 20_000L
    }
}
