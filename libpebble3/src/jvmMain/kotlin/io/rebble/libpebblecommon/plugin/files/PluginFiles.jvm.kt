package io.rebble.libpebblecommon.plugin.files

import com.russhwolf.settings.Settings
import io.rebble.libpebblecommon.connection.AppContext

internal actual fun platformPluginFileSystem(appContext: AppContext, settings: Settings): PluginFileSystem =
    error("Platform plugin files are unavailable on JVM")
