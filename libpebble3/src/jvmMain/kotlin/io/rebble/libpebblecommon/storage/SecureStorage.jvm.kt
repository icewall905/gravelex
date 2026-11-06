package io.rebble.libpebblecommon.storage

import io.rebble.libpebblecommon.connection.AppContext
import kotlin.uuid.Uuid

internal actual fun pluginSecureStorage(appContext: AppContext, pluginUuid: Uuid): SecureStorage =
    error("Platform secure storage is unavailable on JVM")
