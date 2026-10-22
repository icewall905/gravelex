package io.rebble.libpebblecommon.database.entity

import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertNull
import io.rebble.libpebblecommon.database.entity.BloodOxygenPreferencesValue.Companion.asBytes
import io.rebble.libpebblecommon.database.entity.BloodOxygenPreferencesValue.Companion.encodeToString
import io.rebble.libpebblecommon.util.DataBuffer

class BloodOxygenPreferencesTest {
    @Test
    fun enabledPreferenceUsesSingleOneByteValue() {
        assertContentEquals(byteArrayOf(1), BloodOxygenPreferencesValue(true).asBytes().asByteArray())
        assertContentEquals(byteArrayOf(0), BloodOxygenPreferencesValue(false).asBytes().asByteArray())
    }

    @Test
    fun preferenceJsonRoundTripsAndMissingValueRemainsUnknown() {
        val enabled = BloodOxygenPreferencesValue(true).encodeToString()
        val disabled = BloodOxygenPreferencesValue(false).encodeToString()

        assertEquals(true, BloodOxygenPreferencesValue.fromString(enabled)?.enabled)
        assertEquals(false, BloodOxygenPreferencesValue.fromString(disabled)?.enabled)
        assertNull(BloodOxygenPreferencesValue.fromString(null))
    }

    @Test
    fun unspecifiedPreferenceDoesNotCreateAWriteValue() {
        assertNull(bloodOxygenPreferenceValueIfSpecified(null))
        assertEquals(
            BloodOxygenPreferencesValue(enabled = false).encodeToString(),
            bloodOxygenPreferenceValueIfSpecified(false),
        )
        assertEquals(
            BloodOxygenPreferencesValue(enabled = true).encodeToString(),
            bloodOxygenPreferenceValueIfSpecified(true),
        )
    }

    @Test
    fun blobDecodesTheFirmwareBooleanByte() {
        val enabled = BloodOxygenPreferencesBlobItem(enabled = false)
        enabled.fromBytes(DataBuffer(ubyteArrayOf(1u)))
        assertEquals(1.toByte(), enabled.enabled.get())

        val disabled = BloodOxygenPreferencesBlobItem(enabled = true)
        disabled.fromBytes(DataBuffer(ubyteArrayOf(0u)))
        assertEquals(0.toByte(), disabled.enabled.get())
    }

    private fun UByteArray.asByteArray(): ByteArray = toList().map { it.toByte() }.toByteArray()
}
