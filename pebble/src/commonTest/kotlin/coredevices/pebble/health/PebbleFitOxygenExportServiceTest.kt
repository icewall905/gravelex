package coredevices.pebble.health

import com.russhwolf.settings.MapSettings
import coredevices.util.security.DecryptResult
import coredevices.util.security.SecretCipher
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.TextContent
import io.rebble.libpebblecommon.database.entity.HealthDataEntity
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class PebbleFitOxygenExportServiceTest {
    @Test
    fun failedPostKeepsCursorAndSuccessfulRetryUploadsValidSamples() = runTest {
        var requests = 0
        var payload = ""
        val sample = sample(timestamp = 1_700_000_000L, percent = 96, quality = 42)
        val client = HttpClient(MockEngine { request ->
            requests++
            assertEquals("Bearer test-secret", request.headers[HttpHeaders.Authorization])
            payload = (request.body as? TextContent)?.text.orEmpty()
            respond(
                content = "",
                status = if (requests == 1) HttpStatusCode.ServiceUnavailable else HttpStatusCode.OK,
            )
        })
        val settings = MapSettings()
        val service = PebbleFitOxygenExportService(settings, TestCipher(), client) { after, _ ->
            listOf(sample).filter { it.timestamp > after }
        }
        assertTrue(service.saveConfiguration("https://ph.tdgs.org", "test-secret").saved)
        assertFalse(settings.getString("pebblefit_oxygen_token", "").contains("test-secret"))

        val failed = service.syncNow()
        assertEquals(0, failed.uploaded)
        assertEquals(0L, settings.getLong("pebblefit_oxygen_watermark", 0L))

        val succeeded = service.syncNow()
        assertEquals(1, succeeded.uploaded, succeeded.message)
        assertEquals(sample.timestamp, settings.getLong("pebblefit_oxygen_watermark", 0L))
        assertTrue(payload.contains("\"source\":\"phone-oxygen\""))
        assertTrue(payload.contains("\"ts\":1700000000"))
        assertTrue(payload.contains("\"percent\":96"))
        assertTrue(payload.contains("\"quality\":42"))
    }

    @Test
    fun saveIsRejectedDuringPostAndNewConfigAppliesAfterSyncCompletes() = runTest {
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        var requests = 0
        val sample = sample(timestamp = 1_700_000_000L, percent = 95, quality = 3)
        val client = HttpClient(MockEngine { request ->
            requests++
            if (requests == 1) {
                assertEquals("https://old.example/fitness/records", request.url.toString())
                assertEquals("Bearer old-token", request.headers[HttpHeaders.Authorization])
                entered.complete(Unit)
                release.await()
            } else {
                assertEquals("https://new.example/fitness/records", request.url.toString())
                assertEquals("Bearer new-token", request.headers[HttpHeaders.Authorization])
            }
            respond(content = "", status = HttpStatusCode.OK)
        })
        val settings = MapSettings()
        val service = PebbleFitOxygenExportService(settings, TestCipher(), client) { after, _ ->
            listOf(sample).filter { it.timestamp > after }
        }
        assertTrue(service.saveConfiguration("https://old.example", "old-token").saved)

        val firstSync = async { service.syncNow() }
        entered.await()
        val rejected = service.saveConfiguration("https://new.example", "new-token")
        assertFalse(rejected.saved)
        assertTrue(rejected.message.contains("in progress"))
        release.complete(Unit)
        assertEquals(1, firstSync.await().uploaded)
        assertEquals(sample.timestamp, settings.getLong("pebblefit_oxygen_watermark", 0L))

        assertTrue(service.saveConfiguration("https://new.example", "new-token").saved)
        assertEquals(0L, settings.getLong("pebblefit_oxygen_watermark", 0L))
        assertEquals(1, service.syncNow().uploaded)
        assertEquals(2, requests)
        assertEquals(sample.timestamp, settings.getLong("pebblefit_oxygen_watermark", 0L))
    }

    @Test
    fun connectionTestUsesOneUrlTokenSnapshotWhenSettingsChangeInFlight() = runTest {
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val client = HttpClient(MockEngine { request ->
            assertEquals("https://old.example/fitness/records", request.url.toString())
            assertEquals("Bearer old-token", request.headers[HttpHeaders.Authorization])
            entered.complete(Unit)
            release.await()
            respond(content = "", status = HttpStatusCode.OK)
        })
        val service = PebbleFitOxygenExportService(MapSettings(), TestCipher(), client) { _, _ -> emptyList() }
        assertTrue(service.saveConfiguration("https://old.example", "old-token").saved)

        val testRequest = async { service.testConnection() }
        entered.await()
        assertTrue(service.saveConfiguration("https://new.example", "new-token").saved)
        release.complete(Unit)
        assertEquals("Settings changed. Try again.", testRequest.await())
    }

    @Test
    fun timeoutIsRetryableAndDoesNotLeaveBusySet() = runTest {
        var requests = 0
        val sample = sample(timestamp = 1_700_000_000L, percent = 97, quality = 8)
        val client = HttpClient(MockEngine {
            requests++
            if (requests == 1) awaitCancellation()
            respond(content = "", status = HttpStatusCode.OK)
        })
        val service = PebbleFitOxygenExportService(MapSettings(), TestCipher(), client) { after, _ ->
            listOf(sample).filter { it.timestamp > after }
        }
        service.saveConfiguration("https://ph.tdgs.org", "token")

        val timeout = service.syncNow()
        assertTrue(timeout.message.contains("timed out"))
        assertFalse(service.status.value.busy)
        run { val result = service.syncNow(); assertEquals(1, result.uploaded, result.message) }
        assertEquals(2, requests)
        assertFalse(service.status.value.busy)
    }


    @Test
    fun lateSamplesWithinLookbackAreReplayedWithoutMovingHighWaterBackward() = runTest {
        val first = sample(timestamp = 1_700_000_000L, percent = 95, quality = 1)
        val late = sample(timestamp = first.timestamp - 86_400L, percent = 94, quality = 2)
        val uploaded = mutableListOf<Long>()
        val client = HttpClient(MockEngine { request ->
            val payloadText = (request.body as? TextContent)?.text.orEmpty()
            if (payloadText.contains("\"ts\":${late.timestamp}")) uploaded += late.timestamp
            if (payloadText.contains("\"ts\":${first.timestamp}")) uploaded += first.timestamp
            respond(content = "", status = HttpStatusCode.OK)
        })
        val settings = MapSettings()
        val available = mutableListOf(first)
        val service = PebbleFitOxygenExportService(settings, TestCipher(), client) { after, _ ->
            available.filter { it.timestamp > after }.sortedBy { it.timestamp }
        }
        service.saveConfiguration("https://ph.tdgs.org", "token")
        run { val result = service.syncNow(); assertEquals(1, result.uploaded, result.message) }
        assertEquals(first.timestamp, settings.getLong("pebblefit_oxygen_watermark", 0L))

        available += late
        assertEquals(2, service.syncNow().uploaded)
        assertEquals(first.timestamp, settings.getLong("pebblefit_oxygen_watermark", 0L))
        assertEquals(listOf(first.timestamp, late.timestamp, first.timestamp), uploaded)
    }

    @Test
    fun invalidUrlAndEmptyTokenNeverSendNetworkRequest() = runTest {
        val client = HttpClient(MockEngine {
            error("A network request must not be made without a configured token.")
        })
        val service = PebbleFitOxygenExportService(MapSettings(), TestCipher(), client) { _, _ -> emptyList() }
        assertFalse(service.saveConfiguration("http://ph.tdgs.org", "token").saved)
        assertEquals("Add a bearer token first.", service.syncNow().message)
    }

    private fun sample(timestamp: Long, percent: Int, quality: Int) = HealthDataEntity(
        timestamp = timestamp,
        steps = 0,
        orientation = 0,
        intensity = 0,
        lightIntensity = 0,
        activeMinutes = 0,
        restingGramCalories = 0,
        activeGramCalories = 0,
        distanceCm = 0,
        spo2Percent = percent,
        spo2Quality = quality,
    )

    private class TestCipher : SecretCipher {
        override fun encrypt(plaintext: String): String = "testcipher:${plaintext.reversed()}"
        override fun decrypt(stored: String): DecryptResult =
            if (stored.startsWith("testcipher:")) {
                DecryptResult.Success(stored.removePrefix("testcipher:").reversed())
            } else {
                DecryptResult.Unrecoverable
            }
    }
}
