package com.anopticlabs.gravel.workout

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coredevices.pebble.health.PebbleFitOxygenExportService
import coredevices.util.Permission
import coredevices.util.PermissionRequester
import coredevices.util.rememberUiContext
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.koin.compose.koinInject
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable
fun WorkoutEntry() {
    val context = LocalContext.current
    val recording by WorkoutRecorder.live.collectAsState()
    val open = { context.startActivity(Intent(context, WorkoutActivity::class.java)) }
    Row(Modifier.fillMaxWidth(), Arrangement.spacedBy(8.dp), Alignment.CenterVertically) {
        FilledTonalButton(onClick = open, modifier = Modifier.weight(1f)) {
            Text(if (recording == null) "Log workout" else "View recording")
        }
        TextButton(onClick = {
            context.startActivity(Intent(context, WorkoutActivity::class.java).putExtra("history", true))
        }) { Text("Workout history") }
    }
}

internal class WorkoutActivity : ComponentActivity() {
    private var screenVisible by mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
        )
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(
                background = Color(0xff101e24),
                surface = Color(0xff192b32),
                surfaceVariant = Color(0xff283c42),
                primary = Color(0xffa7ead9),
                onPrimary = Color(0xff142b2b),
                secondary = Color(0xfff4c18e),
                tertiary = Color(0xffc8c1f3),
            )) {
                WorkoutScreen(intent.getBooleanExtra("history", false), screenVisible, ::finish)
            }
        }
    }

    override fun onStart() { super.onStart(); screenVisible = true }
    override fun onStop() { screenVisible = false; super.onStop() }
}

@Composable
private fun WorkoutScreen(openHistory: Boolean, visible: Boolean, close: () -> Unit) {
    val context = LocalContext.current
    val live by WorkoutRecorder.live.collectAsState()
    val finished by WorkoutRecorder.finished.collectAsState()
    val error by WorkoutRecorder.error.collectAsState()
    val snackbar = remember { SnackbarHostState() }
    var history by rememberSaveable { mutableStateOf(openHistory) }
    var detailId by rememberSaveable { mutableStateOf<String?>(null) }
    var refresh by remember { mutableIntStateOf(0) }
    val storeResult by produceState<Result<WorkoutStore>?>(null) {
        value = withContext(Dispatchers.IO) { runCatching { WorkoutStore.get(context) } }
    }
    val store = storeResult?.getOrNull()

    LaunchedEffect(finished) {
        finished?.let {
            detailId = it
            history = true
            refresh++
            WorkoutRecorder.finished.compareAndSet(it, null)
        }
    }
    LaunchedEffect(error) {
        error?.let {
            refresh++
            snackbar.showSnackbar(it)
            WorkoutRecorder.error.compareAndSet(it, null)
        }
    }

    val title = live?.workout?.sport?.label ?: if (detailId != null) "Workout review" else if (history) "Workout history" else "Log workout"
    val back = {
        when {
            live != null -> close()
            detailId != null -> detailId = null
            history -> history = false
            else -> close()
        }
    }
    BackHandler { back() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(title, fontWeight = FontWeight.SemiBold) },
                navigationIcon = {
                    IconButton(onClick = back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
                },
                actions = {
                    if (!history && live == null) TextButton(onClick = { history = true }) { Text("History") }
                },
            )
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { insets ->
        Box(Modifier.padding(insets).fillMaxSize()) {
            val recording = live
            when {
                storeResult?.isFailure == true -> Text("Workout storage is unavailable.", Modifier.padding(20.dp))
                store == null -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                recording != null -> Recording(recording)
                detailId != null -> Review(store, detailId!!, snackbar) {
                    detailId = null
                    refresh++
                }
                history -> History(store, refresh) { detailId = it }
                else -> Setup(visible)
            }
        }
    }
}

private data class StrapChoice(val label: String, val address: String)

