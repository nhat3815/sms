package vn.smsbridge.sender

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        val prefs = context.getSharedPreferences(CloudSyncService.PREFS, Context.MODE_PRIVATE)
        if (prefs.getString(CloudSyncService.SERVER_URL, "").isNullOrBlank() &&
            prefs.getString(CloudSyncService.LAN_SERVER_URL, "").isNullOrBlank() &&
            prefs.getString(CloudSyncService.WAN_SERVER_URL, "").isNullOrBlank()) return
        val serviceIntent = Intent(context, CloudSyncService::class.java)
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            context.startForegroundService(serviceIntent)
        } else {
            context.startService(serviceIntent)
        }
    }
}
