package coredevices.libindex.device

import coredevices.haversine.KMPHaversineSatelliteManager
import kotlin.time.Duration

interface IndexSystem {
    suspend fun forceFailsafe(scanResult: IndexScanResult)
    suspend fun measureRSSI(device: IndexDevice, connectionTimeout: Duration): RSSIMeasurement
}

class RealIndexSystem(
    private val satelliteManager: KMPHaversineSatelliteManager
): IndexSystem {
    private val RSSI_SAMPLES = 20

    override suspend fun forceFailsafe(scanResult: IndexScanResult) {
        // GravelEx cannot obtain a Ring satellite from its inert provider.
        requireNotNull(satelliteManager.getSatelliteById(scanResult.identifier.asString)).forceFailsafe()
    }

    override suspend fun measureRSSI(device: IndexDevice, connectionTimeout: Duration): RSSIMeasurement {
        val satellite = requireNotNull(satelliteManager.getSatelliteById(device.identifier.asString)) {
            "Index 01 is not connected"
        }
        error("Ring RSSI measurement is unavailable in GravelEx")
    }
}