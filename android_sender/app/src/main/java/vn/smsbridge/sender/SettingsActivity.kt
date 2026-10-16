package vn.smsbridge.sender

import android.Manifest
import android.app.Activity
import android.app.role.RoleManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Telephony
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.Collections
import java.util.Locale

class SettingsActivity : Activity() {

    private lateinit var txtIpAddress: TextView
    private lateinit var btnCopyIp: Button
    private lateinit var statusView: TextView
    private lateinit var statusDot: TextView
    private lateinit var txtSimInfo: TextView
    private lateinit var btnGrant: Button
    private lateinit var btnDefaultSms: Button
    private lateinit var btnRefresh: Button
    private lateinit var txtCloudStatus: TextView
    private lateinit var inputLanServer: EditText
    private lateinit var inputWanServer: EditText
    private lateinit var inputDeviceId: EditText
    private lateinit var inputDeviceToken: EditText
    private lateinit var btnDiscover: Button
    private lateinit var btnTestConn: Button
    private lateinit var lblTestStatus: TextView
    private lateinit var btnSaveCloud: Button
    private lateinit var btnStopCloud: Button

    private val permissions = arrayOf(
        Manifest.permission.SEND_SMS,
        Manifest.permission.READ_SMS,
        Manifest.permission.RECEIVE_SMS,
        Manifest.permission.READ_PHONE_STATE
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        findViewById<Button>(R.id.btn_back).setOnClickListener { finish() }

        txtIpAddress = findViewById(R.id.txt_ip_address)
        btnCopyIp = findViewById(R.id.btn_copy_ip)
        statusView = findViewById(R.id.status)
        statusDot = findViewById(R.id.status_dot)
        txtSimInfo = findViewById(R.id.txt_sim_info)
        btnGrant = findViewById(R.id.btn_grant)
        btnDefaultSms = findViewById(R.id.btn_default_sms)
        btnRefresh = findViewById(R.id.btn_refresh)
        txtCloudStatus = findViewById(R.id.txt_cloud_status)
        inputLanServer = findViewById(R.id.input_lan_server)
        inputWanServer = findViewById(R.id.input_wan_server)
        inputDeviceId = findViewById(R.id.input_device_id)
        inputDeviceToken = findViewById(R.id.input_device_token)
        btnDiscover = findViewById(R.id.btn_discover)
        btnTestConn = findViewById(R.id.btn_test_conn)
        lblTestStatus = findViewById(R.id.lbl_test_status)
        btnSaveCloud = findViewById(R.id.btn_save_cloud)
        btnStopCloud = findViewById(R.id.btn_stop_cloud)

        loadInitialData()
        setupActions()
        updateStatus()
    }

    override fun onResume() {
        super.onResume()
        updateStatus()
    }

    private fun loadInitialData() {
        val prefs = getSharedPreferences(CloudSyncService.PREFS, MODE_PRIVATE)
        val defaultDevId = "phone-${Build.MODEL.replace(" ", "-").lowercase(Locale.ROOT)}"
        val defaultToken = "123"

        val curLan = prefs.getString(CloudSyncService.LAN_SERVER_URL, "")
        inputLanServer.setText(if (curLan.isNullOrBlank() || curLan.contains("192.168.137.1")) "" else curLan)
        inputWanServer.setText(prefs.getString(CloudSyncService.WAN_SERVER_URL, prefs.getString(CloudSyncService.SERVER_URL, "")))

        val curDevId = prefs.getString(CloudSyncService.DEVICE_ID, "")
        inputDeviceId.setText(if (curDevId.isNullOrBlank()) defaultDevId else curDevId)

        val curToken = prefs.getString(CloudSyncService.DEVICE_TOKEN, "")
        inputDeviceToken.setText(if (curToken.isNullOrBlank()) defaultToken else curToken)

        // Tự động tìm kiếm Master LAN nếu ô đang trống
        if (inputLanServer.text.isNullOrBlank()) {
            triggerAutoDiscover()
        }
    }

    private fun setupActions() {
        btnCopyIp.setOnClickListener {
            val ip = getWifiIpAddress()
            if (ip != null) {
                val fullIp = "$ip:5555"
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("Wi-Fi IP", fullIp))
                Toast.makeText(this, "📋 Đã sao chép IP: $fullIp", Toast.LENGTH_SHORT).show()
            } else {
                Toast.makeText(this, "⚠️ Thiết bị chưa kết nối Wi-Fi!", Toast.LENGTH_SHORT).show()
            }
        }