@SuppressLint("MissingPermission")
@Composable
private fun Setup(visible: Boolean) {
    val context = LocalContext.current
    val settings = remember { context.getSharedPreferences("workout_setup", 0) }
    val uiContext = rememberUiContext()
    val permissions = koinInject<PermissionRequester>()
    val scope = rememberCoroutineScope()
    var sport by rememberSaveable { mutableStateOf(Sport.run) }
    var gps by rememberSaveable { mutableStateOf(sport.gpsDefault) }
    var address by rememberSaveable { mutableStateOf(settings.getString("strap_address", null)) }
    var strapName by rememberSaveable { mutableStateOf(settings.getString("strap_name", null)) }
    var scanning by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    var starting by remember { mutableStateOf(false) }
    val found = remember { mutableStateMapOf<String, StrapChoice>() }
    val bluetoothPermissions = remember {
        if (Build.VERSION.SDK_INT >= 31) arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
    }
    fun granted(permission: String) = context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
    fun start() {
        if (!visible) return
        try {
            WorkoutRecorder.command(context, WorkoutRecorder.START) {
                putExtra("sport", sport.name)
                putExtra("gps", gps)
                putExtra("strap", address)
            }
            starting = true
        } catch (_: RuntimeException) {
            message = "Open the workout screen and try starting again."
        }
    }
    LaunchedEffect(starting) {
        if (starting) {
            delay(3000)
            starting = false
        }
    }
    suspend fun permitScan() {
        val ui = uiContext ?: return
        if (!bluetoothPermissions.all(::granted)) {
            val permission = if (Build.VERSION.SDK_INT >= 31) Permission.Bluetooth else Permission.Location
            permissions.requestPermission(permission, ui)
        }
        if (bluetoothPermissions.all(::granted)) scanning = true
        else message = "Allow Bluetooth access to find a chest strap."
    }

    suspend fun permitStart() {
        val ui = uiContext ?: return
        if (gps && !granted(Manifest.permission.ACCESS_FINE_LOCATION)) {
            permissions.requestPermission(Permission.Location, ui)
            if (!granted(Manifest.permission.ACCESS_FINE_LOCATION)) {
                message = "Allow precise location for a route, or turn off phone GPS."
                return
            }
        }
        if (address != null && Build.VERSION.SDK_INT >= 31 && !granted(Manifest.permission.BLUETOOTH_CONNECT)) {
            permissions.requestPermission(Permission.Bluetooth, ui)
            if (!granted(Manifest.permission.BLUETOOTH_CONNECT)) {
                message = "Allow Nearby devices for heart rate, or remove the selected strap."
                return
            }
        }
        if (Build.VERSION.SDK_INT >= 33 && !granted(Manifest.permission.POST_NOTIFICATIONS)) {
            permissions.requestPermission(Permission.PostNotifications, ui)
        }
        start()
    }

    LaunchedEffect(scanning, visible) {
        if (!visible) scanning = false
        if (scanning) {
            delay(12_000)
            scanning = false
            if (found.isEmpty()) message = "No straps found. Put on the strap, turn on Bluetooth, and scan again."
        }
    }
    DisposableEffect(scanning, visible) {
        if (!scanning || !visible) return@DisposableEffect onDispose {}
        found.clear()
        val scanner = runCatching { context.getSystemService(BluetoothManager::class.java)?.adapter?.bluetoothLeScanner }.getOrNull()
        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                val device = result.device
                val name = result.scanRecord?.deviceName ?: runCatching { device.name }.getOrNull()
                val suffix = device.address.takeLast(5)
                found[device.address] = StrapChoice(name ?: "Heart rate sensor ($suffix)", device.address)
            }

            override fun onScanFailed(errorCode: Int) {
                message = "Bluetooth scan failed. Try again."
                scanning = false
            }
        }
        if (scanner == null) {
            message = "Turn on Bluetooth to find your chest strap."
            scanning = false
        } else {
            runCatching { scanner.startScan(listOf(heartScanFilter), heartScanSettings, callback) }.onFailure {
                message = "Could not scan. Check Bluetooth permissions."
                scanning = false
            }
        }
        onDispose { runCatching { scanner?.stopScan(callback) } }
    }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item {
            Text("Activity", style = MaterialTheme.typography.titleLarge)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Sport.entries.forEach { option ->
                    FilterChip(selected = sport == option, onClick = { sport = option; gps = option.gpsDefault },
                        label = { Text(option.label) })
                }
            }
        }
        item {
            HorizontalDivider()
            Row(Modifier.fillMaxWidth().padding(top = 16.dp), Arrangement.SpaceBetween, Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Phone GPS", style = MaterialTheme.typography.titleMedium)
                    Text("Record your route, distance, pace and elevation.", style = MaterialTheme.typography.bodyMedium)
                }
                Switch(checked = gps, onCheckedChange = { gps = it })
            }
        }
        item {
            HorizontalDivider()
            Text("Heart rate", Modifier.padding(top = 16.dp), style = MaterialTheme.typography.titleMedium)
            Text(strapName ?: "Use a Bluetooth chest strap, such as Garmin HRM-Pro.")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = {
                    message = null
                    if (scanning) scanning = false else scope.launch { permitScan() }
                }) { Text(if (scanning) "Stop scan" else "Find chest strap") }
                if (address != null) TextButton(onClick = {
                    address = null
                    strapName = null
                    settings.edit().remove("strap_address").remove("strap_name").apply()
                }) { Text("Remove") }
            }
        }
        items(found.values.sortedBy { it.label }, key = { it.address }) { strap ->
            OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = {
                address = strap.address
                strapName = strap.label
                scanning = false
                found.clear()
                message = null
                settings.edit().putString("strap_address", strap.address).putString("strap_name", strap.label).apply()
            }) { Text(strap.label) }
        }
        if (scanning) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        message?.let { item { Text(it, color = MaterialTheme.colorScheme.secondary) } }
        item {
            Button(modifier = Modifier.fillMaxWidth().heightIn(min = 54.dp), enabled = !scanning && !starting, onClick = {
                message = null
                scope.launch { permitStart() }
            }) { Text(if (starting) "Starting…" else "Start ${sport.label.lowercase()}") }
        }
    }
}

