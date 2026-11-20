package com.anopticlabs.gravel.workout

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import kotlinx.serialization.json.*
import java.util.Locale
import kotlin.math.*

internal fun duration(ms: Long): String {
    val seconds = ms.coerceAtLeast(0) / 1000
    val hours = seconds / 3600
    val minutes = (seconds / 60 % 60).toString().padStart(2, '0')
    val remainder = (seconds % 60).toString().padStart(2, '0')
    return if (hours == 0L) "$minutes:$remainder" else "$hours:$minutes:$remainder"
}

internal fun distance(meters: Double): String = String.format(Locale.getDefault(), "%.2f km", meters / 1000)
internal fun pace(ms: Long, meters: Double): String = duration((ms * 1000 / meters).roundToLong()) + " /km"
internal fun speed(secondsPerKm: Double): String =
    String.format(Locale.getDefault(), "%.1f km/h", 3600 / secondsPerKm)

internal data class ChartPoint(val time: Long, val value: Double, val segment: Int = 0)
internal data class WorkoutSeries(
    val heart: List<ChartPoint>,
    val averageBpm: Int?,
    val pace: List<ChartPoint>,
    val altitude: List<ChartPoint>,
    val elevationGain: Double?,
    val splits: List<Long>,
)

internal fun workoutSeries(detail: WorkoutDetail): WorkoutSeries {
    val heart = detail.heart.map { ChartPoint(it.active, it.bpm.toDouble(), it.segment) }
    val avg = detail.heart.takeIf { it.isNotEmpty() }?.map { it.bpm }?.average()?.roundToInt()
    val altitude = detail.route.mapNotNull { fix -> fix.altitude?.let { ChartPoint(fix.active, it, fix.segment) } }
    var ascent = 0.0
    var reference: ChartPoint? = null
    for (point in altitude) {
        val prev = reference
        if (prev == null || prev.segment != point.segment) {
            reference = point
        } else if (abs(point.value - prev.value) >= 4) {
            ascent += max(0.0, point.value - prev.value)
            reference = point
        }
    }
    val paces = mutableListOf<ChartPoint>()
    val splits = mutableListOf<Long>()
    var splitStart = 0L
    var nextSplit = 1000.0
    var anchorIndex = 0
    for (i in 1 until detail.route.size) {
        val point = detail.route[i]
        val previous = detail.route[i - 1]
        if (point.segment != previous.segment) {
            anchorIndex = i
            continue
        }
        while (anchorIndex + 1 < i && point.active - detail.route[anchorIndex + 1].active >= 8000) anchorIndex++
        val anchor = detail.route[anchorIndex]
        val elapsed = point.active - anchor.active
        val delta = point.meters - anchor.meters
        if (elapsed >= 4000 && delta > 0) paces.add(ChartPoint(point.active, elapsed * 1000 / delta, point.segment))
        while (point.meters >= nextSplit && point.meters > previous.meters) {
            val fraction = (nextSplit - previous.meters) / (point.meters - previous.meters)
            val splitEnd = previous.active + ((point.active - previous.active) * fraction).roundToLong()
            splits.add(splitEnd - splitStart)
            splitStart = splitEnd
            nextSplit += 1000
        }
    }
    return WorkoutSeries(heart, avg, paces, altitude, ascent.takeIf { altitude.size >= 2 }, splits)
}

internal fun WorkoutDetail.pebbleFitPayload(): JsonObject = buildJsonObject {
    val active = (workout.active / 1000).toInt()
    val elapsed = ((workout.end - workout.start + 999) / 1000).toInt().coerceIn(active, 172800)
    put("id", workout.id)
    put("start", workout.start / 1000)
    put("seconds", elapsed)
    put("active_seconds", active)
    put("type", workout.sport.name)
    workout.rpe?.let { put("rpe", it) }
    if (route.isNotEmpty()) put("distance_m", distance)
    put("heart", buildJsonArray {
        heartBuckets(heart, active).forEach { bucket ->
            add(buildJsonArray { add(bucket.offset); add(bucket.bpm); add(bucket.seconds) })
        }
    })
}

private data class Projected(val x: Double, val y: Double, val segment: Int)

