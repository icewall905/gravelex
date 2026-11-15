package io.rebble.libpebblecommon.time

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import io.rebble.libpebblecommon.connection.AppContext

class AndroidTimeChangedReceiver(private val context: Context) : TimeChanged {
    override fun registerForTimeChanges(onChanged: () -> Unit) {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) {
                if (intent?.action == Intent.ACTION_TIMEZONE_CHANGED) {
                    // The framework resets this process's cached default zone from a separate
                    // binder call that can land after this broadcast; drop the cache ourselves so
                    // the sync below reads the new zone instead of the old one.
                    java.util.TimeZone.setDefault(null)
                }
                onChanged()
            }
        }
        val filter = IntentFilter()
        filter.addAction(Intent.ACTION_TIME_CHANGED)
        filter.addAction(Intent.ACTION_TIMEZONE_CHANGED)
        context.registerReceiver(receiver, filter)
    }
}

actual fun createTimeChanged(appContext: AppContext): TimeChanged =
    AndroidTimeChangedReceiver(appContext.context)