@Composable
private fun Recording(state: LiveWorkout) {
    val context = LocalContext.current
    var finish by remember { mutableStateOf(false) }
    var addSet by remember { mutableStateOf(false) }
    val command = { action: String -> WorkoutRecorder.command(context, action) }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        item {
            Text(if (state.paused) "Paused" else "Active time", color = MaterialTheme.colorScheme.primary)
            Text(duration(state.active), fontSize = 54.sp, fontWeight = FontWeight.SemiBold, lineHeight = 60.sp)
        }
        item {
            HorizontalDivider()
            Row(Modifier.fillMaxWidth().padding(top = 16.dp), Arrangement.SpaceBetween) {
                if (state.gpsStatus.isNotEmpty()) Readout("Distance", distance(state.distance))
                if (state.strapStatus.isNotEmpty()) Readout("Heart rate", state.bpm?.let { "$it bpm" } ?: "—")
                if (state.workout.sport == Sport.strength) Readout("Sets", state.sets.toString())
                Readout("Laps", state.laps.toString())
            }
        }
        if (state.gpsStatus.isNotEmpty() || state.strapStatus.isNotEmpty()) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    if (state.gpsStatus.isNotEmpty()) Text(state.gpsStatus)
                    if (state.strapStatus.isNotEmpty()) Text(state.strapStatus)
                }
            }
        }
        if (state.route.isNotEmpty()) item { RouteTrace(state.route) }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(modifier = Modifier.weight(1f), onClick = { command(if (state.paused) WorkoutRecorder.RESUME else WorkoutRecorder.PAUSE) }) {
                    Text(if (state.paused) "Resume" else "Pause")
                }
                OutlinedButton(modifier = Modifier.weight(1f), enabled = !state.paused,
                    onClick = { command(WorkoutRecorder.LAP) }) { Text("Lap") }
            }
            if (state.workout.sport == Sport.strength) {
                FilledTonalButton(modifier = Modifier.fillMaxWidth(), onClick = { addSet = true }) { Text("Add strength set") }
            }
            TextButton(modifier = Modifier.fillMaxWidth(), onClick = { finish = true }) { Text("Finish workout") }
        }
    }
    if (finish) AlertDialog(
        onDismissRequest = { finish = false }, title = { Text("Finish workout?") },
        text = { Text("Save this recording to your workout history.") },
        confirmButton = { TextButton(onClick = { finish = false; command(WorkoutRecorder.FINISH) }) { Text("Finish and save") } },
        dismissButton = { TextButton(onClick = { finish = false }) { Text("Keep recording") } },
    )
    if (addSet) SetDialog(onDismiss = { addSet = false }) { set ->
        WorkoutRecorder.command(context, WorkoutRecorder.SET) {
            putExtra("exercise", set.exercise)
            putExtra("reps", set.reps)
            putExtra("kg", set.kg ?: Double.NaN)
        }
        addSet = false
    }
}

