package io.rebble.libpebblecommon.connection.bt.ble.pebble

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class BatteryLevelTest {
    @Test
    fun acceptsOnlySingleBytePercentages() {
        assertEquals(0, byteArrayOf(0).asBatteryLevel())
        assertEquals(100, byteArrayOf(100).asBatteryLevel())
        assertNull(byteArrayOf().asBatteryLevel())
        assertNull(byteArrayOf(45, 1).asBatteryLevel())
        assertNull(byteArrayOf(101).asBatteryLevel())
        assertNull(byteArrayOf(-1).asBatteryLevel())
    }
}
