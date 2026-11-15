package io.rebble.libpebblecommon.services

import io.rebble.libpebblecommon.packets.TimeMessage
import io.rebble.libpebblecommon.protocolhelpers.PebblePacket
import io.rebble.libpebblecommon.protocolhelpers.ProtocolEndpoint
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertTrue
import kotlin.time.Duration.Companion.minutes
import kotlin.time.Duration.Companion.seconds
import kotlin.time.Instant

class TimeSyncPolicyTest {
    private val t0 = Instant.fromEpochSeconds(1_800_000_000)

    @Test
    fun dueWhenNeverSynced() {
        assertTrue(TimeSyncPolicy.isDue(null, t0))
    }

    @Test
    fun notDueWithinInterval() {
        assertFalse(TimeSyncPolicy.isDue(t0, t0 + 59.minutes))
    }

    @Test
    fun dueAfterIntervalOfWallClock() {
        assertTrue(TimeSyncPolicy.isDue(t0, t0 + 60.minutes))
    }

    @Test
    fun dueWhenPhoneClockMovedBackwards() {
        assertTrue(TimeSyncPolicy.isDue(t0, t0 - 1.seconds))
    }

    @Test
    fun driftIsWatchUtcMinusPhoneUtc() {
        assertEquals(7.seconds, TimeSyncPolicy.drift(t0.epochSeconds + 7, t0))
        assertEquals((-3).seconds, TimeSyncPolicy.drift(t0.epochSeconds - 3, t0))
    }

    @Test
    fun oneSecondIsNoise() {
        assertFalse(TimeSyncPolicy.needsResync(1.seconds))
        assertFalse(TimeSyncPolicy.needsResync((-1).seconds))
        assertTrue(TimeSyncPolicy.needsResync(2.seconds))
        assertTrue(TimeSyncPolicy.needsResync((-90).seconds))
    }

    @Test
    fun getTimeResponseDecodes() {
        val time = 0x6B49D200u
        val bytes = TimeMessage.GetTimeResponse(time).serialize()
        val decoded = PebblePacket.deserialize(bytes)
        assertIs<TimeMessage.GetTimeResponse>(decoded)
        assertEquals(time, decoded.time.get())
        assertEquals(ProtocolEndpoint.TIME, decoded.endpoint)
    }
}