@Composable
private fun SetDialog(onDismiss: () -> Unit, save: (StrengthSet) -> Unit) {
    var exercise by rememberSaveable { mutableStateOf("") }
    var reps by rememberSaveable { mutableStateOf("") }
    var load by rememberSaveable { mutableStateOf("") }
    val count = reps.toIntOrNull()
    val kg = load.replace(',', '.').toDoubleOrNull()
    AlertDialog(
        onDismissRequest = onDismiss, title = { Text("Add strength set") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(exercise, { exercise = it.take(100) }, label = { Text("Exercise") }, singleLine = true)
                OutlinedTextField(reps, { reps = it.take(3) }, label = { Text("Reps") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                OutlinedTextField(load, { load = it.take(8) }, label = { Text("Weight (kg, optional)") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
            }
        },
        confirmButton = {
            TextButton(enabled = exercise.isNotBlank() && count != null && count in 1..999 &&
                (load.isBlank() || kg != null && kg.isFinite() && kg >= 0), onClick = {
                if (count != null) save(StrengthSet(exercise.trim(), count, kg))
            }) { Text("Save set") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun History(store: WorkoutStore, refresh: Int, open: (String) -> Unit) {
    val workouts by produceState<Result<List<Workout>>?>(null, refresh) {
        value = withContext(Dispatchers.IO) { runCatching { store.history() } }
    }
    val entries = workouts?.getOrNull()
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp)) {
        when {
            workouts?.isFailure == true -> item { Text("Could not load workout history.") }
            entries == null -> item { CircularProgressIndicator() }
            entries.isEmpty() -> item { Text("Your saved workouts will appear here.") }
            else -> items(entries, key = { it.id }) { entry ->
                Row(Modifier.fillMaxWidth().clickable { open(entry.id) }.padding(vertical = 14.dp),
                    Arrangement.SpaceBetween, Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(entry.sport.label, style = MaterialTheme.typography.titleMedium)
                        Text(workoutDate(entry.start) + if (entry.interrupted) " · Interrupted" else "",
                            style = MaterialTheme.typography.bodySmall)
                    }
                    Text(duration(entry.active), color = MaterialTheme.colorScheme.primary)
                }
                HorizontalDivider()
            }
        }
    }
}

@Composable
private fun Review(store: WorkoutStore, id: String, snackbar: SnackbarHostState, back: () -> Unit) {
    val hub: PebbleFitOxygenExportService = koinInject()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var version by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    var delete by remember { mutableStateOf(false) }
    var effort by remember { mutableStateOf(false) }
    val result by produceState<Result<WorkoutDetail?>?>(null, id, version) {
        value = withContext(Dispatchers.IO) { runCatching { store.detail(id) } }
    }
    val detail = result?.getOrNull()
    val export = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/gpx+xml")) { uri ->
        if (uri != null) {
            scope.launch {
                val resultMessage = try {
                    withContext(Dispatchers.IO) {
                        val recording = store.detail(id)?.takeIf { it.route.isNotEmpty() } ?: error("Route unavailable")
                        val stream = context.contentResolver.openOutputStream(uri, "wt") ?: error("Document unavailable")
                        stream.bufferedWriter(Charsets.UTF_8).use(recording::writeGpx)
                    }
                    "GPX saved"
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {
                    "Could not save GPX. Choose another file location."
                }
                snackbar.showSnackbar(resultMessage)
            }
        }
    }

    if (detail == null) {
        if (result == null) CircularProgressIndicator(Modifier.padding(20.dp))
        else Text("Could not open this workout.", Modifier.padding(20.dp))
        return
    }
    val workout = detail.workout
    val series = remember(detail) { workoutSeries(detail) }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
        item {
            Text(workoutDate(workout.start), color = MaterialTheme.colorScheme.primary)
            Text(workout.sport.label, style = MaterialTheme.typography.displaySmall, fontWeight = FontWeight.SemiBold)
            if (workout.interrupted) Text("Interrupted recording", color = MaterialTheme.colorScheme.secondary)
        }
        if (detail.route.isNotEmpty()) item { RouteTrace(detail.route) }
        item {
            Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween) {
                Readout("Active time", duration(workout.active))
                Readout("Elapsed", duration(workout.end - workout.start))
            }
            if (detail.route.isNotEmpty()) {
                Row(Modifier.fillMaxWidth().padding(top = 12.dp), Arrangement.SpaceBetween) {
                    Readout("Distance", distance(detail.distance))
                    if (detail.distance > 0 && workout.active > 0) {
                        if (workout.sport == Sport.cycle) {
                            Readout("Avg speed", speed(workout.active / detail.distance))
                        } else Readout("Avg pace", pace(workout.active, detail.distance))
                    }
                    series.elevationGain?.let { Readout("Ascent", "${it.toInt()} m") }
                }
            }
        }
        if (series.heart.isNotEmpty()) item {
            WorkoutChart("Heart rate", series.heart, workout.active, MaterialTheme.colorScheme.secondary, gapMs = 5000) { "${it.toInt()} bpm" }
            Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween) {
                Readout("Average", "${series.averageBpm} bpm")
                Readout("Peak", "${series.heart.maxOf { it.value }.toInt()} bpm")
            }
        }
        if (series.heart.isNotEmpty()) item { HeartZones(detail.heart) }
        if (series.pace.isNotEmpty()) item {
            if (workout.sport == Sport.cycle) {
                val speeds = remember(series.pace) { series.pace.map { it.copy(value = 3_600_000 / it.value) } }
                WorkoutChart("Speed", speeds, workout.active, MaterialTheme.colorScheme.primary) {
                    speed(3600 / it)
                }
            } else {
                WorkoutChart("Pace", series.pace, workout.active, MaterialTheme.colorScheme.primary, reverse = true) {
                    duration(it.toLong()) + " /km"
                }
            }
        }
        if (series.altitude.isNotEmpty()) item {
            WorkoutChart("Elevation", series.altitude, workout.active, MaterialTheme.colorScheme.tertiary) { "${it.toInt()} m" }
        }
        if (detail.distance >= 1000) item {
            Text("Kilometre splits", style = MaterialTheme.typography.titleLarge)
            series.splits.forEachIndexed { index, split ->
                BreakdownRow("${index + 1} km", duration(split))
            }
        }
        if (detail.laps.isNotEmpty()) item {
            Text("Laps", style = MaterialTheme.typography.titleLarge)
            (detail.laps + Lap(workout.active, detail.distance)).mapIndexedNotNull { index, lap ->
                val previous = detail.laps.getOrNull(index - 1) ?: Lap(0, 0.0)
                val time = lap.active - previous.active
                if (time <= 0) null else index + 1 to (duration(time) + "  ·  " + distance(lap.meters - previous.meters))
            }.forEach { (number, summary) -> BreakdownRow("Lap $number", summary) }
        }
        if (detail.sets.isNotEmpty()) item {
            Text("Strength sets", style = MaterialTheme.typography.titleLarge)
            detail.sets.forEachIndexed { index, set ->
                BreakdownRow("${index + 1}. ${set.exercise}", "${set.reps} reps" + (set.kg?.let { "  ·  $it kg" } ?: ""))
            }
        }
        item {
            HorizontalDivider()
            Row(Modifier.fillMaxWidth().padding(top = 12.dp), Arrangement.SpaceBetween, Alignment.CenterVertically) {
                Text("Perceived effort")
                TextButton(enabled = !busy, onClick = { effort = true }) {
                    Text(workout.rpe?.let { "$it / 10" } ?: "Add effort")
                }
            }
            Button(modifier = Modifier.fillMaxWidth(), enabled = !busy && workout.active >= 1000, onClick = {
                busy = true
                scope.launch {
                    try {
                        val payload = withContext(Dispatchers.Default) { detail.pebbleFitPayload() }
                        val message = hub.uploadPhoneWorkout(payload)
                        busy = false
                        snackbar.showSnackbar(message)
                    } finally {
                        busy = false
                    }
                }
            }) { Text(if (busy) "Sending…" else "Send to PebbleFit") }
            Text("Shares workout totals and heart-rate summaries with your configured PebbleFit server.")
            if (detail.route.isNotEmpty()) {
                OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = {
                    export.launch("${workout.sport.name}-${Instant.ofEpochMilli(workout.start).atZone(ZoneId.systemDefault()).toLocalDate()}.gpx")
                }) { Text("Save GPX") }
            }
            TextButton(enabled = !busy, onClick = { delete = true }) { Text("Delete from phone") }
        }
    }
    if (delete) AlertDialog(
        onDismissRequest = { delete = false }, title = { Text("Delete workout from phone?") },
        text = { Text("The local recording, route and sensor samples will be removed.") },
        confirmButton = {
            TextButton(onClick = {
                delete = false
                scope.launch {
                    val saved = withContext(Dispatchers.IO) { runCatching { store.delete(id) }.isSuccess }
                    if (saved) back() else snackbar.showSnackbar("Could not delete workout.")
                }
            }) { Text("Delete workout") }
        },
        dismissButton = { TextButton(onClick = { delete = false }) { Text("Cancel") } },
    )
    if (effort) {
        var value by remember { mutableFloatStateOf(workout.rpe?.toFloat() ?: 5f) }
        fun save(rpe: Int?) {
            effort = false
            scope.launch {
                val saved = withContext(Dispatchers.IO) { runCatching { store.effort(id, rpe) }.isSuccess }
                if (saved) version++ else snackbar.showSnackbar("Could not save effort.")
            }
        }
        AlertDialog(
            onDismissRequest = { effort = false }, title = { Text("Perceived effort") },
            text = {
                Column {
                    Text("${value.toInt()} / 10")
                    Slider(value, { value = it }, valueRange = 1f..10f, steps = 8)
                    Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween) { Text("Easy"); Text("Maximum") }
                }
            },
            confirmButton = { TextButton(onClick = { save(value.toInt()) }) { Text("Save effort") } },
            dismissButton = { TextButton(onClick = { save(null) }) { Text("Clear effort") } },
        )
    }
}

