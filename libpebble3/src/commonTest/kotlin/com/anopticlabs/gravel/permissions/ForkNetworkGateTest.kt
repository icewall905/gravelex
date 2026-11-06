package com.anopticlabs.gravel.permissions

import io.rebble.libpebblecommon.permissions.APP
import io.rebble.libpebblecommon.permissions.AppPermissions
import io.rebble.libpebblecommon.permissions.FakePermissionDao
import io.rebble.libpebblecommon.permissions.FixedClock
import io.rebble.libpebblecommon.permissions.NetworkGate
import io.rebble.libpebblecommon.permissions.NoWatches
import io.rebble.libpebblecommon.permissions.PermissionPolicy
import io.rebble.libpebblecommon.permissions.RunningApps
import io.rebble.libpebblecommon.permissions.installedAs
import io.rebble.libpebblecommon.permissions.subject
import io.rebble.libpebblecommon.permissions.testScope

import io.rebble.libpebblecommon.LibPebbleConfig
import io.rebble.libpebblecommon.LibPebbleConfigFlow
import io.rebble.libpebblecommon.WatchConfig
import io.rebble.libpebblecommon.WatchConfigFlow
import io.rebble.libpebblecommon.database.dao.FakeForkAppPermissionDao
import io.rebble.libpebblecommon.database.entity.LockerAppPermissionType
import io.rebble.libpebblecommon.locker.PermissionSetting
import io.rebble.libpebblecommon.locker.WatchappPermissionResolver
import io.rebble.libpebblecommon.plugin.PluginNetworkVerdict
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertIs

class ForkNetworkGateTest {
    @Test
    fun explicitForkDenialWinsAndRevocationAppliesImmediately() = runTest {
        val config = MutableStateFlow(LibPebbleConfig(watchConfig = WatchConfig(
            enablePlugins = true,
            permissionPolicy = PermissionPolicy.NeverAsk,
            watchappDefaultNetworkAllowed = true,
        )))
        val fork = WatchappPermissionResolver(FakeForkAppPermissionDao(), LibPebbleConfigFlow(config))
        val permissions = AppPermissions(FakePermissionDao(), installedAs(subject()), WatchConfigFlow(config),
            FixedClock(1_000), RunningApps(NoWatches), testScope, fork)
        val gate = NetworkGate(permissions, "Fixture", APP)
        assertIs<PluginNetworkVerdict.Allowed>(gate.check("https://example.org", false))
        fork.setWatchappPermission(APP, LockerAppPermissionType.Network, PermissionSetting.Deny)
        assertIs<PluginNetworkVerdict.Denied>(gate.check("https://example.org", false))
        fork.setWatchappPermission(APP, LockerAppPermissionType.Network, PermissionSetting.FollowGlobal)
        assertIs<PluginNetworkVerdict.Allowed>(gate.check("https://example.org", false))
    }

    @Test
    fun disablingPluginsDoesNotBypassForkDefaultDenial() = runTest {
        val config = MutableStateFlow(LibPebbleConfig(watchConfig = WatchConfig(enablePlugins = false)))
        val fork = WatchappPermissionResolver(FakeForkAppPermissionDao(), LibPebbleConfigFlow(config))
        val permissions = AppPermissions(FakePermissionDao(), installedAs(subject()), WatchConfigFlow(config),
            FixedClock(1_000), RunningApps(NoWatches), testScope, fork)
        assertIs<PluginNetworkVerdict.Denied>(NetworkGate(permissions, "Fixture", APP).check("https://example.org", false))
    }
}
