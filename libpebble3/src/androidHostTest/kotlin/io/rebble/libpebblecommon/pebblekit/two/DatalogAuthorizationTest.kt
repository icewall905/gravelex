package io.rebble.libpebblecommon.pebblekit.two

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class DatalogAuthorizationTest {
    @Test
    fun deliveryRequiresEnabledAuthorizedCompanionAndPseudonym() {
        var calls = 0
        val pseudonym = { calls++; "private-id" }
        assertNull(datalogWatchIdentifier(false, true, pseudonym))
        assertNull(datalogWatchIdentifier(true, false, pseudonym))
        assertEquals(0, calls)
        assertNull(datalogWatchIdentifier(true, true) { null })
        assertEquals("private-id", datalogWatchIdentifier(true, true, pseudonym))
        assertEquals(1, calls)
    }
}
