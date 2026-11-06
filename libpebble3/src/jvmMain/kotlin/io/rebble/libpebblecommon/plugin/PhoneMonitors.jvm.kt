package io.rebble.libpebblecommon.plugin

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf

actual class PhoneBatteryMonitor { actual val batteryLevel: Flow<Int?> = flowOf(null) }
actual class PhoneNetworkMonitor {
    actual val cellGeneration: Flow<String?> = flowOf(null)
    actual val connection: Flow<String?> = flowOf(null)
}
actual class PhoneSoundPlayer {
    actual val isRinging: Flow<Boolean> = flowOf(false)
    actual fun startRinging() { error("Phone sound is unavailable on JVM") }
    actual fun stopRinging() {}
}
