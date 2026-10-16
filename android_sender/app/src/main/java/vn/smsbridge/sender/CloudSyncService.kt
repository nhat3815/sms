package vn.smsbridge.sender

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

class CloudSyncService : Service() {
    companion object {
        const val PREFS = "cloud_config"
        const val SERVER_URL = "server_url"
        const val LAN_SERVER_URL = "lan_server_url"
        const val WAN_SERVER_URL = "wan_server_url"
        const val DEVICE_ID = "device_id"
        const val DEVICE_TOKEN = "device_token"
        const val JOB_SERVER_PREFIX = "job_server_"
        private const val CHANNEL_ID = "sms_cloud_bridge"
        private const val NOTIFICATION_ID = 2026
        private val reportExecutor = Executors.newSingleThreadExecutor()
        private const val OUTBOX = "result_outbox"

        fun reportResult(
            context: android.content.Context,
            jobId: String,
            status: String,
            detail: String,
            phone: String = "",
            message: String = "",
            resultCode: Int = 0,
            subscriptionId: Int = -1
        ) {
            if (jobId.isBlank()) return
            val result = JSONObject().put("job_id", jobId).put("status", status)
                .put("detail", detail).put("phone", phone).put("message", message)
                .put("result_code", resultCode).put("subscription_id", subscriptionId)
            Outbox.enqueue(context, result)
            reportExecutor.execute { flush(context) }
        }

        private fun flush(context: android.content.Context) {
            val client = CloudClient(context)
            Outbox.read(context).forEach { item ->
                try {
                    if (client.postResult(item.getString("job_id"), item.optString("status"), item.optString("detail"), item.optString("phone"), item.optString("message"), item.optInt("result_code"), item.optInt("subscription_id", -1))) {
                        Outbox.remove(context, item.getString("job_id"), item.optLong("timestamp"))
                    }
                } catch (_: Exception) {}
            }
        }
    }

    private lateinit var wakeLock: PowerManager.WakeLock
    private lateinit var wifiLock: android.net.wifi.WifiManager.WifiLock

    private val executor = Executors.newSingleThreadExecutor()
    @Volatile private var running = false

    override fun onCreate() {
        super.onCreate()
        val power = getSystemService(PowerManager::class.java)
        wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "smsbridge:cloud-sync").apply {
            setReferenceCounted(false)
            acquire()
        }
        val wifi = getSystemService(android.net.wifi.WifiManager::class.java)
        @Suppress("DEPRECATION")
        wifiLock = wifi.createWifiLock(android.net.wifi.WifiManager.WIFI_MODE_FULL_HIGH_PERF, "smsbridge:cloud-wifi").apply {
            setReferenceCounted(false)
            acquire()
        }
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "SMS Cloud Bridge", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val notification = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            android.app.Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION") android.app.Notification.Builder(this)
        }.setContentTitle("SMS Cloud Bridge")
            .setContentText("Đang chờ lệnh gửi SMS")
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .build()
        startForeground(NOTIFICATION_ID, notification)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!running) {
            running = true
            executor.execute(::pollLoop)
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        executor.shutdownNow()
        if (::wakeLock.isInitialized && wakeLock.isHeld) wakeLock.release()
        @Suppress("DEPRECATION")
        if (::wifiLock.isInitialized && wifiLock.isHeld) wifiLock.release()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun pollLoop() {
        while (running) {
            flushPendingResults()
            var hadJob = false
            try {
                val client = CloudClient(this)
                val job = client.nextJob()
                if (job != null) {
                    hadJob = true
                    val payload = job.payload
                    val jobId = payload.getString("id")
                    client.rememberJobServer(jobId, job.server)
                    sendBroadcast(Intent(this, SmsCommandReceiver::class.java).apply {
                        action = "vn.smsbridge.sender.SEND_SMS"
                        putExtra("job_id", jobId)
                        putExtra("phone", payload.getString("phone"))
                        putExtra("message", payload.getString("message"))
                        putExtra("subscription_id", payload.optInt("subscription_id", -1))
                        putExtra("token", client.readBridgeToken())
                    })
                    client.postResult(jobId, "QUEUED", "Android accepted cloud job", payload.optString("phone", ""), payload.optString("message", ""))
                }
            } catch (error: Exception) {
                EventLog.append(this, JSONObject().put("stage", "CLOUD_ERROR").put("error", error.message ?: error.javaClass.simpleName))
            }
            val sleepMs = if (hadJob) 800L else 4000L
            try { Thread.sleep(sleepMs) } catch (_: InterruptedException) { return }
        }
    }

    private fun flushPendingResults() = reportExecutor.execute { flush(this) }

}

private object Outbox {
    private const val KEY = "result_outbox"
    private val lock = Any()

