package io.rebble.libpebblecommon.database.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import io.rebble.libpebblecommon.database.entity.ForkAppPermission
import io.rebble.libpebblecommon.database.entity.LockerAppPermissionType
import kotlinx.coroutines.flow.Flow
import kotlin.uuid.Uuid

@Dao
interface ForkAppPermissionDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertOrReplace(permission: ForkAppPermission)

    @Query("DELETE FROM LockerAppPermission WHERE appUuid = :appUuid")
    suspend fun deleteByAppUuid(appUuid: Uuid)

    // Fork: needed for the tri-state per-app model. Removing the (app, permission)
    // row is how "follow the global default" is represented: absence of a row
    // means the app has no explicit override, so the global default applies.
    @Query("DELETE FROM LockerAppPermission WHERE appUuid = :appUuid AND permission = :permission")
    suspend fun deleteByAppUuidAndPermission(appUuid: Uuid, permission: LockerAppPermissionType)

    @Query("SELECT * FROM LockerAppPermission WHERE appUuid = :appUuid")
    suspend fun getByAppUuid(appUuid: Uuid): List<ForkAppPermission>

    @Query("SELECT * FROM LockerAppPermission WHERE appUuid = :appUuid AND permission = :permission")
    suspend fun getByAppUuidAndPermission(appUuid: Uuid, permission: LockerAppPermissionType): ForkAppPermission?

    // Fork: reactive variant so settings/detail UI reflects toggles live and the
    // per-app WebView enforcement can re-evaluate without polling.
    @Query("SELECT * FROM LockerAppPermission WHERE appUuid = :appUuid AND permission = :permission")
    fun getByAppUuidAndPermissionFlow(appUuid: Uuid, permission: LockerAppPermissionType): Flow<ForkAppPermission?>
}
