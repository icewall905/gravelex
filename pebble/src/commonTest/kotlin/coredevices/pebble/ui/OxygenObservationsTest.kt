package coredevices.pebble.ui

import io.rebble.libpebblecommon.database.entity.HealthDataEntity
import kotlin.test.Test
import kotlin.test.assertEquals

class OxygenObservationsTest {
    @Test
    fun observationsFilterRangeEndInvalidSamplesAndFutureDataWithoutFillingGaps() {
        val rows = listOf(
            sample(120, 0),
            sample(180, 95),
            sample(240, 101),
            sample(60, 97),
            sample(100, 98),
            sample(200, 96), // exclusive range end
            sample(201, 94), // outside the selected range
            sample(190, 93), // future but still inside the selected range
        )

        val actual = validOxygenObservations(rows, start = 100, end = 200, now = 180)

        assertEquals(listOf(180L, 100L), actual.map { it.timestamp })
        assertEquals(listOf(95, 98), actual.map { it.spo2Percent })
    }

    private fun sample(timestamp: Long, percent: Int) = HealthDataEntity(
        timestamp = timestamp,
        steps = 0,
        orientation = 0,
        intensity = 0,
        lightIntensity = 0,
        activeMinutes = 0,
        restingGramCalories = 0,
        activeGramCalories = 0,
        distanceCm = 0,
        spo2Percent = percent,
        spo2Quality = 6,
    )
}
