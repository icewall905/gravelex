package coredevices.pebble.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import coredevices.pebble.health.PebbleFitOxygenExportService
import coredevices.util.AppResumed
import io.rebble.libpebblecommon.connection.LibPebble
import io.rebble.libpebblecommon.connection.ConnectedPebbleDevice
import kotlinx.coroutines.flow.merge
import kotlinx.coroutines.launch
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime
import org.koin.compose.koinInject
import kotlin.time.Clock
import kotlin.time.Duration.Companion.days

@Composable
internal fun OxygenSetupStatusDialog(
    onDismiss: () -> Unit,
    onConfigureExport: () -> Unit,
) {
    val libPebble: LibPebble = koinInject()
    val exportService: PebbleFitOxygenExportService = koinInject()
    val appResumed: AppResumed = koinInject()
    val healthSettings by libPebble.healthSettings.collectAsState(null)
    val exportStatus by exportService.status.collectAsState()
    val scope = rememberCoroutineScope()
    var latest by remember { mutableStateOf<io.rebble.libpebblecommon.database.entity.HealthDataEntity?>(null) }
    var recentCount by remember { mutableStateOf(0) }
    var message by remember { mutableStateOf("") }

    LaunchedEffect(libPebble, appResumed) {
        suspend fun refresh() {
            latest = libPebble.getLatestSpo2Reading()
            recentCount = libPebble.getSpo2ReadingCountSince(Clock.System.now().minus(30.days).epochSeconds)
        }
        refresh()
        merge(libPebble.healthDataUpdated, appResumed.appResumed).collect { refresh() }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Blood oxygen setup & status") },
        text = {
            Column(Modifier.heightIn(max = 360.dp).verticalScroll(rememberScrollState())) {
                Text("Watch monitoring: ${healthSettings?.bloodOxygenEnabled?.let { if (it) "On" else "Off" } ?: "Unknown — waiting for the watch preference"}")
                Text("Latest local reading: ${latest?.let { "${it.spo2Percent}% · ${formatOxygenTimestamp(it.timestamp)} · ${oxygenQualityLabel(it.spo2Quality)} (${it.spo2Quality})" } ?: "—"}", modifier = Modifier.padding(top = 6.dp))
                Text("Readings in the last 30 days: $recentCount", modifier = Modifier.padding(top = 4.dp))
                Text("Sensor quality is reported by the watch and is not a clinical assessment.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
                Text("Request watch history asks the watch to transfer stored samples. Upload now sends samples already stored on this phone to the configured server.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))

                Text("GravelEx export: ${if (exportService.enabled) "Enabled" else "Disabled"}", modifier = Modifier.padding(top = 12.dp))
                Text("Bearer token: ${if (exportService.tokenConfigured) "Configured" else "Not configured"}")
                Text("Last acknowledged batch: ${exportService.lastSuccessfulUploadAt?.let(::formatOxygenTimestamp) ?: "None recorded"}${exportService.lastSuccessfulUploadCount?.let { " · $it records" } ?: ""}")
                Text("Current status: ${exportStatus.message}", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp))
                if (message.isNotBlank()) Text(message, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 2.dp))
            }
        },
        confirmButton = {
            Column {
                Row {
                    TextButton(onClick = {
                        val connected = libPebble.watches.value.any { it is ConnectedPebbleDevice }
                        if (connected) {
                            libPebble.requestHealthData(fullSync = true)
                            message = "History request submitted to the connected watch. Uploading is a separate action."
                        } else {
                            message = "Connect the watch before requesting its stored history."
                        }
                    }) { Text("Request watch history") }
                    TextButton(
                        enabled = !exportStatus.busy,
                        onClick = { scope.launch { message = exportService.syncNow().message } },
                    ) { Text(if (exportStatus.busy) "Uploading…" else "Upload now") }
                }
                Row {
                    TextButton(onClick = onConfigureExport) { Text("Configure export") }
                    TextButton(onClick = onDismiss) { Text("Done") }
                }
            }
        },
    )
}

// Firmware HealthRateQuality values stored in DLS v14: 0 none, 1 off-wrist,
// 3 worst, 4 poor, 5 acceptable, 6 good, 7 excellent. Value 2 is reserved/unknown.
internal fun oxygenQualityLabel(rawQuality: Int): String = when (rawQuality) {
    0 -> "No quality value"
    1 -> "Off wrist"
    3 -> "Worst signal"
    4 -> "Poor signal"
    5 -> "Acceptable signal"
    6 -> "Good signal"
    7 -> "Excellent signal"
    else -> "Unknown quality"
}

internal fun formatOxygenTimestamp(epochSeconds: Long): String {
    val local = kotlin.time.Instant.fromEpochSeconds(epochSeconds).toLocalDateTime(TimeZone.currentSystemDefault())
    val hour = local.hour % 12
    val hour12 = if (hour == 0) 12 else hour
    val amPm = if (local.hour < 12) "AM" else "PM"
    return "${local.month.shortName()} ${local.dayOfMonth}, ${local.year} · $hour12:${local.minute.toString().padStart(2, '0')} $amPm"
}
