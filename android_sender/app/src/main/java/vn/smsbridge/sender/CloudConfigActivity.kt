package vn.smsbridge.sender

import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.graphics.Color
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Space
import android.widget.TextView
import android.widget.Toast
import android.view.View
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

class CloudConfigActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences(CloudSyncService.PREFS, MODE_PRIVATE)
        val defaultDevId = "phone-${Build.MODEL.replace(" ", "-").lowercase(Locale.ROOT)}"
        val defaultToken = "123"

        val lblTitle = TextView(this).apply {
            text = "⚡ CẤU HÌNH KẾT NỐI KHÔNG DÂY (CLOUD / LAN)"
            textSize = 16f
            setTextColor(Color.parseColor("#0284C7"))
            setTypeface(null, android.graphics.Typeface.BOLD)
            setPadding(0, 0, 0, 16)
        }
        val lblDesc = TextView(this).apply {
            text = "Kết nối trực tiếp điện thoại với máy tính qua Wi-Fi / Hotspot.\nKhông cần cáp USB, không cần gỡ lỗi không dây."
            textSize = 12f
            setTextColor(Color.parseColor("#64748B"))
            setPadding(0, 0, 0, 24)
        }

        val lblLan = TextView(this).apply {
            text = "1. Địa chỉ Máy tính (Master LAN):"
            textSize = 13f
            setTypeface(null, android.graphics.Typeface.BOLD)
            setTextColor(Color.parseColor("#334155"))
        }
        val lanServer = EditText(this).apply {
            hint = "http://192.168.x.x:8765 (Xem trên màn hình Web)"
            val cur = prefs.getString(CloudSyncService.LAN_SERVER_URL, "")
            setText(if (cur.isNullOrBlank() || cur.contains("192.168.137.1")) "" else cur)
        }

        val btnDiscover = Button(this).apply {
            text = "🔍 TỰ ĐỘNG TÌM MÁY TÍNH TRÊN WI-FI"
            setBackgroundColor(Color.parseColor("#059669"))
            setTextColor(Color.WHITE)
            setTypeface(null, android.graphics.Typeface.BOLD)
            setPadding(0, 16, 0, 16)
        }

        val btnTest = Button(this).apply {
            text = "🧪 KIỂM TRA KẾT NỐI TỚI MÁY TÍNH"
            setBackgroundColor(Color.parseColor("#475569"))
            setTextColor(Color.WHITE)
            setTypeface(null, android.graphics.Typeface.BOLD)
            setPadding(0, 16, 0, 16)
        }

        val lblTestStatus = TextView(this).apply {
            textSize = 12f
            setPadding(0, 8, 0, 8)
            visibility = View.GONE
        }

        val lblWan = TextView(this).apply {
            text = "2. Cloud Server WAN (Nếu có):"
            textSize = 13f
            setTypeface(null, android.graphics.Typeface.BOLD)
            setTextColor(Color.parseColor("#334155"))
            setPadding(0, 16, 0, 0)
        }
        val wanServer = EditText(this).apply {
            hint = "https://sms.example.com (tùy chọn)"
            setText(prefs.getString(CloudSyncService.WAN_SERVER_URL, prefs.getString(CloudSyncService.SERVER_URL, "")))
        }

        val lblDevId = TextView(this).apply {
            text = "3. Tên thiết bị (Device ID):"
            textSize = 13f
            setTypeface(null, android.graphics.Typeface.BOLD)
            setTextColor(Color.parseColor("#334155"))
            setPadding(0, 16, 0, 0)
        }
        val deviceId = EditText(this).apply {
            hint = defaultDevId
            val cur = prefs.getString(CloudSyncService.DEVICE_ID, "")
            setText(if (cur.isNullOrBlank()) defaultDevId else cur)
        }

        val lblToken = TextView(this).apply {
            text = "4. Device Token (Bất kỳ, trùng với máy tính):"
            textSize = 13f
            setTypeface(null, android.graphics.Typeface.BOLD)
            setTextColor(Color.parseColor("#334155"))
            setPadding(0, 16, 0, 0)
        }
        val deviceToken = EditText(this).apply {
            hint = "123"
            val cur = prefs.getString(CloudSyncService.DEVICE_TOKEN, "")
            setText(if (cur.isNullOrBlank()) defaultToken else cur)
        }

        val save = Button(this).apply {
            text = "💾 LƯU VÀ KẾT NỐI NGAY"
            setBackgroundColor(Color.parseColor("#0284C7"))
            setTextColor(Color.WHITE)
            setTypeface(null, android.graphics.Typeface.BOLD)
            setPadding(0, 20, 0, 20)
        }
        val stop = Button(this).apply {
            text = "🛑 Dừng kết nối"
            setBackgroundColor(Color.parseColor("#EF4444"))
            setTextColor(Color.WHITE)
            setPadding(0, 16, 0, 16)
        }
        val close = Button(this).apply {
            text = "◀️ Quay lại"
            setBackgroundColor(Color.parseColor("#64748B"))
            setTextColor(Color.WHITE)
            setPadding(0, 16, 0, 16)
        }

        val scroll = ScrollView(this).apply {
            addView(LinearLayout(this@CloudConfigActivity).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(32, 32, 32, 48)
                addView(lblTitle)
                addView(lblDesc)
                addView(lblLan)
                addView(lanServer)
                addView(btnDiscover)
                addView(Space(this@CloudConfigActivity).apply { minimumHeight = 8 })
                addView(btnTest)
                addView(lblTestStatus)
                addView(lblWan)
                addView(wanServer)
                addView(lblDevId)
                addView(deviceId)
                addView(lblToken)
                addView(deviceToken)
                addView(Space(this@CloudConfigActivity).apply { minimumHeight = 24 })
                addView(save)
                addView(Space(this@CloudConfigActivity).apply { minimumHeight = 12 })
                addView(stop)
                addView(Space(this@CloudConfigActivity).apply { minimumHeight = 12 })
                addView(close)
            })
        }
        setContentView(scroll)

        if (lanServer.text.isNullOrBlank()) {
            Thread {
                try {
                    val socket = java.net.DatagramSocket()
                    socket.broadcast = true
                    socket.soTimeout = 1500
                    val sendData = "DISCOVER_SMS_MASTER".toByteArray()
                    val packet = java.net.DatagramPacket(sendData, sendData.size, java.net.InetAddress.getByName("255.255.255.255"), 8766)
                    socket.send(packet)
                    val buf = ByteArray(1024)
                    val recv = java.net.DatagramPacket(buf, buf.size)
                    socket.receive(recv)
                    val resp = String(recv.data, 0, recv.length)
                    val json = org.json.JSONObject(resp)
                    socket.close()
                    val u = json.optString("lan_url", "").ifEmpty { json.optString("web_url", "") }
                    if (u.isNotEmpty()) {
                        runOnUiThread {
                            if (lanServer.text.isNullOrBlank()) {
                                lanServer.setText(normalizeUrl(u))
                            }
                        }
                    }
                } catch (_: Exception) {}
            }.start()
        }

        btnTest.setOnClickListener {
            val raw = lanServer.text.toString().trim()
            if (raw.isEmpty()) {
                Toast.makeText(this, "⚠️ Hãy nhập địa chỉ máy tính trước!", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            val url = normalizeUrl(raw)
            btnTest.isEnabled = false
            btnTest.text = "⏳ Đang kiểm tra kết nối..."
            lblTestStatus.visibility = View.VISIBLE
            lblTestStatus.text = "⏳ Đang gửi tín hiệu kiểm tra tới máy tính: $url..."
            lblTestStatus.setTextColor(Color.parseColor("#0284C7"))

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
                    btnTest.isEnabled = true
                    btnTest.text = "🧪 KIỂM TRA KẾT NỐI TỚI MÁY TÍNH"
                    if (success) {
                        lanServer.setText(successUrl)
                        lblTestStatus.text = "✅ KẾT NỐI THÀNH CÔNG!\nMáy tính đã phản hồi tại $successUrl.\nBấm 'LƯU VÀ KẾT NỐI NGAY' bên dưới để kích hoạt."
                        lblTestStatus.setTextColor(Color.parseColor("#059669"))
                        Toast.makeText(this@CloudConfigActivity, "🎉 Kết nối máy tính thành công!", Toast.LENGTH_LONG).show()
                    } else {
                        lblTestStatus.text = "❌ KHÔNG KẾT NỐI ĐƯỢC!\nLỗi: $errorMsg\n\nHướng dẫn:\n1. Đảm bảo điện thoại và máy tính kết nối CHUNG mạng Wi-Fi.\n2. Xem IP máy tính hiển thị trên Web và nhập vào ô trên."
                        lblTestStatus.setTextColor(Color.parseColor("#DC2626"))
                        Toast.makeText(this@CloudConfigActivity, "❌ Không thể kết nối tới máy tính!", Toast.LENGTH_LONG).show()
                    }
                }
            }.start()
        }

        btnDiscover.setOnClickListener {
            btnDiscover.isEnabled = false
            btnDiscover.text = "⏳ Đang quét tìm máy tính..."
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
                    val json = org.json.JSONObject(resp)
                    socket.close()
                    val u = json.optString("lan_url", "").ifEmpty { json.optString("web_url", "") }
                    if (u.isNotEmpty()) foundUrl = normalizeUrl(u)
                } catch (_: Exception) {}

                runOnUiThread {
                    btnDiscover.isEnabled = true
                    btnDiscover.text = "🔍 TỰ ĐỘNG TÌM MÁY TÍNH TRÊN WI-FI"
                    if (foundUrl != null) {
                        lanServer.setText(foundUrl)
                        Toast.makeText(this@CloudConfigActivity, "🎯 Đã tìm thấy máy tính: $foundUrl", Toast.LENGTH_LONG).show()
                    } else {
                        Toast.makeText(this@CloudConfigActivity, "⚠️ Không thấy phản hồi UDP. Vui lòng nhập IP máy tính hiển thị trên Web (ví dụ: http://192.168.1.x:8765)", Toast.LENGTH_LONG).show()
                    }
                }
            }.start()
        }

        close.setOnClickListener { finish() }
        save.setOnClickListener {
            val lanUrl = normalizeUrl(lanServer.text.toString())
            val wanUrl = normalizeUrl(wanServer.text.toString())
            val id = deviceId.text.toString().trim()
            val token = deviceToken.text.toString().trim()
            if ((lanUrl.isNotEmpty() && !isAllowedServer(lanUrl)) ||
                (wanUrl.isNotEmpty() && !isAllowedServer(wanUrl)) ||
                (lanUrl.isEmpty() && wanUrl.isEmpty()) || id.isEmpty() || token.isEmpty()) {
                Toast.makeText(this, "⚠️ Cần ít nhất Master LAN hoặc Cloud WAN, Device ID và token!", Toast.LENGTH_LONG).show()
                return@setOnClickListener
            }
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
            Toast.makeText(this, "✅ Đã lưu và kích hoạt kết nối với máy tính!", Toast.LENGTH_SHORT).show()
            finish()
        }
        stop.setOnClickListener {
            stopService(Intent(this, CloudSyncService::class.java))
            Toast.makeText(this, "🛑 Đã dừng kết nối", Toast.LENGTH_SHORT).show()
        }
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
        val uri = runCatching { android.net.Uri.parse(s) }.getOrNull() ?: return false
        return uri.scheme == "http" || uri.scheme == "https"
    }
}