@Composable
internal fun RouteTrace(route: List<Fix>) {
    val color = MaterialTheme.colorScheme.primary
    val finish = MaterialTheme.colorScheme.secondary
    val grid = MaterialTheme.colorScheme.outlineVariant
    val projected = remember(route) {
        val origin = route.first()
        val latitudeScale = cos(Math.toRadians(origin.lat))
        val stride = (route.size / 2000).coerceAtLeast(1)
        route.filterIndexed { index, fix ->
            index % stride == 0 || index == route.lastIndex ||
                route.getOrNull(index - 1)?.segment != fix.segment || route.getOrNull(index + 1)?.segment != fix.segment
        }.map {
            val longitude = (it.lon - origin.lon + 540) % 360 - 180
            Projected(longitude * latitudeScale * 111_195, (origin.lat - it.lat) * 111_195, it.segment)
        }
    }
    val minX = remember(projected) { projected.minOf { it.x } }
    val maxX = remember(projected) { projected.maxOf { it.x } }
    val minY = remember(projected) { projected.minOf { it.y } }
    val maxY = remember(projected) { projected.maxOf { it.y } }
    var zoom by remember { mutableFloatStateOf(1f) }
    var pan by remember { mutableStateOf(Offset.Zero) }
    Surface(shape = MaterialTheme.shapes.large, color = MaterialTheme.colorScheme.surface) {
        Box(Modifier.fillMaxWidth().height(226.dp)) {
            Canvas(Modifier.fillMaxSize().semantics { contentDescription = "GPS route, north up" }
                .pointerInput(Unit) {
                    detectTransformGestures { centroid, change, scale, _ ->
                        val nextZoom = (zoom * scale).coerceIn(1f, 8f)
                        val delta = centroid - Offset(size.width / 2f, size.height / 2f)
                        pan = if (nextZoom == 1f) Offset.Zero else {
                            val next = delta - (delta - pan) * (nextZoom / zoom) + change
                            Offset(next.x.coerceIn(-size.width * nextZoom / 2, size.width * nextZoom / 2),
                                next.y.coerceIn(-size.height * nextZoom / 2, size.height * nextZoom / 2))
                        }
                        zoom = nextZoom
                    }
                }) {
                val metersPerPixel = max(max((maxX - minX) / (size.width * .77), (maxY - minY) / (size.height * .72)), .05) / zoom
                fun offset(p: Projected) = center + pan + Offset(
                    ((p.x - (minX + maxX) / 2) / metersPerPixel).toFloat(),
                    ((p.y - (minY + maxY) / 2) / metersPerPixel).toFloat(),
                )
                clipRect {
                    for (step in 1..7) {
                        val x = size.width * step / 8
                        val y = size.height * step / 8
                        drawLine(grid.copy(alpha = .35f), Offset(x, 0f), Offset(x, size.height))
                        drawLine(grid.copy(alpha = .35f), Offset(0f, y), Offset(size.width, y))
                    }
                    for (i in 1 until projected.size) {
                        if (projected[i - 1].segment == projected[i].segment) {
                            drawLine(color, offset(projected[i - 1]), offset(projected[i]), 3.dp.toPx(), StrokeCap.Round)
                        }
                    }
                    drawCircle(color, 4.dp.toPx(), offset(projected.first()))
                    if (projected.size > 1) drawCircle(finish, 4.dp.toPx(), offset(projected.last()))
                }
            }
            Text("N ↑", Modifier.align(Alignment.TopEnd).padding(12.dp), color = color)
            Text("GPS route", Modifier.align(Alignment.BottomStart).padding(12.dp),
                style = MaterialTheme.typography.labelMedium)
        }
    }
}

@Composable
internal fun WorkoutChart(
    title: String,
    points: List<ChartPoint>,
    active: Long,
    color: Color,
    reverse: Boolean = false,
    gapMs: Long = 30_000,
    label: (Double) -> String,
) {
    if (points.isEmpty()) return
    val grid = MaterialTheme.colorScheme.outlineVariant
    val min = remember(points) { points.minOf { it.value } }
    val max = remember(points) { points.maxOf { it.value } }
    var selected by remember(points) { mutableStateOf<ChartPoint?>(null) }
    val span = maxOf(active, points.last().time, 1L)
    val rendered = remember(points) {
        // Compress dense plots without losing low and high readings or GPS segment boundaries.
        val chunkSize = (points.size / 1000).coerceAtLeast(1)
        var group = 0
        val grouped = points.mapIndexed { index, point ->
            val previous = points.getOrNull(index - 1)
            if (previous != null && (point.segment != previous.segment || point.time - previous.time > gapMs)) group++
            point.copy(segment = group)
        }
        grouped.chunked(chunkSize).flatMap { chunk ->
            if (chunk.first().segment != chunk.last().segment) {
                chunk.filterIndexed { index, point ->
                    chunk.getOrNull(index - 1)?.segment != point.segment || chunk.getOrNull(index + 1)?.segment != point.segment
                }
            } else {
                listOf(chunk.first(), chunk.minBy { it.value }, chunk.maxBy { it.value }, chunk.last()).distinct().sortedBy { it.time }
            }
        }
    }
    Text(title, style = MaterialTheme.typography.titleLarge)
    Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween) {
        Text(selected?.let { duration(it.time) } ?: label(if (reverse) min else max),
            style = MaterialTheme.typography.labelMedium)
        Text(selected?.let { label(it.value) }.orEmpty(), color = color, style = MaterialTheme.typography.labelLarge)
    }
    Canvas(Modifier.fillMaxWidth().height(106.dp).padding(vertical = 6.dp)
        .semantics { contentDescription = "$title chart, ${label(min)} to ${label(max)}" }
        .pointerInput(points, span) {
            detectTapGestures { offset ->
                val target = (offset.x / size.width * span).toLong()
                val index = points.binarySearchBy(target) { it.time }.let { if (it >= 0) it else -it - 1 }
                selected = listOfNotNull(points.getOrNull(index - 1), points.getOrNull(index)).minByOrNull { abs(it.time - target) }
            }
        }) {
        fun position(p: ChartPoint): Offset {
            val fraction = if (max == min) .5 else (p.value - min) / (max - min)
            return Offset(size.width * (p.time.toDouble() / span).toFloat(),
                size.height * (if (reverse) fraction else 1 - fraction).toFloat())
        }
        for (line in 0..3) {
            val y = size.height * line / 3
            drawLine(grid, Offset(0f, y), Offset(size.width, y), 1.dp.toPx())
        }
        if (rendered.size == 1) drawCircle(color, 3.dp.toPx(), position(rendered.single()))
        for (i in 1 until rendered.size) {
            val a = rendered[i - 1]
            val b = rendered[i]
            if (a.segment == b.segment) {
                drawLine(color, position(a), position(b), 2.dp.toPx(), StrokeCap.Round)
            } else {
                drawCircle(color, 2.dp.toPx(), position(b))
            }
        }
        selected?.let {
            val p = position(it)
            drawLine(color.copy(alpha = .55f), Offset(p.x, 0f), Offset(p.x, size.height))
            drawCircle(color, 4.dp.toPx(), p)
        }
    }
    Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween) {
        Text(label(if (reverse) max else min), style = MaterialTheme.typography.labelMedium)
        Text(duration(span), style = MaterialTheme.typography.labelMedium)
    }
}
