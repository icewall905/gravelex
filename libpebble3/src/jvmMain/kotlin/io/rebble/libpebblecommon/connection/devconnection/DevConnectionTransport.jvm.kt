package io.rebble.libpebblecommon.connection.devconnection

import kotlinx.io.files.Path
import java.util.UUID

internal actual fun getTempPath(extension: String): Path =
    Path(System.getProperty("java.io.tmpdir"), "devconn-${UUID.randomUUID()}.$extension")