        btnGrant.setOnClickListener {
            val missing = permissions.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
            if (missing.isNotEmpty()) {
                requestPermissions(missing.toTypedArray(), 100)
                try {
                    val intent = Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                        data = Uri.fromParts("package", packageName, null)
                        flags = Intent.FLAG_ACTIVITY_NEW_TASK
                    }
                    startActivity(intent)
                    Toast.makeText(this, "👉 Hãy gạt Bật Cho phép quyền Tin nhắn SMS và Điện thoại", Toast.LENGTH_LONG).show()
                } catch (_: Exception) {}
            } else {
                Toast.makeText(this, "✅ Đã cấp đầy đủ tất cả quyền SMS!", Toast.LENGTH_SHORT).show()
            }
        }

        btnDefaultSms.setOnClickListener {
            try {
                val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    val roleManager = getSystemService(RoleManager::class.java)
                    roleManager.createRequestRoleIntent(RoleManager.ROLE_SMS)
                } else {
                    Intent(Telephony.Sms.Intents.ACTION_CHANGE_DEFAULT)
                        .putExtra(Telephony.Sms.Intents.EXTRA_PACKAGE_NAME, packageName)
                }
                startActivityForResult(intent, 200)
            } catch (error: Exception) {
                Toast.makeText(this, "Không mở được cài đặt SMS mặc định: ${error.message}", Toast.LENGTH_SHORT).show()
            }
        }

        btnRefresh.setOnClickListener {
            updateStatus()
            Toast.makeText(this, "Đã làm mới thông tin", Toast.LENGTH_SHORT).show()
        }

        btnDiscover.setOnClickListener {
            btnDiscover.isEnabled = false
            btnDiscover.text = "⏳ Đang quét..."
            Thread {
                var foundUrl: String? = null
                try {
                    val socket = java.net.DatagramSocket()
                    socket.broadcast = true
                    socket.soTimeout = 2000
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
                    val u = json.optString("lan_url", "").ifEmpty { json.optString("web_url", "") }
                    if (u.isNotEmpty()) foundUrl = normalizeUrl(u)
                } catch (_: Exception) {}

                runOnUiThread {
                    btnDiscover.isEnabled = true
                    btnDiscover.text = "🔍 Tự tìm máy tính"
                    if (foundUrl != null) {
                        inputLanServer.setText(foundUrl)
                        Toast.makeText(this, "🎯 Đã tìm thấy máy tính: $foundUrl", Toast.LENGTH_LONG).show()
                    } else {
                        Toast.makeText(this, "⚠️ Không thấy phản hồi UDP. Vui lòng nhập IP máy tính hiển thị trên Web", Toast.LENGTH_LONG).show()
                    }
                }
            }.start()
        }

        btnTestConn.setOnClickListener {
            val raw = inputLanServer.text.toString().trim()
            if (raw.isEmpty()) {
                Toast.makeText(this, "⚠️ Hãy nhập địa chỉ máy tính trước!", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            val url = normalizeUrl(raw)
            btnTestConn.isEnabled = false
            btnTestConn.text = "⏳ Đang thử..."
            lblTestStatus.visibility = View.VISIBLE
            lblTestStatus.text = "⏳ Đang gửi tín hiệu kiểm tra: $url..."
            lblTestStatus.setTextColor(Color.parseColor("#38BDF8"))

            Thread {
                var success = false
                var successUrl = url
                var errorMsg = ""

                val candidates = mutableListOf(url)
                val base = url.replace(Regex(":\\d+"), "")
                for (p in listOf(8765, 5000, 5001, 8899)) {
                    candidates.add("$base:$p")
                }

                for (target in candidates.distinct()) {
                    try {
                        val conn = URL("$target/health").openConnection() as HttpURLConnection
                        conn.connectTimeout = 3000
                        conn.readTimeout = 3000
                        val code = conn.responseCode
                        if (code in 200..299) {
                            success = true
                            successUrl = target
                            break
                        }
                    } catch (e: Exception) {
                        errorMsg = e.message ?: e.javaClass.simpleName
                    }
                }

                runOnUiThread {
                    btnTestConn.isEnabled = true
                    btnTestConn.text = "🧪 Kiểm tra"
                    if (success) {
                        inputLanServer.setText(successUrl)
                        lblTestStatus.text = "✅ KẾT NỐI THÀNH CÔNG tại $successUrl.\nBấm 'LƯU VÀ KẾT NỐI' để kích hoạt."
                        lblTestStatus.setTextColor(Color.parseColor("#059669"))
                        Toast.makeText(this, "🎉 Kết nối máy tính thành công!", Toast.LENGTH_LONG).show()
                    } else {
                        lblTestStatus.text = "❌ KHÔNG KẾT NỐI ĐƯỢC!\nLỗi: $errorMsg\n\nHãy kiểm tra xem 2 máy đã chung mạng chưa."
                        lblTestStatus.setTextColor(Color.parseColor("#EF4444"))
                        Toast.makeText(this, "❌ Không kết nối được tới máy tính!", Toast.LENGTH_LONG).show()
                    }
                }
            }.start()
        }

        btnSaveCloud.setOnClickListener {
            val lanUrl = normalizeUrl(inputLanServer.text.toString())
            val wanUrl = normalizeUrl(inputWanServer.text.toString())
            val id = inputDeviceId.text.toString().trim()
            val token = inputDeviceToken.text.toString().trim()

            if ((lanUrl.isNotEmpty() && !isAllowedServer(lanUrl)) ||
                (wanUrl.isNotEmpty() && !isAllowedServer(wanUrl)) ||
                (lanUrl.isEmpty() && wanUrl.isEmpty()) || id.isEmpty() || token.isEmpty()) {
                Toast.makeText(this, "⚠️ Cần ít nhất Master LAN hoặc Cloud WAN, Device ID và token!", Toast.LENGTH_LONG).show()
                return@setOnClickListener
            }

            val prefs = getSharedPreferences(CloudSyncService.PREFS, MODE_PRIVATE)
            prefs.edit()
                .putString(CloudSyncService.LAN_SERVER_URL, lanUrl)
                .putString(CloudSyncService.WAN_SERVER_URL, wanUrl)
                .putString(CloudSyncService.SERVER_URL, if (wanUrl.isNotEmpty()) wanUrl else lanUrl)
                .putString(CloudSyncService.DEVICE_ID, id)
                .putString(CloudSyncService.DEVICE_TOKEN, token)
                .apply()

            val serviceIntent = Intent(this, CloudSyncService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(serviceIntent)
            } else {
                startService(serviceIntent)
            }
            updateStatus()
            Toast.makeText(this, "✅ Đã lưu và kích hoạt kết nối với máy tính!", Toast.LENGTH_SHORT).show()
        }

        btnStopCloud.setOnClickListener {
            stopService(Intent(this, CloudSyncService::class.java))
            val prefs = getSharedPreferences(CloudSyncService.PREFS, MODE_PRIVATE)
            prefs.edit()
                .putString(CloudSyncService.LAN_SERVER_URL, "")
                .putString(CloudSyncService.WAN_SERVER_URL, "")
                .putString(CloudSyncService.SERVER_URL, "")
                .apply()
            updateStatus()
            Toast.makeText(this, "🛑 Đã dừng kết nối", Toast.LENGTH_SHORT).show()
        }
    }

    private fun triggerAutoDiscover() {
        Thread {
            try {
                val socket = java.net.DatagramSocket()
                socket.broadcast = true
                socket.soTimeout = 1500
                val sendData = "DISCOVER_SMS_MASTER".toByteArray()
                val packet = java.net.DatagramPacket(
                    sendData,
                    sendData.size,
                    java.net.InetAddress.getByName("255.255.255.255"),
                    8766
                )
                socket.send(packet)
                val buf = ByteArray(1024)
                val recv = java.net.DatagramPacket(buf, buf.size)
                socket.receive(recv)
                val resp = String(recv.data, 0, recv.length)
                val json = JSONObject(resp)
                socket.close()
                val u = json.optString("lan_url", "").ifEmpty { json.optString("web_url", "") }
                if (u.isNotEmpty()) {
                    runOnUiThread {
                        if (inputLanServer.text.isNullOrBlank()) {
                            inputLanServer.setText(normalizeUrl(u))
                        }
                    }
                }
            } catch (_: Exception) {}
        }.start()
    }

    private fun updateStatus() {
        val granted = permissions.all { checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED }
        val defaultSms = Telephony.Sms.getDefaultSmsPackage(this) == packageName
        val wifiIp = getWifiIpAddress()
        val prefs = getSharedPreferences(CloudSyncService.PREFS, MODE_PRIVATE)
        val lanUrl = prefs.getString(CloudSyncService.LAN_SERVER_URL, "")?.trim().orEmpty()
        val wanUrl = prefs.getString(CloudSyncService.WAN_SERVER_URL, "")?.trim().orEmpty()
        val devId = prefs.getString(CloudSyncService.DEVICE_ID, "")?.trim().orEmpty()

        if (wifiIp != null) {
            txtIpAddress.text = "$wifiIp:5555"
            txtIpAddress.setTextColor(Color.parseColor("#00E676"))
        } else {
            txtIpAddress.text = "Chưa kết nối Wi-Fi"
            txtIpAddress.setTextColor(Color.parseColor("#94A3B8"))
        }

        val cloudTarget = if (lanUrl.isNotEmpty()) lanUrl else if (wanUrl.isNotEmpty()) wanUrl else ""
        if (cloudTarget.isNotEmpty()) {
            txtCloudStatus.text = "🟢 Đang kết nối: $cloudTarget (ID: ${if (devId.isNotEmpty()) devId else "phone"})"
            txtCloudStatus.setTextColor(Color.parseColor("#38BDF8"))
        } else {
            txtCloudStatus.text = "⚪ Trạng thái: Chưa cấu hình kết nối"
            txtCloudStatus.setTextColor(Color.parseColor("#94A3B8"))
        }

        val dotShape = GradientDrawable().apply { shape = GradientDrawable.OVAL }
        if (granted && defaultSms) {
            dotShape.setColor(Color.parseColor("#00E676"))
            statusView.text = "SMS Service: Sẵn sàng (Mặc định)"
        } else if (granted) {
            dotShape.setColor(Color.parseColor("#00E676"))
            statusView.text = "SMS Service: Sẵn sàng (SIM)"
        } else {
            dotShape.setColor(Color.parseColor("#EF4444"))
            statusView.text = "SMS Service: Chưa cấp quyền SMS"
        }
        statusDot.background = dotShape

        if (granted) {
            SmsCommandReceiver.writeSimStatus(this)
            try {
                val sm = getSystemService(android.telephony.SubscriptionManager::class.java)
                val activeSubs = sm?.activeSubscriptionInfoList.orEmpty()
                if (activeSubs.isNotEmpty()) {
                    val simListStr = activeSubs.joinToString("  |  ") { sub ->
                        val slot = sub.simSlotIndex + 1
                        val carrier = sub.carrierName?.toString()?.ifEmpty { "SIM $slot" } ?: "SIM $slot"
                        "SIM $slot: $carrier"
                    }
                    txtSimInfo.text = "📶 Đã phát hiện ${activeSubs.size} SIM: $simListStr"
                    txtSimInfo.setTextColor(Color.parseColor("#38BDF8"))
                } else {
                    txtSimInfo.text = "⚠️ Không tìm thấy SIM nào đang hoạt động"
                    txtSimInfo.setTextColor(Color.parseColor("#F59E0B"))
                }
            } catch (e: Exception) {
                txtSimInfo.text = "SIM: Không đọc được thông tin (${e.message})"
                txtSimInfo.setTextColor(Color.parseColor("#EF4444"))
            }
        } else {
            txtSimInfo.text = "⚠️ Cần cấp quyền Điện thoại để nhận diện SIM"
            txtSimInfo.setTextColor(Color.parseColor("#EF4444"))
        }
    }

    private fun getWifiIpAddress(): String? {
        try {
            val wifiMgr = applicationContext.getSystemService(Context.WIFI_SERVICE) as? android.net.wifi.WifiManager
            val ipInt = wifiMgr?.connectionInfo?.ipAddress ?: 0
            if (ipInt != 0) {
                val ipStr = String.format(
                    Locale.US,
                    "%d.%d.%d.%d",
                    ipInt and 0xff,
                    ipInt shr 8 and 0xff,
                    ipInt shr 16 and 0xff,
                    ipInt shr 24 and 0xff
                )
                if (ipStr != "0.0.0.0" && !ipStr.startsWith("127.")) {
                    return ipStr
                }
            }
        } catch (_: Exception) {}

        try {
            val interfaces = Collections.list(java.net.NetworkInterface.getNetworkInterfaces())
            for (intf in interfaces) {
                val addrs = Collections.list(intf.inetAddresses)
                for (addr in addrs) {
                    if (!addr.isLoopbackAddress && addr is java.net.Inet4Address) {
                        val host = addr.hostAddress ?: ""
                        if (!host.startsWith("127.") && !host.startsWith("10.0.2.") && host.isNotEmpty()) {
                            return host
                        }
                    }
                }
            }
        } catch (_: Exception) {}
        return null
    }

    private fun normalizeUrl(raw: String): String {
        var s = raw.trim().trimEnd('/')
        if (s.isEmpty()) return ""
        if (!s.startsWith("http://") && !s.startsWith("https://")) {
            s = "http://$s"
        }
        return s
    }

    private fun isAllowedServer(url: String): Boolean {
        val s = normalizeUrl(url)
        val uri = runCatching { Uri.parse(s) }.getOrNull() ?: return false
        return uri.scheme == "http" || uri.scheme == "https"
    }
}
