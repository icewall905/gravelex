package io.rebble.libpebblecommon.database.dao

import co.touchlab.kermit.Logger
import io.rebble.libpebblecommon.database.entity.HealthDataEntity
import io.rebble.libpebblecommon.database.entity.OverlayDataEntity

private val logger = Logger.withTag("HealthDaoExt")

/**
 * Inserts health data with priority based on step count. If data already exists for a timestamp,
 * keeps the higher-step movement record and merges independently arriving oxygen readings.
 */
suspend fun HealthDao.insertHealthDataWithPriority(data: List<HealthDataEntity>) {
    var inserted = 0
    var skipped = 0
    var replaced = 0

    data.forEach { newData ->
        val existing = getDataAtTimestamp(newData.timestamp)
        if (existing == null) {
            insertHealthData(listOf(newData))
            inserted++
        } else {
            val merged = mergeHealthMinute(existing, newData)
            if (merged != existing) {
                insertHealthData(listOf(merged))
                replaced++
            } else {
                skipped++
            }
        }
    }

    val summary = buildString {
        append("Health data insert complete: ")
        if (inserted > 0) append("$inserted new, ")
        if (replaced > 0) append("$replaced updated (movement or oxygen), ")
        if (skipped > 0) append("$skipped skipped (lower/equal steps)")
    }
    logger.d { summary }
}

/** Movement and oxygen arrive independently: a duplicate step total can add SpO2. */
internal fun mergeHealthMinute(existing: HealthDataEntity, incoming: HealthDataEntity): HealthDataEntity {
    require(existing.timestamp == incoming.timestamp)
    val movement = if (incoming.steps > existing.steps) incoming else existing
    val oxygen = when {
        incoming.spo2Percent in 1..100 -> incoming
        existing.spo2Percent in 1..100 -> existing
        else -> return movement
    }
    return movement.copy(spo2Percent = oxygen.spo2Percent, spo2Quality = oxygen.spo2Quality)
}

/**
 * Inserts overlay data (sleep, activities) while preventing duplicates.
 * An overlay entry is considered duplicate if it has the same startTime and type.
 * When duplicates exist, keeps the entry with the longer duration to prevent data loss.
 */
suspend fun HealthDao.insertOverlayDataWithDeduplication(data: List<OverlayDataEntity>) {
    if (data.isEmpty()) return

    var inserted = 0
    var skipped = 0
    var replaced = 0

    data.forEach { newData ->
        val existing = getOverlayAtStartTimeAndType(newData.startTime, newData.type)
        if (existing == null) {
            insertOverlayData(listOf(newData))
            inserted++
        } else if (newData.duration > existing.duration) {
            logger.d {
                "Replacing overlay at startTime ${newData.startTime}, type ${newData.type}: ${existing.duration}s -> ${newData.duration}s (gained ${newData.duration - existing.duration}s)"
            }
            insertOverlayData(listOf(newData))
            replaced++
        } else if (newData.duration < existing.duration) {
            logger.d {
                "Skipping overlay at startTime ${newData.startTime}, type ${newData.type}: existing ${existing.duration}s > new ${newData.duration}s"
            }
            skipped++
        } else {
            // Same duration - skip as duplicate
            skipped++
        }
    }

    val summary = buildString {
        append("Overlay data insert complete: ")
        if (inserted > 0) append("$inserted new, ")
        if (replaced > 0) append("$replaced replaced (longer duration), ")
        if (skipped > 0) append("$skipped skipped (shorter/equal duration)")
    }
    logger.d { summary }
}
