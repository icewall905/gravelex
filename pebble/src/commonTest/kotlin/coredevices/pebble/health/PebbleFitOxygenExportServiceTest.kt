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
import io.rebble.libpebblecommon.database.entity.OverlayDataEntity
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class PebbleFitOxygenExportServiceTest {
    @Test
    fun disabledExportDoesNotReadOrSendHealthData() = runTest {
        val settings = MapSettings()
        val client = HttpClient(MockEngine { error("Disabled export must not make a request") })
        val service = PebbleFitOxygenExportService(settings, TestCipher(), client,
            readHealth = { _, _ -> error("Disabled export must not read health") },
            readSessions = { _, _, _, _ -> error("Disabled export must not read sessions") })
        assertFalse(service.enabled)
        assertTrue(service.saveConfiguration("https://ph.tdgs.org", "test-secret", false).saved)
        assertTrue(service.syncNow().message.contains("disabled"))
        assertTrue(service.tokenConfigured)
    }

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
        val service = PebbleFitOxygenExportService(settings, TestCipher(), client, readHealth = { after, _ ->
            listOf(sample).filter { it.timestamp > after }
        }, readSessions = { _, _, _, _ -> emptyList() })
        assertTrue(service.saveConfiguration("https://ph.tdgs.org", "test-secret").saved)
        assertFalse(settings.getString("pebblefit_oxygen_token", "").contains("test-secret"))

        val failed = service.syncNow()
        assertEquals(0, failed.uploaded)
        assertEquals(null, service.lastSuccessfulUploadAt)
        assertEquals(null, service.lastSuccessfulUploadCount)
        assertEquals(0L, settings.getLong("pebblefit_health_watermark", 0L))

        val succeeded = service.syncNow()
        assertEquals(1, succeeded.uploaded, succeeded.message)
        assertTrue((service.lastSuccessfulUploadAt ?: 0L) > 0L)
        assertEquals(1, service.lastSuccessfulUploadCount)
        val restored = PebbleFitOxygenExportService(settings, TestCipher(), client,
            readHealth = { _, _ -> emptyList() }, readSessions = { _, _, _, _ -> emptyList() })
        assertEquals(service.lastSuccessfulUploadAt, restored.lastSuccessfulUploadAt)
        assertEquals(service.lastSuccessfulUploadCount, restored.lastSuccessfulUploadCount)
        assertEquals(sample.timestamp, settings.getLong("pebblefit_health_watermark", 0L))
        assertTrue(restored.saveConfiguration("https://other.example", "").saved)
        assertEquals(null, restored.lastSuccessfulUploadAt)
        assertEquals(null, restored.lastSuccessfulUploadCount)
        assertEquals(0L, settings.getLong("pebblefit_health_watermark", 0L))
        assertTrue(payload.contains("\"source\":\"gravelex\""))
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
        val service = PebbleFitOxygenExportService(settings, TestCipher(), client, readHealth = { after, _ ->
            listOf(sample).filter { it.timestamp > after }
        }, readSessions = { _, _, _, _ -> emptyList() })
        assertTrue(service.saveConfiguration("https://old.example", "old-token").saved)

        val firstSync = async { service.syncNow() }
        entered.await()
        val rejected = service.saveConfiguration("https://new.example", "new-token")
        assertFalse(rejected.saved)
        assertTrue(rejected.message.contains("in progress"))
        release.complete(Unit)
        assertEquals(1, firstSync.await().uploaded)
        assertEquals(sample.timestamp, settings.getLong("pebblefit_health_watermark", 0L))

        assertTrue(service.saveConfiguration("https://new.example", "new-token").saved)
        assertEquals(0L, settings.getLong("pebblefit_health_watermark", 0L))
        assertEquals(1, service.syncNow().uploaded)
        assertEquals(2, requests)
        assertEquals(sample.timestamp, settings.getLong("pebblefit_health_watermark", 0L))
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
        val service = PebbleFitOxygenExportService(MapSettings(), TestCipher(), client, readHealth = { _, _ -> emptyList() }, readSessions = { _, _, _, _ -> emptyList() })
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
        val service = PebbleFitOxygenExportService(MapSettings(), TestCipher(), client, readHealth = { after, _ ->
            listOf(sample).filter { it.timestamp > after }
        }, readSessions = { _, _, _, _ -> emptyList() })
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
        val service = PebbleFitOxygenExportService(settings, TestCipher(), client, readHealth = { after, _ ->
            available.filter { it.timestamp > after }.sortedBy { it.timestamp }
        }, readSessions = { _, _, _, _ -> emptyList() })
        service.saveConfiguration("https://ph.tdgs.org", "token")
        run { val result = service.syncNow(); assertEquals(1, result.uploaded, result.message) }
        assertEquals(first.timestamp, settings.getLong("pebblefit_health_watermark", 0L))

        available += late
        assertEquals(2, service.syncNow().uploaded)
        assertEquals(first.timestamp, settings.getLong("pebblefit_health_watermark", 0L))
        assertEquals(listOf(first.timestamp, late.timestamp, first.timestamp), uploaded)
    }

    @Test
    fun invalidUrlAndEmptyTokenNeverSendNetworkRequest() = runTest {
        val client = HttpClient(MockEngine {
            error("A network request must not be made without a configured token.")
        })
        val service = PebbleFitOxygenExportService(MapSettings(), TestCipher(), client, readHealth = { _, _ -> emptyList() }, readSessions = { _, _, _, _ -> emptyList() })
        assertFalse(service.saveConfiguration("http://ph.tdgs.org", "token").saved)
        assertTrue(service.saveConfiguration("https://ph.tdgs.org", "", true).saved)
        assertEquals("Add a bearer token first.", service.syncNow().message)
    }

    @Test
    fun exportsMinuteUnitsOxygenAndEveryKnownOverlayType() = runTest {
        val minute = sample(timestamp = 1_700_000_100L, percent = 97, quality = 9).copy(
            steps = 23,
            intensity = 11,
            lightIntensity = 4,
            activeMinutes = 1,
            restingGramCalories = 500,
            activeGramCalories = 1_250,
            distanceCm = 1_234,
            heartRate = 122,
            heartRateZone = 2,
        )
        val sessions = (1..7).map { type ->
            OverlayDataEntity(
                startTime = 1_700_001_000L + type,
                duration = 60L * type,
                type = type,
                steps = 1,
                restingKiloCalories = 0,
                activeKiloCalories = 0,
                distanceCm = 0,
                offsetUTC = 0,
            )
        }
        var payload = ""
        val client = HttpClient(MockEngine { request ->
            payload = (request.body as? TextContent)?.text.orEmpty()
            respond(content = "", status = HttpStatusCode.OK)
        })
        val service = PebbleFitOxygenExportService(
            MapSettings(), TestCipher(), client,
            readHealth = { after, _ -> listOf(minute).filter { it.timestamp > after } },
            readSessions = { after, afterType, _, limit -> sessions.filter { it.startTime > after || (it.startTime == after && it.type > afterType) }.take(limit) },
        )
        service.saveConfiguration("https://receiver.example", "secret")

        val result = service.syncNow()
        assertEquals(8, result.uploaded, result.message)
        assertTrue(payload.contains("\"source\":\"gravelex\""))
        assertTrue(payload.contains("\"hr\":122"))
        assertTrue(payload.contains("\"steps\":23"))
        assertTrue(payload.contains("\"active_kcal\":1.25"))
        assertTrue(payload.contains("\"resting_kcal\":0.5"))
        assertTrue(payload.contains("\"distance_m\":12.34"))
        assertTrue(payload.contains("\"percent\":97"))
        assertTrue(payload.contains("\"type\":\"sleep\""))
        assertTrue(payload.contains("\"type\":\"restful_sleep\""))
        assertTrue(payload.contains("\"type\":\"walk\""))
        assertTrue(payload.contains("\"type\":\"run\""))
        assertTrue(payload.contains("\"type\":\"workout\""))
        assertTrue(payload.contains("\"raw_overlay_type\":7"))
        assertTrue(payload.contains("\"id\":\"1700001007:7\""))
    }

    @Test
    fun boundedPagesResumeAfterAPartialFailureWithoutLosingTheRemainder() = runTest {
        val rows = (1L..3001L).map { sample(1_700_000_000L + it, 95, 1) }
        var requests = 0
        val client = HttpClient(MockEngine {
            requests++
            respond(content = "", status = if (requests == 2) HttpStatusCode.ServiceUnavailable else HttpStatusCode.OK)
        })
        val settings = MapSettings()
        val service = PebbleFitOxygenExportService(
            settings, TestCipher(), client,
            readHealth = { after, limit -> rows.filter { it.timestamp > after }.take(limit) },
            readSessions = { _, _, _, _ -> emptyList() },
        )
        service.saveConfiguration("https://receiver.example", "secret")

        val partial = service.syncNow()
        assertEquals(3000, partial.uploaded, partial.message)
        assertEquals(rows[2999].timestamp, settings.getLong("pebblefit_health_scan_cursor", 0L))
        assertEquals(rows[2999].timestamp, settings.getLong("pebblefit_health_watermark", 0L))

        val resumed = service.syncNow()
        assertEquals(1, resumed.uploaded, resumed.message)
        assertEquals(rows.last().timestamp, settings.getLong("pebblefit_health_watermark", 0L))
        assertEquals(3, requests)
    }

    @Test
    fun sessionPagesRespectReceiverLimitAndResumeEqualStartTypesAfterFailure() = runTest {
        // Entry 1000 and 1001 share startTime but have different primary-key types.
        val sessions = (1L..999L).map { overlay(1_700_000_000L + it, 1) } +
            listOf(overlay(1_700_002_000L, 1), overlay(1_700_002_000L, 2))
        var requests = 0
        val accepted = mutableListOf<String>()
        val client = HttpClient(MockEngine { request ->
            requests++
            val batch = Json.parseToJsonElement((request.body as TextContent).text)
                .jsonObject.getValue("sessions").jsonArray
            assertTrue(batch.size <= 1000)
            if (requests == 2) respond("", HttpStatusCode.ServiceUnavailable)
            else {
                accepted += batch.map { it.jsonObject.getValue("id").jsonPrimitive.content }
                respond("", HttpStatusCode.OK)
            }
        })
        val settings = MapSettings()
        val service = PebbleFitOxygenExportService(settings, TestCipher(), client,
            readHealth = { _, _ -> emptyList() },
            readSessions = { after, afterType, _, limit -> sessions.filter {
                it.startTime > after || (it.startTime == after && it.type > afterType)
            }.take(limit) })
        service.saveConfiguration("https://receiver.example", "secret")
        assertEquals(1000, service.syncNow().uploaded)
        assertEquals(1, settings.getInt("pebblefit_session_scan_type", -1))
        assertEquals(1, service.syncNow().uploaded)
        assertEquals(1001, accepted.size)
        assertEquals(1001, accepted.toSet().size)
        assertTrue(accepted.contains("1700002000:2"))
    }

    @Test
    fun invalidFullPageDoesNotHideValidRowsAndRejectedSessionsDoNotPoisonBatch() = runTest {
        val invalid = (1L..3000L).map { sample(1_700_000_000L + it, 95, 1).copy(steps = 10001) }
        val valid = sample(1_700_004_000L, 95, 1)
        val rows = invalid + valid
        val sessions = listOf(overlay(1_700_003_000L, 1).copy(duration = 172801L), overlay(1_700_004_000L, 1))
        var requests = 0
        val client = HttpClient(MockEngine { request ->
            requests++
            val body = Json.parseToJsonElement((request.body as TextContent).text).jsonObject
            assertTrue(body.getValue("records").jsonArray.all { it.jsonObject.getValue("steps").jsonPrimitive.content == "0" })
            assertTrue(body.getValue("sessions").jsonArray.all { it.jsonObject.getValue("seconds").jsonPrimitive.content == "60" })
            respond("", HttpStatusCode.OK)
        })
        val service = PebbleFitOxygenExportService(MapSettings(), TestCipher(), client,
            readHealth = { after, limit -> rows.filter { it.timestamp > after }.take(limit) },
            readSessions = { after, afterType, _, limit -> sessions.filter {
                it.startTime > after || (it.startTime == after && it.type > afterType)
            }.take(limit) })
        service.saveConfiguration("https://receiver.example", "secret")
        val result = service.syncNow()
        assertEquals(2, result.uploaded)
        assertTrue(result.message.contains("Skipped 3001 invalid records"))
        assertEquals(2, requests)
    }

    @Test
    fun durableBackoffStopsPeriodicRequestsAndManualSuccessResetsIt() = runTest {
        var requests = 0
        val settings = MapSettings()
        val row = sample(1_700_000_000L, 96, 1)
        val client = HttpClient(MockEngine {
            requests++
            respond("", if (requests == 1) HttpStatusCode.InternalServerError else HttpStatusCode.OK)
        })
        fun service() = PebbleFitOxygenExportService(settings, TestCipher(), client,
            readHealth = { after, _ -> listOf(row).filter { it.timestamp > after } },
            readSessions = { _, _, _, _ -> emptyList() })
        val first = service()
        first.saveConfiguration("https://health.example", "token")
        assertTrue(first.syncNow().retryableFailure)
        assertEquals(1, first.consecutiveFailures)
        assertTrue(first.nextRetryAt > first.lastAttemptAt)
        val restarted = service()
        restarted.syncIfDue()
        assertEquals(1, requests)
        assertEquals(1, restarted.syncNow().uploaded)
        assertEquals(0, restarted.consecutiveFailures)
        assertEquals(0L, restarted.nextRetryAt)
    }

    @Test
    fun fullReconciliationIsBoundedResumesAndFindsLateOldHistory() = runTest {
        val settings = MapSettings()
        val client = HttpClient(MockEngine { respond("", HttpStatusCode.OK) })
        var reads = 0
        var late = false
        val old = sample(1_000_000_000L, 96, 1)
        val service = PebbleFitOxygenExportService(settings, TestCipher(), client,
            readHealth = { after, _ ->
                reads++
                if (late) listOf(old).filter { it.timestamp > after }
                else listOf(sample(maxOf(after + 1, 1_700_000_000L), 96, 1))
            }, readSessions = { _, _, _, _ -> emptyList() })
        service.saveConfiguration("https://health.example", "token")
        assertEquals(4, service.syncNow().uploaded)
        assertEquals(4, reads)
        assertEquals(0L, service.lastReconciliationAt)
        val cursor = settings.getLong("pebblefit_health_scan_cursor", 0L)
        assertTrue(cursor > old.timestamp)
        late = true
        service.syncNow() // EOF completes the existing scan.
        assertTrue(service.lastReconciliationAt > 0)
        settings.putLong("gravelex_export_reconciled", 0L) // next weekly scan due
        assertEquals(1, service.syncNow().uploaded)
        assertTrue(service.lastReconciliationAt > 0)
    }

    @Test
    fun cancellationDoesNotAcknowledgeOrCompleteHistoricalScan() = runTest {
        val settings = MapSettings()
        val entered = CompletableDeferred<Unit>()
        val client = HttpClient(MockEngine {
            entered.complete(Unit)
            awaitCancellation()
        })
        val service = PebbleFitOxygenExportService(settings, TestCipher(), client,
            readHealth = { after, _ -> listOf(sample(1_700_000_000L, 96, 1)).filter { it.timestamp > after } },
            readSessions = { _, _, _, _ -> emptyList() })
        service.saveConfiguration("https://health.example", "token")
        val run = async { service.syncNow() }
        entered.await()
        run.cancel()
        run.join()
        assertEquals(946684799L, settings.getLong("pebblefit_health_scan_cursor", 0L))
        assertEquals(0L, settings.getLong("pebblefit_health_watermark", 0L))
        assertEquals(0L, service.lastReconciliationAt)
        assertFalse(service.status.value.busy)
    }

    @Test
    fun automaticPollingAfterEofDoesNotReplayUnchangedHistory() = runTest {
        val settings = MapSettings()
        var requests = 0
        val row = sample(1_700_000_000L, 95, 1)
        val client = HttpClient(MockEngine { requests++; respond("", HttpStatusCode.OK) })
        val service = PebbleFitOxygenExportService(settings, TestCipher(), client,
            readHealth = { after, _ -> listOf(row).filter { it.timestamp > after } },
            readSessions = { _, _, _, _ -> emptyList() })
        service.saveConfiguration("https://health.example", "token")
        service.syncIfDue()
        assertEquals(1, requests)
        repeat(3) {
            settings.putLong("gravelex_export_next_poll", 0L) // next scheduled poll
            service.syncIfDue()
        }
        assertEquals(1, requests)
    }

    private fun overlay(start: Long, type: Int) = OverlayDataEntity(
        startTime = start, duration = 60L, type = type, steps = 0,
        restingKiloCalories = 0, activeKiloCalories = 0, distanceCm = 0, offsetUTC = 0,
    )

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
