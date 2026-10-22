package io.rebble.libpebblecommon.database.dao

import io.rebble.libpebblecommon.database.entity.HealthDataEntity
import kotlin.test.Test
import kotlin.test.assertEquals

class HealthMinuteMergeTest {
    private val minute = HealthDataEntity(1_700_000_000L, 20, 1, 2, 3, 0, 5, 6, 7, heartRate = 60)

    @Test fun equalStepReplayCanAddOxygen() {
        val updated = mergeHealthMinute(minute, minute.copy(spo2Percent = 97, spo2Quality = 4))
        assertEquals(97, updated.spo2Percent)
        assertEquals(4, updated.spo2Quality)
        assertEquals(20, updated.steps)
    }

    @Test fun lowerStepReplayCanAddOxygenWithoutLosingMovement() {
        val updated = mergeHealthMinute(minute, minute.copy(steps = 0, distanceCm = 0, spo2Percent = 96, spo2Quality = 3))
        assertEquals(20, updated.steps)
        assertEquals(7, updated.distanceCm)
        assertEquals(96, updated.spo2Percent)
    }

    @Test fun higherStepReplayCannotEraseOxygen() {
        val existing = minute.copy(spo2Percent = 98, spo2Quality = 2)
        val updated = mergeHealthMinute(existing, minute.copy(steps = 30))
        assertEquals(30, updated.steps)
        assertEquals(98, updated.spo2Percent)
        assertEquals(2, updated.spo2Quality)
    }

    @Test fun invalidOrMissingOxygenCannotEraseSavedReading() {
        val existing = minute.copy(spo2Percent = 98, spo2Quality = 2)
        for (value in listOf(0, -1, 101)) {
            assertEquals(existing, mergeHealthMinute(existing, minute.copy(spo2Percent = value)))
        }
    }
}
