package vn.smsbridge.sender

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class SmsDeliverReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        EventLog.append(
            context,
            org.json.JSONObject()
                .put("stage", "SMS_DELIVER")
                .put("timestamp", System.currentTimeMillis())
        )
    }
}
