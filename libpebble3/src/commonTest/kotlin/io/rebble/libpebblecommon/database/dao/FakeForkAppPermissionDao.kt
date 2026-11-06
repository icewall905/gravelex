package io.rebble.libpebblecommon.database.dao

import io.rebble.libpebblecommon.database.entity.ForkAppPermission
import io.rebble.libpebblecommon.database.entity.LockerAppPermissionType
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import kotlin.uuid.Uuid

/**
 * In-memory stand-in for the Room DAO, backed by a single state flow so the reactive
 * queries used by the permission resolver emit on change. Shared by every test that
 * exercises the watchapp permission model (resolver, geolocation gate, PKJS bridge
 * gate), so they all resolve through the same storage semantics as production:
 * row absence = FollowGlobal.
 */
class FakeForkAppPermissionDao : ForkAppPermissionDao {
    private val rows = MutableStateFlow<Map<Pair<Uuid, LockerAppPermissionType>, ForkAppPermission>>(emptyMap())

    override suspend fun insertOrReplace(permission: ForkAppPermission) {
        rows.value = rows.value + ((permission.appUuid to permission.permission) to permission)
    }

    override suspend fun deleteByAppUuid(appUuid: Uuid) {
        rows.value = rows.value.filterKeys { it.first != appUuid }
    }

    override suspend fun deleteByAppUuidAndPermission(appUuid: Uuid, permission: LockerAppPermissionType) {
        rows.value = rows.value - (appUuid to permission)
    }

    override suspend fun getByAppUuid(appUuid: Uuid): List<ForkAppPermission> =
        rows.value.values.filter { it.appUuid == appUuid }

    override suspend fun getByAppUuidAndPermission(
        appUuid: Uuid,
        permission: LockerAppPermissionType,
    ): ForkAppPermission? = rows.value[appUuid to permission]

    override fun getByAppUuidAndPermissionFlow(
        appUuid: Uuid,
        permission: LockerAppPermissionType,
    ): Flow<ForkAppPermission?> = rows.map { it[appUuid to permission] }
}
