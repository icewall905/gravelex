package io.rebble.libpebblecommon.connection.bt.ble.pebble

import co.touchlab.kermit.Logger
import com.juul.kable.GattStatusException
import io.rebble.libpebblecommon.connection.bt.ble.transport.ConnectedGattClient
import io.rebble.libpebblecommon.di.ConnectionCoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.io.IOException
import kotlin.time.Duration.Companion.seconds
import kotlin.time.Duration.Companion.minutes
import kotlin.time.Clock
import kotlin.uuid.Uuid

class BatteryWatcher(
    private val scope: ConnectionCoroutineScope,
)  {
    private val logger = Logger.withTag("BatteryWatcher")
    private val _battery = MutableStateFlow<Int?>(null)
    val batteryLevel: StateFlow<Int?> = _battery.asStateFlow()
    private val _batteryObservedAt = MutableStateFlow<Long?>(null)
    /** Unix seconds when the watch battery value was read from GATT. */
    val batteryObservedAt: StateFlow<Long?> = _batteryObservedAt.asStateFlow()
    private var connectedGattClient: ConnectedGattClient? = null

    suspend fun subscribe(gattClient: ConnectedGattClient) {
        connectedGattClient = gattClient
        val batterySub = gattClient.subscribeToCharacteristic(BATTERY_SERVICE_UUID, BATTERY_LEVEL_CHARACTERISTIC_UUID)
        if (batterySub == null) {
            logger.e("batterySub is null")
            return
        }
        scope.launch {
            // There is some weird timing thing where this throws a GATT error "Authorization is
            // insufficient", if done too early.
            delay(2.seconds)
            if (!batterySub.collectBatteryChanges()) {
                delay(10.seconds)
                logger.i { "retrying batterySub.collectBatteryChanges()" }
                if (!batterySub.collectBatteryChanges()) {
                    logger.w { "failed to subscribe to battery changes after retry" }
                }
            }
        }
        val initialLevelBytes = try {
            gattClient.readCharacteristic(BATTERY_SERVICE_UUID, BATTERY_LEVEL_CHARACTERISTIC_UUID)
        } catch (e: GattStatusException) {
            logger.e(e) { "failed to read battery level" }
            null
        }
        val initialLevel = initialLevelBytes?.asBatteryLevel()
        logger.v { "initial batteryLevel = $initialLevel (raw: ${initialLevelBytes?.toHexString()})" }
        initialLevel?.let {
            _battery.value = it
            _batteryObservedAt.value = Clock.System.now().epochSeconds
        }
        // Some watch firmware does not emit a notification unless the value changes.
        // Refresh periodically so the observation timestamp represents a real GATT read
        // and the health hub can distinguish a live watch from a stale cached value.
        scope.launch {
            while (true) {
                delay(5.minutes)
                refresh()
            }
        }
    }

    suspend fun refresh(): Boolean {
        val client = connectedGattClient ?: return false
        return try {
            val level = client.readCharacteristic(BATTERY_SERVICE_UUID, BATTERY_LEVEL_CHARACTERISTIC_UUID)
                ?.asBatteryLevel() ?: return false
            _battery.value = level
            _batteryObservedAt.value = Clock.System.now().epochSeconds
            true
        } catch (e: GattStatusException) {
            logger.w(e) { "failed to refresh battery level" }
            false
        } catch (e: IOException) {
            logger.w(e) { "failed to refresh battery level" }
            false
        }
    }

    private suspend fun Flow<ByteArray>.collectBatteryChanges(): Boolean {
        try {
            collect { bytes ->
                val batteryLevel = bytes.asBatteryLevel()
                batteryLevel.also { logger.v { "battery level changed: $batteryLevel (raw: ${bytes.toHexString()})" } }
                batteryLevel?.let {
                    _battery.value = it
                    _batteryObservedAt.value = Clock.System.now().epochSeconds
                }
            }
            return true
        } catch (e: GattStatusException) {
            // Android
            logger.e(e) { "batterySub.collect ${e.message}" }
            return false
        } catch (e: IOException) {
            // iOS
            logger.e(e) { "batterySub.collect ${e.message}" }
            return false
        }
    }

    companion object {
        private const val BLUETOOTH_BASE_UUID_POSTFIX = "0000-1000-8000-00805F9B34FB"
        private val BATTERY_SERVICE_UUID: Uuid = Uuid.parse("0000180F-$BLUETOOTH_BASE_UUID_POSTFIX")
        private val BATTERY_LEVEL_CHARACTERISTIC_UUID: Uuid = Uuid.parse("00002A19-$BLUETOOTH_BASE_UUID_POSTFIX")
    }
}

internal fun ByteArray.asBatteryLevel(): Int? =
    if (size == 1) this[0].toInt().and(0xff).takeIf { it in 0..100 } else null