@Composable
private fun HeartZones(heart: List<Pulse>) {
    val context = LocalContext.current
    val settings = remember { context.getSharedPreferences("workout_setup", 0) }
    var maxBpm by remember { mutableIntStateOf(settings.getInt("max_bpm", 0)) }
    var editing by remember { mutableStateOf(false) }
    Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween, Alignment.CenterVertically) {
        Text("Heart-rate zones", style = MaterialTheme.typography.titleLarge)
        TextButton(onClick = { editing = true }) { Text(if (maxBpm == 0) "Set max HR" else "$maxBpm bpm max") }
    }
    if (maxBpm in 100..240) {
        val seconds = remember(heart, maxBpm) { zoneSeconds(heart, maxBpm) }
        val total = seconds.sum()
        val labels = listOf("Below 50%", "50–59%", "60–69%", "70–79%", "80–89%", "90% and above")
        for ((index, label) in labels.withIndex()) {
            Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), Arrangement.SpaceBetween) {
                Text(label)
                Text(duration(seconds[index] * 1000L))
            }
            LinearProgressIndicator(
                progress = { if (total == 0) 0f else seconds[index].toFloat() / total },
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.secondary,
            )
        }
    }
    if (editing) {
        var input by rememberSaveable { mutableStateOf(maxBpm.takeIf { it > 0 }?.toString().orEmpty()) }
        val value = input.toIntOrNull()
        AlertDialog(
            onDismissRequest = { editing = false },
            title = { Text("Maximum heart rate") },
            text = {
                OutlinedTextField(input, { input = it.take(3) }, label = { Text("Maximum BPM") },
                    singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
            },
            confirmButton = {
                TextButton(enabled = value != null && value in 100..240, onClick = {
                    if (value != null) {
                        settings.edit().putInt("max_bpm", value).apply()
                        maxBpm = value
                        editing = false
                    }
                }) { Text("Save") }
            },
            dismissButton = { TextButton(onClick = { editing = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun BreakdownRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), Arrangement.spacedBy(8.dp)) {
        Text(label, Modifier.weight(1f))
        Text(value)
    }
    HorizontalDivider()
}

@Composable
private fun Readout(label: String, value: String) {
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium)
        Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
    }
}

private val shortDate = DateTimeFormatter.ofPattern("EEE, d MMM yyyy · HH:mm")
private fun workoutDate(epoch: Long) = shortDate.format(Instant.ofEpochMilli(epoch).atZone(ZoneId.systemDefault()))