    fun enqueue(context: android.content.Context, value: JSONObject) = synchronized(lock) {
        val prefs = context.getSharedPreferences(CloudSyncService.PREFS, android.content.Context.MODE_PRIVATE)
        val values = read(context)
        value.put("timestamp", System.currentTimeMillis())
        values.removeAll { it.optString("job_id") == value.optString("job_id") && it.optString("status") == value.optString("status") }
        values.add(value)
        prefs.edit().putString(KEY, org.json.JSONArray(values).toString()).apply()
    }

    fun read(context: android.content.Context): MutableList<JSONObject> = synchronized(lock) {
        val raw = context.getSharedPreferences(CloudSyncService.PREFS, android.content.Context.MODE_PRIVATE).getString(KEY, "[]") ?: "[]"
        val array = org.json.JSONArray(raw)
        MutableList(array.length()) { array.getJSONObject(it) }
    }

    fun remove(context: android.content.Context, jobId: String, timestamp: Long) = synchronized(lock) {
        val values = read(context).filterNot { it.optString("job_id") == jobId && it.optLong("timestamp") == timestamp }
        context.getSharedPreferences(CloudSyncService.PREFS, android.content.Context.MODE_PRIVATE).edit()
            .putString(KEY, org.json.JSONArray(values).toString()).apply()
    }
}

private data class CloudJob(val payload: JSONObject, val server: String)

private class CloudClient(private val context: android.content.Context) {
    fun postResult(
        jobId: String,
        status: String,
        detail: String,
        phone: String = "",
        message: String = "",
        resultCode: Int = 0,
        subscriptionId: Int = -1
    ): Boolean {
        val body = JSONObject()
            .put("status", status)
            .put("detail", detail)
            .put("phone", phone)
            .put("message", message)
            .put("result_code", resultCode)
            .put("subscription_id", subscriptionId)
            .put("timestamp", System.currentTimeMillis())
            .toString()
        val server = prefs().getString("${CloudSyncService.JOB_SERVER_PREFIX}$jobId", "") ?: ""
        if (server.isNotBlank()) {
            try {
                request(server, "POST", "/v1/device/jobs/$jobId/result", body)
                return true
            } catch (_: Exception) {}
        }
        for (candidate in servers()) {
            try {
                request(candidate, "POST", "/v1/device/jobs/$jobId/result", body)
                return true
            } catch (_: Exception) {}
        }
        return false
    }

    fun nextJob(): CloudJob? {
        for (server in servers()) {
            try {
                val job = request(server, "GET", "/v1/device/jobs/next")
                if (job != null) return CloudJob(job, server)
            } catch (_: Exception) {
            }
        }
        return null
    }

    fun rememberJobServer(jobId: String, server: String) {
        prefs().edit().putString("${CloudSyncService.JOB_SERVER_PREFIX}$jobId", server).apply()
    }

    private fun request(server: String, method: String, path: String, body: String? = null): JSONObject? {
        val prefs = prefs()
        var deviceId = prefs.getString(CloudSyncService.DEVICE_ID, "") ?: ""
        var deviceToken = prefs.getString(CloudSyncService.DEVICE_TOKEN, "") ?: ""
        if (deviceId.isEmpty()) {
            deviceId = "phone-${android.os.Build.MODEL.replace(" ", "-").lowercase(java.util.Locale.ROOT)}"
            prefs.edit().putString(CloudSyncService.DEVICE_ID, deviceId).apply()
        }
        if (deviceToken.isEmpty()) {
            deviceToken = "123"
            prefs.edit().putString(CloudSyncService.DEVICE_TOKEN, deviceToken).apply()
        }
        if (!isAllowedServer(server)) return null
        val normalizedServer = normalizeUrl(server)
        val connection = URL(normalizedServer + path).openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.connectTimeout = 8000
        connection.readTimeout = 12000
        connection.setRequestProperty("X-Device-Id", deviceId)
        connection.setRequestProperty("X-Device-Token", deviceToken)
        val sims = readActiveSims()
        if (sims.isNotEmpty() && sims != "[]") {
            try {
                connection.setRequestProperty("X-Device-Sims", java.net.URLEncoder.encode(sims, "UTF-8"))
            } catch (_: Exception) {
                connection.setRequestProperty("X-Device-Sims", sims)
            }
        }
        connection.setRequestProperty("Content-Type", "application/json")
        if (body != null) {
            connection.doOutput = true
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        }
        val code = connection.responseCode
        if (code == 204) return null
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
        if (code !in 200..299) error("Cloud HTTP $code: $response")
        return if (response.isBlank()) null else JSONObject(response)
    }

