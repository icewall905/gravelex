package com.anopticlabs.gravel.workout

import org.xml.sax.InputSource
import java.io.StringReader
import java.io.StringWriter
import javax.xml.parsers.DocumentBuilderFactory
import kotlin.test.*

class WorkoutDataTest {
    @Test
    fun decodesBothBluetoothHeartRateFormatsAndRejectsLostContact() {
        assertEquals(165, decodeHeartRate(byteArrayOf(0, 165.toByte())))
        assertEquals(266, decodeHeartRate(byteArrayOf(1, 10, 1)))
        assertEquals(165, decodeHeartRate(byteArrayOf(6, 165.toByte())))
        assertNull(decodeHeartRate(byteArrayOf(4, 165.toByte())))
        assertNull(decodeHeartRate(byteArrayOf(1, 10)))
        assertNull(decodeHeartRate(byteArrayOf(0, 0)))
    }

    @Test
    fun accuracyJitterAndPausesDoNotInflateDistance() {
        val a = fix(1000, 0, 0.0)
        assertNull(appendFix(a, fix(2000, 0, .00001)))
        assertNull(appendFix(a, fix(2000, 0, .01)))
        assertNull(appendFix(a, fix(2000, 0, .0001).copy(accuracy = 60f)))
        val b = assertNotNull(appendFix(a, fix(4000, 0, .0002)))
        assertEquals(22.24, b.meters, .1)
        val paused = assertNotNull(appendFix(b, fix(6000, 1, .01)))
        assertEquals(b.meters, paused.meters)
        val gap = assertNotNull(appendFix(paused, fix(40_000, 1, .02)))
        assertEquals(2, gap.segment)
        assertEquals(b.meters, gap.meters)
    }

    @Test
    fun uploadBucketsCountOnlySecondsActuallyObserved() {
        val samples = listOf(
            Pulse(1000, 140, 1000, 0), Pulse(1400, 160, 1400, 0),
            Pulse(2200, 170, 2200, 0), Pulse(61_000, 125, 61_000, 0),
            Pulse(63_000, 150, 63_000, 0),
        )
        assertEquals(listOf(HeartBucket(0, 160, 2), HeartBucket(60, 125, 1)), heartBuckets(samples, 63))
    }

    @Test
    fun gpxContainsSeparateRoutesAndDoesNotCarryHeartRateAcrossPause() {
        val last = fix(7000, 1, .01).copy(time = 120_000, altitude = null)
        val workout = Workout("test", Sport.run, 0, 120_000, 7000)
        val detail = WorkoutDetail(workout,
            listOf(fix(3000, 0, .0001), last), listOf(Pulse(2900, 160, 2900, 0)), emptyList(), emptyList())
        val xml = StringWriter().also(detail::writeGpx).toString()
        val parsed = DocumentBuilderFactory.newInstance().apply { isNamespaceAware = true }
            .newDocumentBuilder().parse(InputSource(StringReader(xml)))
        val gpx = "http://www.topografix.com/GPX/1/1"
        assertEquals(2, parsed.getElementsByTagNameNS(gpx, "trkseg").length)
        assertEquals(2, parsed.getElementsByTagNameNS(gpx, "time").length)
        assertEquals(1, parsed.getElementsByTagNameNS(gpx, "ele").length)
        assertEquals("160", parsed.getElementsByTagNameNS("http://www.garmin.com/xmlschemas/TrackPointExtension/v1", "hr")
            .item(0).textContent)
    }

    private fun fix(time: Long, segment: Int, lat: Double) =
        Fix(time, time, segment, lat, 0.0, 15.0, 5f, 0.0)
}
