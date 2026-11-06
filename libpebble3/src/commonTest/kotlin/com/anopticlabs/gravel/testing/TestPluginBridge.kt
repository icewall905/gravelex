package com.anopticlabs.gravel.testing

import com.russhwolf.settings.MapSettings
import io.rebble.libpebblecommon.RealLibPebbleAnalytics
import io.rebble.libpebblecommon.WatchConfigFlow
import io.rebble.libpebblecommon.di.LibPebbleCoroutineScope
import io.rebble.libpebblecommon.permissions.AppPermissions
import io.rebble.libpebblecommon.permissions.FakePermissionDao
import io.rebble.libpebblecommon.permissions.FixedClock
import io.rebble.libpebblecommon.permissions.NoWatches
import io.rebble.libpebblecommon.permissions.PermissionSubject
import io.rebble.libpebblecommon.permissions.RunningApps
import io.rebble.libpebblecommon.permissions.installedAs
import io.rebble.libpebblecommon.plugin.PluginClient
import io.rebble.libpebblecommon.plugin.PluginLogs
import io.rebble.libpebblecommon.plugin.PluginRegistry
import kotlinx.coroutines.CoroutineScope
import kotlin.uuid.Uuid

internal class TestPluginBridge(uuid: Uuid, config: WatchConfigFlow, scope: CoroutineScope) {
    val registry = PluginRegistry(emptySet(), config, MapSettings())
    private val running = RunningApps(NoWatches)
    val permissions = AppPermissions(FakePermissionDao(), installedAs(PermissionSubject(uuid, legacy = true)),
        config, FixedClock(1_000), running, LibPebbleCoroutineScope(scope.coroutineContext))
    val client = PluginClient(registry, permissions, running, RealLibPebbleAnalytics(), PluginLogs())
}
