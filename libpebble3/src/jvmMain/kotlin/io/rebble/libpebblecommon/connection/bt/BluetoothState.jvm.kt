package io.rebble.libpebblecommon.connection.bt

import com.juul.kable.Bluetooth
import io.rebble.libpebblecommon.connection.AppContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

actual fun nativeBluetoothStateFlow(appContext: AppContext): Flow<BluetoothState> =
    Bluetooth.availability.map { availability ->
        if (availability is Bluetooth.Availability.Available) BluetoothState.Enabled else BluetoothState.Disabled
    }

actual fun locationServicesBlockScanning(appContext: AppContext): Boolean = false
