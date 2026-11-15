package io.rebble.libpebblecommon.services

import kotlin.time.Duration
import kotlin.time.Duration.Companion.hours
import kotlin.time.Duration.Companion.minutes
import kotlin.time.Duration.Companion.seconds
import kotlin.time.Instant

/**
 * When the phone re-sends its clock to a connected watch.
 *
 * Coroutine `delay` runs on the monotonic clock, which on Android stops while the phone is in
 * deep sleep, so a plain `delay(1.hours)` loop can go many wall-clock hours without a sync. The
 * service instead ticks often and decides from the wall clock whether a sync is due, and on some
 * ticks asks the watch for its time and re-syncs if it has drifted.
 */
internal object TimeSyncPolicy {
    /** How often the sync loop wakes (in awake time). */
    val CHECK_INTERVAL: Duration = 5.minutes

    /** Wall-clock age after which the watch is re-synced regardless of measured drift. */
    val RESYNC_INTERVAL: Duration = 1.hours

    /** Ask the watch for its time on every Nth tick. */
    const val DRIFT_CHECK_EVERY_TICKS = 3

    /**
     * Largest watch/phone difference left alone. SetUTC and the watch reply are whole seconds and
     * there is link latency, so up to about one second is measurement noise.
     */
    val MAX_DRIFT: Duration = 2.seconds

    /** Due when never synced, the phone clock went backwards past the last sync, or it is stale. */
    fun isDue(lastSync: Instant?, now: Instant): Boolean =
        lastSync == null || now < lastSync || now - lastSync >= RESYNC_INTERVAL

    /**
     * Watch clock minus phone clock. PebbleOS answers GetTime with its UTC clock in seconds
     * (PebbleOS tests/integration/bluetooth/test_time_endpoint.py).
     */
    fun drift(watchUtcSeconds: Long, phoneNow: Instant): Duration =
        (watchUtcSeconds - phoneNow.epochSeconds).seconds

    fun needsResync(drift: Duration): Boolean = drift.absoluteValue >= MAX_DRIFT
}
