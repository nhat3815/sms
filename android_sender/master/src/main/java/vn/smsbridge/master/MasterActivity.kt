package vn.smsbridge.master

import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast

class MasterActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val store = MasterStore(this)
        val device = EditText(this).apply { hint = "Agent ID, ví dụ android-01"; setText("master") }
        val phone = EditText(this).apply { hint = "Số điện thoại" }
        val message = EditText(this).apply { hint = "Nội dung SMS"; minLines = 4 }
        val info = TextView(this).apply { text = "Server: http://${wifiIp()}:8765\nToken: ${store.clusterToken()}\nCùng máy: http://127.0.0.1:8765" }
        val send = Button(this).apply { text = "Xếp hàng gửi" }
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
            addView(info); addView(device); addView(phone); addView(message); addView(send)
        })
        startMaster()
        send.setOnClickListener {
            val agentId = device.text.toString().trim()
            val number = phone.text.toString().filter { it.isDigit() || it == '+' }
            val text = message.text.toString().trim()
            if (agentId.isEmpty() || number.length !in 8..15 || text.isEmpty()) return@setOnClickListener Toast.makeText(this, "Thiếu Agent ID, số hoặc nội dung", Toast.LENGTH_LONG).show()
            store.enqueue(agentId, number, text)
            Toast.makeText(this, "Đã xếp hàng cho $agentId", Toast.LENGTH_SHORT).show()
        }
    }

    private fun startMaster() {
        val intent = Intent(this, MasterServerService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent) else startService(intent)
    }

    private fun wifiIp(): String = (applicationContext.getSystemService(WIFI_SERVICE) as? android.net.wifi.WifiManager)?.connectionInfo?.ipAddress?.let { ip -> "%d.%d.%d.%d".format(ip and 0xff, ip shr 8 and 0xff, ip shr 16 and 0xff, ip shr 24 and 0xff) } ?: "<Wi-Fi IP>"
}
