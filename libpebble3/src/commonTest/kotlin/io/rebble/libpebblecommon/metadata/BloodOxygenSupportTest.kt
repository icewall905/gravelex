package io.rebble.libpebblecommon.metadata

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class BloodOxygenSupportTest {
    @Test
    fun onlySupportedObelixFirmwareGetsBloodOxygenSettings() {
        assertTrue(WatchHardwarePlatform.CORE_OBELIX_PVT.supportsBloodOxygen("v4.41.1"))
        assertTrue(WatchHardwarePlatform.CORE_OBELIX_DVT.supportsBloodOxygen("v4.42.0"))
        assertFalse(WatchHardwarePlatform.CORE_OBELIX_PVT.supportsBloodOxygen("v4.41.0"))
        assertFalse(WatchHardwarePlatform.PEBBLE_ROBERT_BIGBOARD.supportsBloodOxygen("v4.41.1"))
        assertFalse(WatchHardwarePlatform.CORE_GETAFIX_DVT.supportsBloodOxygen("v4.50.0"))
    }
}
