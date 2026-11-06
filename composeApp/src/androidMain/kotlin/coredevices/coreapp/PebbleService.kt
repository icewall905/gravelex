package coredevices.coreapp

import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationChannelCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import co.touchlab.kermit.Logger
import coredevices.util.R
import org.koin.core.component.KoinComponent
import org.koin.core.component.inject

class PebbleService: Service(), KoinComponent {
    companion object {
        const val NOTIFICATION_CHANNEL_ID = "pebble"
        const val NOTIFICATION_CHANNEL_NAME = "Gravel Service"

        private val logger = Logger.withTag("PebbleService")
    }

    private val notificationManagerCompat: NotificationManagerCompat by lazy {
        NotificationManagerCompat.from(this)
    }
    private val pebbleBackgroundManager: PebbleBackgroundManager by inject()

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        logger.v { "onStartCommand()" }
        val notificationChannel = NotificationChannelCompat.Builder(
            NOTIFICATION_CHANNEL_ID,
            NotificationManager.IMPORTANCE_MIN)
        .setName(NOTIFICATION_CHANNEL_NAME)
        .build()
        notificationManagerCompat.createNotificationChannel(notificationChannel)

        val contentIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(this, NOTIFICATION_CHANNEL_ID)
            .setContentTitle("Gravel")
            .setContentText("Keeping watch connection alive")
            .setOngoing(true)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentIntent(contentIntent)
            .build()
        try {
            ServiceCompat.startForeground(
                this,
                1,
                notification,
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
                } else {
                    0
                }
            )
        } catch (e: Exception) {
            // Couldn't foreground: SecurityException (missing connectedDevice prerequisites on
            // 14+) or ForegroundServiceStartNotAllowedException (sticky restart while app is
            // backgrounded). Must stop before the FGS timeout or the system throws
            // ForegroundServiceDidNotStartInTimeException
            logger.w(e) { "Error starting FG service" }
            stopSelf(startId)
            return START_NOT_STICKY
        }
        pebbleBackgroundManager.onServiceStarted()
        return START_STICKY
    }

    override fun onDestroy() {
        pebbleBackgroundManager.onServiceStopped()
        notificationManagerCompat.cancel(1)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? {
        return null
    }
}
