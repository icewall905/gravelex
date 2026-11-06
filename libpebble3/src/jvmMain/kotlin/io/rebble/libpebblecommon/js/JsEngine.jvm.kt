package io.rebble.libpebblecommon.js

import io.rebble.libpebblecommon.connection.AppContext
import kotlinx.coroutines.CoroutineScope

actual class JsEngine actual constructor(appContext: AppContext, scope: CoroutineScope, name: String, interfaces: List<JsEngineInterface>) {
    actual suspend fun start() { error("Plugin JS execution is unavailable on JVM") }
    actual suspend fun stop() {}
    actual suspend fun eval(js: String) { error("Plugin JS execution is unavailable on JVM") }
}
