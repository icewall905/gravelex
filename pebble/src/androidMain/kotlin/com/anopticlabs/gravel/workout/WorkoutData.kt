package com.anopticlabs.gravel.workout

import java.io.Writer
import java.time.Instant
import kotlin.math.*

internal enum class Sport(val label: String, val gpsDefault: Boolean) {
    run("Running", true),
    hike("Hiking", true),
    walk("Walking", true),
    cycle("Cycling", true),
    strength("Strength", false),
    tennis("Tennis", false),
    rowing("Rowing", false),
    yoga("Yoga", false),
    workout("Other workout", false),
}

internal data class Workout(
    val id: String,
    val sport: Sport,
    val start: Long,
    val end: Long,
    val active: Long,
    val interrupted: Boolean = false,
    val rpe: Int? = null,
)

internal data class Fix(
    val time: Long, val active: Long, val segment: Int,
    val lat: Double, val lon: Double, val altitude: Double?,
    val accuracy: Float, val meters: Double,
)

internal data class Pulse(val active: Long, val bpm: Int, val time: Long, val segment: Int)
internal data class Lap(val active: Long, val meters: Double)
internal data class StrengthSet(val exercise: String, val reps: Int, val kg: Double?)
internal data class WorkoutDetail(
    val workout: Workout,
    val route: List<Fix>,
    val heart: List<Pulse>,
    val laps: List<Lap>,
    val sets: List<StrengthSet>,
) {
    val distance get() = route.lastOrNull()?.meters ?: 0.0
}

internal fun decodeHeartRate(bytes: ByteArray): Int? {
    val flags = bytes.firstOrNull()?.toInt() ?: return null
    // Bit 2 means contact detection is supported. Bit 1 then indicates contact.
    if (flags and 6 == 4 || bytes.size < 2) return null
    val low = bytes[1].toInt() and 255
    val bpm = if (flags and 1 == 0) low else {
        if (bytes.size < 3) return null
        low + ((bytes[2].toInt() and 255) shl 8)
    }
    return bpm.takeIf { it in 1..300 }
}

internal fun metersBetween(a: Fix, b: Fix): Double {
    val dLat = Math.toRadians(b.lat - a.lat)
    val dLon = Math.toRadians(b.lon - a.lon)
    val h = sin(dLat / 2).pow(2) +
        cos(Math.toRadians(a.lat)) * cos(Math.toRadians(b.lat)) * sin(dLon / 2).pow(2)
    return 12_742_000 * asin(sqrt(h.coerceIn(0.0, 1.0)))
}

internal fun appendFix(previous: Fix?, point: Fix): Fix? {
    if (point.accuracy !in 0f..25f || point.lat !in -90.0..90.0 || point.lon !in -180.0..180.0) return null
    if (previous == null) return point.copy(meters = 0.0)
    if (point.active <= previous.active) return null
    if (previous.segment != point.segment) return point.copy(meters = previous.meters)
    val elapsed = (point.active - previous.active) / 1000.0
    if (elapsed > 30) return point.copy(segment = point.segment + 1, meters = previous.meters)
    val distance = metersBetween(previous, point)
    if (distance > elapsed * 40 || distance < max(3.0, max(previous.accuracy, point.accuracy) * .5)) return null
    return point.copy(meters = previous.meters + distance)
}

internal fun WorkoutDetail.writeGpx(out: Writer) {
    out.write("""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="GravelEx" xmlns="http://www.topografix.com/GPX/1/1" xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
<trk><name>${workout.sport.label}</name><type>${workout.sport.name}</type>
""")
    var segment: Int? = null
    var pulseIndex = 0
    for (fix in route) {
        if (segment != fix.segment) {
            if (segment != null) out.write("</trkseg>\n")
            out.write("<trkseg>\n")
            segment = fix.segment
        }
        out.write("""<trkpt lat="${fix.lat}" lon="${fix.lon}">""")
        fix.altitude?.let { out.write("<ele>$it</ele>") }
        out.write("<time>${Instant.ofEpochMilli(fix.time)}</time>")
        while (pulseIndex < heart.size && heart[pulseIndex].active <= fix.active) pulseIndex++
        heart.getOrNull(pulseIndex - 1)?.takeIf { fix.time - it.time in 0..3000 && fix.segment == it.segment }?.let {
            out.write("<extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>${it.bpm}</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions>")
        }
        out.write("</trkpt>\n")
    }
    if (segment != null) out.write("</trkseg>\n")
    out.write("</trk></gpx>\n")
}

internal data class HeartBucket(val offset: Int, val bpm: Int, val seconds: Int)

/** Quantize by observed seconds; empty buckets and Bluetooth gaps stay unobserved. */
internal fun heartBuckets(heart: List<Pulse>, activeSeconds: Int): List<HeartBucket> =
    heart.groupBy { (it.active / 1000).toInt() }.filterKeys { it in 0 until activeSeconds }
        .entries.groupBy { it.key / 60 }.toSortedMap().map { (minute, observations) ->
            HeartBucket(
                minute * 60,
                observations.map { entry -> entry.value.map { it.bpm }.average() }.average().roundToInt(),
                observations.size,
            )
        }


/** Six groups, beginning below 50% of configured maximum heart rate. */
internal fun zoneSeconds(samples: List<Pulse>, maxBpm: Int): List<Int> {
    require(maxBpm in 100..240)
    val result = MutableList(6) { 0 }
    samples.groupBy { it.active / 1000 }.values.forEach { second ->
        val percent = second.map { it.bpm }.average() / maxBpm * 100
        result[(percent.toInt() / 10 - 4).coerceIn(0, 5)]++
    }
    return result
}