    private fun servers(): List<String> {
        val prefs = prefs()
        val lan = prefs.getString(CloudSyncService.LAN_SERVER_URL, "") ?: ""
        val wan = prefs.getString(CloudSyncService.WAN_SERVER_URL, "") ?: ""
        val legacy = prefs.getString(CloudSyncService.SERVER_URL, "") ?: ""
        val rawList = mutableListOf<String>()
        if (lan.isNotBlank()) rawList.add(lan)
        if (wan.isNotBlank()) rawList.add(wan)
        if (legacy.isNotBlank()) rawList.add(legacy)

        val result = mutableListOf<String>()
        for (item in rawList) {
            val norm = normalizeUrl(item)
            if (isAllowedServer(norm)) {
                result.add(norm)
                val base = norm.replace(Regex(":\\d+"), "")
                for (p in listOf(8765, 5000, 5001, 8899)) {
                    result.add("$base:$p")
                }
            }
        }

        // Tự động dò tìm trên mạng nội bộ qua UDP broadcast nếu chưa có server hoạt động
        if (result.isEmpty()) {
            discoverMasterViaUdp()?.let { discovered ->
                result.add(discovered)
                prefs.edit().putString(CloudSyncService.LAN_SERVER_URL, discovered).apply()
            }
        }

        return result.distinct()
    }

    private fun prefs() = context.getSharedPreferences(CloudSyncService.PREFS, android.content.Context.MODE_PRIVATE)

    fun readBridgeToken(): String = context.filesDir.resolve("bridge_token")
        .takeIf { it.exists() }?.readText()?.trim()
        ?: SmsCommandReceiver.DEFAULT_BRIDGE_SECRET

    fun readActiveSims(): String {
        return try {
            val f = context.filesDir.resolve("sim_status.json")
            if (!f.exists()) {
                try { SmsCommandReceiver.writeSimStatus(context) } catch (_: Exception) {}
            }
            if (f.exists()) {
                val obj = JSONObject(f.readText())
                val arr = obj.optJSONArray("subscriptions")
                if (arr != null && arr.length() > 0) return arr.toString()
            }
            val sm = context.getSystemService(android.telephony.SubscriptionManager::class.java)
            val tm = context.getSystemService(android.telephony.TelephonyManager::class.java)
            val arr = org.json.JSONArray()
            if (context.checkSelfPermission(android.Manifest.permission.READ_PHONE_STATE) == android.content.pm.PackageManager.PERMISSION_GRANTED) {
                for (info in sm?.activeSubscriptionInfoList.orEmpty()) {
                    val subId = info.subscriptionId
                    val inService = try {
                        tm?.createForSubscriptionId(subId)?.serviceState?.state == android.telephony.ServiceState.STATE_IN_SERVICE
                    } catch (_: Exception) { true }
                    arr.put(JSONObject()
                        .put("subscription_id", subId)
                        .put("slot_index", info.simSlotIndex)
                        .put("carrier_name", info.carrierName?.toString() ?: ("SIM " + (info.simSlotIndex + 1)))
                        .put("display_name", info.displayName?.toString() ?: ("SIM " + (info.simSlotIndex + 1)))
                        .put("in_service", inService))
                }
            }
            arr.toString()
        } catch (_: Exception) {
            "[]"
        }
    }

    private fun normalizeUrl(server: String): String {
        var s = server.trim().trimEnd('/')
        if (s.isEmpty()) return ""
        if (!s.startsWith("http://") && !s.startsWith("https://")) {
            s = "http://$s"
        }
        return s
    }

    private fun isAllowedServer(server: String): Boolean {
        val s = normalizeUrl(server)
        val uri = runCatching { android.net.Uri.parse(s) }.getOrNull() ?: return false
        return uri.scheme == "http" || uri.scheme == "https"
    }

    private fun discoverMasterViaUdp(timeoutMs: Int = 1200): String? {
        return try {
            val socket = java.net.DatagramSocket()
            socket.broadcast = true
            socket.soTimeout = timeoutMs
            val sendData = "DISCOVER_SMS_MASTER".toByteArray()
            val packet = java.net.DatagramPacket(
                sendData,
                sendData.size,
                java.net.InetAddress.getByName("255.255.255.255"),
                8766
            )
            socket.send(packet)
            val buf = ByteArray(1024)
            val recvPacket = java.net.DatagramPacket(buf, buf.size)
            socket.receive(recvPacket)
            val resp = String(recvPacket.data, 0, recvPacket.length)
            val json = JSONObject(resp)
            socket.close()
            val lanUrl = json.optString("lan_url", "").ifEmpty { json.optString("web_url", "") }
            if (lanUrl.isNotEmpty()) normalizeUrl(lanUrl) else null
        } catch (_: Exception) {
            null
        }
    }
}
