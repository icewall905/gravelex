package com.anopticlabs.gravel.workout

import android.annotation.SuppressLint
import android.bluetooth.*
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import java.util.UUID

internal fun bluetoothUuid(shortId: String) = UUID.fromString("0000$shortId-0000-1000-8000-00805f9b34fb")
internal val heartService = bluetoothUuid("180d")
internal val heartScanFilter = ScanFilter.Builder().setServiceUuid(ParcelUuid(heartService)).build()
internal val heartScanSettings = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build()

@SuppressLint("MissingPermission")
internal class ChestStrap(
    context: Context,
    private val address: String,
    private val status: (String) -> Unit,
    private val pulse: (Int) -> Unit,
) : AutoCloseable {
    private val app = context.applicationContext
    private val handler = Handler(Looper.getMainLooper())
    private val adapter = app.getSystemService(BluetoothManager::class.java)?.adapter
    private var gatt: BluetoothGatt? = null
    private var closed = false
    private val deadline = Runnable { retry("Strap unavailable. Reconnecting…") }

    fun connect() {
        if (closed) return
        status("Connecting to chest strap…")
        gatt = runCatching {
            adapter?.getRemoteDevice(address)?.connectGatt(app, false, callback, BluetoothDevice.TRANSPORT_LE)
        }.getOrNull()
        handler.postDelayed(deadline, if (gatt == null) 4000 else 15000)
    }

    private fun retry(message: String) {
        handler.removeCallbacks(deadline)
        releaseGatt()
        if (closed) return
        status(message)
        handler.postDelayed({ connect() }, 4000)
    }

    private fun releaseGatt() {
        val current = gatt
        gatt = null
        runCatching { current?.close() }
    }

    private fun current(device: BluetoothGatt, action: () -> Unit) {
        handler.post {
            if (gatt === device && !closed) {
                try {
                    action()
                } catch (_: SecurityException) {
                    retry("Bluetooth permission unavailable")
                }
            }
        }
    }

    private val callback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(device: BluetoothGatt, result: Int, state: Int) = current(device) {
            if (result != BluetoothGatt.GATT_SUCCESS || state == BluetoothProfile.STATE_DISCONNECTED) {
                retry("Chest strap disconnected. Reconnecting…")
            } else if (state == BluetoothProfile.STATE_CONNECTED && !device.discoverServices()) {
                retry("Could not read chest strap services")
            }
        }

        @Suppress("DEPRECATION")
        override fun onServicesDiscovered(device: BluetoothGatt, result: Int) = current(device) {
            val measurement = device.getService(heartService)?.getCharacteristic(bluetoothUuid("2a37"))
            val descriptor = measurement?.getDescriptor(bluetoothUuid("2902"))
            if (result != BluetoothGatt.GATT_SUCCESS || measurement == null || descriptor == null ||
                !device.setCharacteristicNotification(measurement, true)
            ) {
                retry("Heart rate service unavailable")
                return@current
            }
            val value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
            val started = if (Build.VERSION.SDK_INT >= 33) {
                device.writeDescriptor(descriptor, value) == BluetoothStatusCodes.SUCCESS
            } else {
                descriptor.value = value
                device.writeDescriptor(descriptor)
            }
            if (!started) retry("Could not subscribe to heart rate")
        }

        override fun onDescriptorWrite(device: BluetoothGatt, descriptor: BluetoothGattDescriptor, result: Int) = current(device) {
            if (result == BluetoothGatt.GATT_SUCCESS) {
                handler.removeCallbacks(deadline)
                status("Chest strap connected")
            } else {
                retry("Could not subscribe to heart rate")
            }
        }

        override fun onCharacteristicChanged(device: BluetoothGatt, characteristic: BluetoothGattCharacteristic, value: ByteArray) {
            if (characteristic.uuid != bluetoothUuid("2a37")) return
            decodeHeartRate(value)?.let { bpm -> current(device) { pulse(bpm) } }
        }

        @Deprecated("Compatibility callback for Android 12 and earlier")
        @Suppress("DEPRECATION")
        override fun onCharacteristicChanged(device: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
            characteristic.value?.let { onCharacteristicChanged(device, characteristic, it) }
        }
    }

    override fun close() {
        closed = true
        handler.removeCallbacksAndMessages(null)
        releaseGatt()
    }
}
