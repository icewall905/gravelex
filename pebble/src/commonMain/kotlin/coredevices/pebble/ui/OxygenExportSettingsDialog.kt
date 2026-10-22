package coredevices.pebble.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import coredevices.pebble.health.PebbleFitOxygenExportService
import kotlinx.coroutines.launch
import org.koin.compose.koinInject

@Composable
internal fun OxygenExportSettingsDialog(onDismiss: () -> Unit) {
    val service: PebbleFitOxygenExportService = koinInject()
    val scope = rememberCoroutineScope()
    val status by service.status.collectAsState()
    var url by remember { mutableStateOf(service.baseUrl) }
    var token by remember { mutableStateOf("") }
    var message by remember { mutableStateOf("") }

    fun save(): Boolean {
        val result = service.saveConfiguration(url, token)
        message = result.message
        if (result.saved) token = ""
        return result.saved
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("PebbleFit oxygen export") },
        text = {
            Column {
                Text(
                    "Upload watch oxygen readings from this phone to your health server. " +
                        "The bearer token is stored encrypted and is never shown after saving.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it },
                    modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                    label = { Text("Server URL") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                )
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it },
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    label = { Text(if (service.tokenConfigured && token.isBlank()) "Bearer token saved" else "Bearer token") },
                    placeholder = { Text("Leave blank to keep the saved token") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                )
                Text(
                    text = message.ifBlank { status.message },
                    modifier = Modifier.padding(top = 12.dp),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        },
        confirmButton = {
            Row {
                TextButton(onClick = {
                    if (save()) scope.launch { message = service.testConnection() }
                }) { Text("Test") }
                TextButton(onClick = {
                    if (save()) scope.launch {
                        message = ""
                        service.syncNow()
                    }
                }) { Text(if (status.busy) "Syncing…" else "Sync now") }
                TextButton(onClick = { if (save()) onDismiss() }) { Text("Save") }
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
