package vn.smsbridge.master

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class MasterServerService : Service() {
    private val executor: ExecutorService = Executors.newCachedThreadPool()
    @Volatile private var running = false
    private var serverSocket: ServerSocket? = null
    private lateinit var store: MasterStore

    override fun onCreate() {
        super.onCreate()
        store = MasterStore(this)
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) manager.createNotificationChannel(NotificationChannel("master", "SMS Master", NotificationManager.IMPORTANCE_LOW))
        val notification = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) Notification.Builder(this, "master") else @Suppress("DEPRECATION") Notification.Builder(this)
        startForeground(8765, notification.setSmallIcon(android.R.drawable.stat_notify_sync).setContentTitle("SMS Bridge Master").setContentText("LAN server :8765 đang chạy").build())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!running) {
            running = true
            executor.execute(::serve)
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        serverSocket?.close()
        executor.shutdownNow()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun serve() {
        try {
            ServerSocket(8765).use { socket ->
                serverSocket = socket
                while (running) executor.execute { handle(socket.accept()) }
            }
        } catch (_: Exception) { stopSelf() }
    }

    private fun handle(socket: Socket) {
        socket.use {
            try {
                val input = BufferedInputStream(it.getInputStream())
                val header = readHeader(input) ?: return
                val lines = header.split("\r\n")
                val request = lines.firstOrNull()?.split(" ") ?: return
                val method = request.getOrNull(0) ?: return
                val path = request.getOrNull(1) ?: return
                val headers = lines.drop(1).mapNotNull { line -> line.split(":", limit = 2).takeIf { it.size == 2 }?.let { it[0].lowercase() to it[1].trim() } }.toMap()
                val contentLength = headers["content-length"]?.toIntOrNull() ?: 0
                val body = input.readNBytes(contentLength).toString(Charsets.UTF_8)
                val deviceId = headers["x-device-id"].orEmpty()
                if (deviceId.isBlank() || headers["x-device-token"] != store.clusterToken()) return respond(it, 401, JSONObject().put("error", "unauthorized"))
                store.heartbeat(deviceId)
                when {
                    method == "GET" && path == "/v1/device/jobs/next" -> {
                        val job = store.claim(deviceId)
                        if (job == null) respond(it, 204, null) else respond(it, 200, job)
                    }
                    method == "POST" && path.startsWith("/v1/device/jobs/") && path.endsWith("/result") -> {
                        val jobId = path.removePrefix("/v1/device/jobs/").removeSuffix("/result").trimEnd('/')
                        val payload = JSONObject(body)
                        if (store.result(deviceId, jobId, payload.optString("status", "FAILED"), payload.optString("detail", ""))) respond(it, 200, JSONObject().put("status", "ok")) else respond(it, 404, JSONObject().put("error", "job not found"))
                    }
                    else -> respond(it, 404, JSONObject().put("error", "not found"))
                }
            } catch (_: Exception) { }
        }
    }

    private fun readHeader(input: BufferedInputStream): String? {
        val bytes = ByteArrayOutputStream()
        var previous = 0
        var current = input.read()
        while (bytes.size() < 16384 && current != -1) {
            bytes.write(current)
            if (previous == '\r'.code && current == '\n'.code && bytes.toByteArray().takeLast(4).toByteArray().contentEquals("\r\n\r\n".toByteArray())) return bytes.toString(Charsets.UTF_8.name()).removeSuffix("\r\n\r\n")
            previous = current
            current = input.read()
        }
        return null
    }

    private fun respond(socket: Socket, code: Int, body: JSONObject?) {
        val payload = body?.toString()?.toByteArray(Charsets.UTF_8) ?: ByteArray(0)
        val reason = if (code == 200) "OK" else if (code == 204) "No Content" else if (code == 401) "Unauthorized" else "Not Found"
        socket.getOutputStream().use { out ->
            out.write("HTTP/1.1 $code $reason\r\nContent-Type: application/json\r\nContent-Length: ${payload.size}\r\nConnection: close\r\n\r\n".toByteArray())
            out.write(payload)
        }
    }
}
