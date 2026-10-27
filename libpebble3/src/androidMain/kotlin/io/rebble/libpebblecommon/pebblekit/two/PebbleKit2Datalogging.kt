package io.rebble.libpebblecommon.pebblekit.two

import android.content.Context
import android.content.Intent
import io.rebble.libpebblecommon.WatchConfigFlow
import io.rebble.libpebblecommon.datalogging.Datalogging
import io.rebble.libpebblecommon.datalogging.ThirdPartyDatalogEvent
import io.rebble.libpebblecommon.di.LibPebbleCoroutineScope
import io.rebble.libpebblecommon.disk.pbw.PbwApp
import io.rebble.libpebblecommon.locker.Locker
import io.rebble.libpebblecommon.locker.LockerPBWCache
import io.rebble.pebblekit2.common.model.DataLogSession
import io.rebble.pebblekit2.common.model.ReceiveResult
import io.rebble.pebblekit2.common.model.WatchIdentifier
import io.rebble.pebblekit2.server.DefaultPebbleListenerConnector
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.time.Instant
import kotlin.uuid.Uuid
import kotlin.uuid.toJavaUuid

/**
 * Delivers third-party data logging sessions to companion apps over PebbleKit 2. Not tied to a
 * running watchapp: spooled data can arrive on reconnect while no watchapp is open.
 */
class PebbleKit2Datalogging(
    private val context: Context,
    private val datalogging: Datalogging,
    private val locker: Locker,
    private val lockerPBWCache: LockerPBWCache,
    private val coroutineScope: LibPebbleCoroutineScope,
    private val watchConfig: WatchConfigFlow,
    private val companionRegistry: PebbleKitCompanionRegistry,
    private val watchIdentity: PebbleKitWatchIdentity,
) {
    private val delivery = DatalogDelivery(coroutineScope, ::senderFor)

    fun init() {
        coroutineScope.launch {
            datalogging.thirdPartyEvents.collect { delivery.enqueue(it) }
        }
    }

    private suspend fun senderFor(uuid: Uuid): DatalogSender? {
        if (!watchConfig.value.pebbleKit2Enabled) return null
        val pkg = withContext(Dispatchers.IO) {
            companionPackagesFor(uuid).firstOrNull {
                companionRegistry.isAuthorizedFor(it, uuid.toString()) &&
                    context.packageManager.queryIntentServices(
                        Intent("io.rebble.pebblekit2.RECEIVE_DATA_FROM_WATCH").setPackage(it), 0
                    ).isNotEmpty()
            }
        } ?: return null
        val connector = DefaultPebbleListenerConnector(context, listOf(pkg))
        return object : DatalogSender {
            private fun identifier(serial: String): String? = datalogWatchIdentifier(
                enabled = watchConfig.value.pebbleKit2Enabled,
                authorized = companionRegistry.isAuthorizedFor(pkg, uuid.toString()),
                pseudonym = { watchIdentity.pseudonymFor(pkg, serial) },
            )

            override suspend fun sendBatch(event: ThirdPartyDatalogEvent.Batch): Boolean {
                val id = identifier(event.watchSerial) ?: return false
                return connector.sendOnDataLogReceived(
                    event.uuid.toJavaUuid(), event.toDataLogSession(), event.data,
                    event.itemsLeft.toLong(), WatchIdentifier(id),
                ) == ReceiveResult.Ack
            }

            override suspend fun sendFinished(event: ThirdPartyDatalogEvent.Finished): Boolean {
                val id = identifier(event.watchSerial) ?: return false
                return connector.sendOnDataLogSessionFinished(
                    event.uuid.toJavaUuid(), event.toDataLogSession(), WatchIdentifier(id),
                ) == ReceiveResult.Ack
            }

            override fun close() = connector.close()
        }
    }

    private suspend fun companionPackagesFor(uuid: Uuid): List<String> = withContext(Dispatchers.IO) {
        val entry = locker.getApp(uuid) ?: return@withContext emptyList()
        val pbwPath = lockerPBWCache.getPBWFileForApp(entry.id, entry.version, locker)
        PbwApp(pbwPath).info.companionApp?.android?.apps.orEmpty().mapNotNull { it.pkg }
    }
}

private fun ThirdPartyDatalogEvent.toDataLogSession() = DataLogSession(
    tag = tag.toLong(),
    timestamp = Instant.fromEpochSeconds(timestamp.toLong()),
    itemSize = itemSize.toInt(),
)

internal fun datalogWatchIdentifier(enabled: Boolean, authorized: Boolean, pseudonym: () -> String?): String? =
    if (enabled && authorized) pseudonym() else null
