package coredevices.pebble.weather

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ParseCoordinateTest {
    @Test
    fun parsesValidCoordinates() {
        assertEquals(51.5074, parseLatitude("51.5074"))
        assertEquals(-0.1278, parseLongitude(" -0.1278 "))
        assertEquals(-122.4, parseLongitude("-122,4"))
        assertEquals(90.0, parseLatitude("90"))
    }

    @Test
    fun rejectsInvalidCoordinates() {
        assertNull(parseLatitude(""))
        assertNull(parseLatitude("abc"))
        assertNull(parseLatitude("90.1"))
        assertNull(parseLongitude("-180.5"))
    }

    @Test
    fun rejectsNonDecimalForms() {
        assertNull(parseLatitude("1e1"))
        assertNull(parseLatitude("NaN"))
    }

    @Test
    fun manualEntryIsMarkedManual() {
        assertEquals(true, manualWeatherLocation(51.5, -0.1, "London", orderIndex = 0).manual)
    }
}
