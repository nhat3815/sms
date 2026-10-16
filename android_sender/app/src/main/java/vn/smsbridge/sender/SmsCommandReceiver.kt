package vn.smsbridge.sender

import android.app.PendingIntent
import android.content.ContentValues
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Telephony
import android.telephony.SmsManager
import android.telephony.SubscriptionManager
import android.telephony.ServiceState
import android.telephony.TelephonyManager
import org.json.JSONArray
import org.json.JSONObject
class SmsCommandReceiver : BroadcastReceiver() {
    companion object {
        const val DEFAULT_BRIDGE_SECRET = "SmsBridge_2026_Direct_Token"
        const val ACTION_SIM_STATUS = "vn.smsbridge.sender.SIM_STATUS"

        // Cache job_id gần nhất chống gửi lặp (Job ID -> Timestamp)
        private val processedJobIds = java.util.concurrent.ConcurrentHashMap<String, Long>()

        // Throttle cooldown chống gửi dồn tới cùng 1 số điện thoại (Phone -> Timestamp)
        private val recentPhoneDispatches = java.util.concurrent.ConcurrentHashMap<String, Long>()

        fun writeSimStatus(context: Context) {
            val subscriptions = JSONArray()
            val subscriptionManager = context.getSystemService(SubscriptionManager::class.java)
            val telephonyManager = context.getSystemService(TelephonyManager::class.java)
            if (context.checkSelfPermission(android.Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED) {
                for (info in subscriptionManager?.activeSubscriptionInfoList.orEmpty()) {
                    val subscriptionId = info.subscriptionId
                    val inService = try {
                        telephonyManager?.createForSubscriptionId(subscriptionId)?.serviceState?.state == ServiceState.STATE_IN_SERVICE
                    } catch (_: Exception) {
                        true
                    }
                    subscriptions.put(JSONObject()
                        .put("subscription_id", subscriptionId)
                        .put("slot_index", info.simSlotIndex)
                        .put("carrier_name", info.carrierName?.toString() ?: ("SIM " + (info.simSlotIndex + 1)))
                        .put("display_name", info.displayName?.toString() ?: ("SIM " + (info.simSlotIndex + 1)))
                        .put("in_service", inService))
                }
            }
            try {
                context.filesDir.resolve("sim_status.json").writeText(
                    JSONObject().put("subscriptions", subscriptions).put("timestamp", System.currentTimeMillis()).toString()
                )
            } catch (_: Exception) {}
        }
    }

    override fun onReceive(context: Context, intent: Intent) {
        var currentPhone = ""
        var currentMessage = ""
        var currentJobId = ""
        try {
            val token = intent.getStringExtra("token")
            val expected = context.filesDir.resolve("bridge_token").takeIf { it.exists() }?.readText()?.trim()
            val isTokenValid = (token != null && (token == expected || token == DEFAULT_BRIDGE_SECRET || expected == null))
            currentJobId = intent.getStringExtra("job_id") ?: ""
            currentPhone = intent.getStringExtra("phone") ?: ""
            currentMessage = intent.getStringExtra("message") ?: ""

            if (!isTokenValid) {
                if (currentJobId.isNotEmpty()) {
                    logError(context, currentJobId, "Xác thực token bảo mật thất bại (Token mismatch)", currentPhone, currentMessage)
                }
                return
            }
            if (intent.action == ACTION_SIM_STATUS) {
                writeSimStatus(context)
                return
            }
            val jobId = intent.getStringExtra("job_id") ?: return
            currentJobId = jobId

            val now = System.currentTimeMillis()

            // 1. Chống gửi trùng lặp theo job_id
            if (processedJobIds.putIfAbsent(jobId, now) != null) {
                EventLog.append(
                    context,
                    JSONObject()
                        .put("job_id", jobId)
                        .put("stage", "SKIPPED_DUPLICATE_JOB")
                        .put("detail", "Bỏ qua lệnh gửi trùng lặp job_id: $jobId")
                        .put("timestamp", now)
                )
                return
            }
            if (processedJobIds.size > 500) {
                val it = processedJobIds.entries.iterator()
                while (it.hasNext()) {
                    if (now - it.next().value > 300_000L) it.remove()
                }
            }

            val phone = intent.getStringExtra("phone") ?: run {
                logError(context, jobId, "Missing phone", "", currentMessage)
                return
            }
            currentPhone = phone

            // 2. Chống gửi dồn lặp tới cùng 1 số điện thoại trong vòng 45 giây
            val cleanPhone = phone.filter { it.isDigit() }
            val lastSentTime = recentPhoneDispatches[cleanPhone]
            if (lastSentTime != null && (now - lastSentTime) < 45_000L) {
                val waitAgoSec = (now - lastSentTime) / 1000
                val skipMsg = "Bỏ qua gửi trùng số $phone (vừa gửi cách đây ${waitAgoSec}s)"
                EventLog.append(
                    context,
                    JSONObject()
                        .put("job_id", jobId)
                        .put("phone", phone)
                        .put("stage", "SKIPPED_THROTTLE")
                        .put("detail", skipMsg)
                        .put("timestamp", now)
                )
                CloudSyncService.reportResult(
                    context = context,
                    jobId = jobId,
                    status = "FAILED",
                    detail = skipMsg,
                    phone = phone,
                    message = ""
                )
                return
            }
            recentPhoneDispatches[cleanPhone] = now
            if (recentPhoneDispatches.size > 500) {
                val it = recentPhoneDispatches.entries.iterator()
                while (it.hasNext()) {
                    if (now - it.next().value > 300_000L) it.remove()
                }
            }

            val message = intent.getStringExtra("message_b64")?.let { b64 ->
                try {
                    String(android.util.Base64.decode(b64.trim(), android.util.Base64.DEFAULT), Charsets.UTF_8)
                } catch (_: Throwable) {
                    null
                }
            } ?: intent.getStringExtra("message") ?: run {
                logError(context, jobId, "Missing message", currentPhone, "")
                return
            }
            currentMessage = message

            if (context.checkSelfPermission(android.Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
                logError(context, jobId, "Ứng dụng chưa được cấp quyền SEND_SMS trên điện thoại", currentPhone, currentMessage)
                return
            }

            val subscriptionId = intent.getIntExtra("subscription_id", -1)
            val manager = resolveSmsManager(context, subscriptionId)
            val parts = manager.divideMessage(message)
            val sent = ArrayList<PendingIntent>()
            val delivered = ArrayList<PendingIntent>()

            parts.indices.forEach { index ->
                sent += pendingIntent(context, jobId, index, parts.size, "SENT", phone, message, subscriptionId)
                delivered += pendingIntent(context, jobId, index, parts.size, "DELIVERED", phone, message, subscriptionId)
            }

            manager.sendMultipartTextMessage(phone, null, parts, sent, delivered)
            val inboxResult = tryInsertSentMessage(context, phone, message)
            EventLog.append(
                context,
                JSONObject()
                    .put("job_id", jobId)
                    .put("phone", phone)
                    .put("message", message)
                    .put("stage", "QUEUED")
                    .put("subscription_id", subscriptionId)
                    .put("part_count", parts.size)
                    .put("sms_store", inboxResult)
                    .put("timestamp", System.currentTimeMillis())
            )
        } catch (error: Throwable) {
            val jId = if (currentJobId.isNotEmpty()) currentJobId else (intent.getStringExtra("job_id") ?: "")
            if (jId.isNotEmpty()) {
                logError(context, jId, error.message ?: error.javaClass.simpleName, currentPhone, currentMessage)
            }
        }
    }


    private fun tryInsertSentMessage(context: Context, phone: String, message: String): String {
        return try {
            val values = ContentValues().apply {
                put(Telephony.Sms.ADDRESS, phone)
                put(Telephony.Sms.BODY, message)
                put(Telephony.Sms.DATE, System.currentTimeMillis())
                put(Telephony.Sms.TYPE, Telephony.Sms.MESSAGE_TYPE_OUTBOX)
                put(Telephony.Sms.READ, 1)
                put(Telephony.Sms.SEEN, 1)
                put(Telephony.Sms.STATUS, Telephony.Sms.STATUS_PENDING)
                put(Telephony.Sms.SUBSCRIPTION_ID, -1)
            }
            val uri = context.contentResolver.insert(Telephony.Sms.Sent.CONTENT_URI, values)
            if (uri != null) {
                "INSERTED"
            } else {
                "NOT_INSERTED"
            }
        } catch (error: SecurityException) {
            "DENIED:${error.javaClass.simpleName}"
        } catch (error: Exception) {
            "ERROR:${error.javaClass.simpleName}"
        }
    }

    private fun resolveSmsManager(context: Context, subscriptionId: Int): SmsManager {
        return try {
            if (subscriptionId >= 0) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    val sm = context.getSystemService(SmsManager::class.java)
                    sm?.createForSubscriptionId(subscriptionId) ?: SmsManager.getSmsManagerForSubscriptionId(subscriptionId)
                } else {
                    @Suppress("DEPRECATION")
                    SmsManager.getSmsManagerForSubscriptionId(subscriptionId)
                }
            } else {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    context.getSystemService(SmsManager::class.java) ?: @Suppress("DEPRECATION") SmsManager.getDefault()
                } else {
                    @Suppress("DEPRECATION")
                    SmsManager.getDefault()
                }
            }
        } catch (_: Throwable) {
            @Suppress("DEPRECATION")
            SmsManager.getDefault()
        }
    }

    private fun pendingIntent(context: Context, jobId: String, index: Int, count: Int, stage: String, phone: String = "", message: String = "", subscriptionId: Int = -1): PendingIntent {
        val action = if (stage == "DELIVERED") "vn.smsbridge.sender.SMS_DELIVERED" else "vn.smsbridge.sender.SMS_SENT"
        val intent = Intent(context, SmsResultReceiver::class.java).apply {
            this.action = action
            putExtra("job_id", jobId)
            putExtra("part_index", index)
            putExtra("part_count", count)
            putExtra("stage", stage)
            putExtra("phone", phone)
            putExtra("message", message)
            putExtra("subscription_id", subscriptionId)
        }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0)
        return PendingIntent.getBroadcast(context, "$jobId:$stage:$index".hashCode(), intent, flags)
    }

    private fun logError(context: Context, jobId: String, error: String, phone: String = "", message: String = "") {
        EventLog.append(
            context,
            JSONObject()
                .put("job_id", jobId)
                .put("phone", phone)
                .put("message", message)
                .put("stage", "FAILED")
                .put("is_success", false)
                .put("error", error)
                .put("timestamp", System.currentTimeMillis())
        )
        CloudSyncService.reportResult(context, jobId, "FAILED", error, phone, message)
    }
}
