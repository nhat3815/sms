package vn.smsbridge.sender

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.app.PendingIntent
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Telephony
import android.telephony.SmsManager
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.*
import org.json.JSONObject
import java.security.SecureRandom
import java.text.SimpleDateFormat
import java.util.*
import kotlin.collections.ArrayList
import kotlin.collections.LinkedHashMap

data class SmsItem(
    val id: Long,
    val address: String,
    val body: String,
    val date: Long,
    val type: Int,
    val statusText: String,
    val statusCode: Int, // 0 = Sent/Delivered OK, 1 = Error/Failed, 2 = Pending/Sending, 3 = Received (Inbox)
    val errorDetail: String = ""
)

class MainActivity : Activity() {

    private lateinit var statusView: TextView
    private lateinit var statusDot: TextView
    private lateinit var btnOpenSettings: Button
    private lateinit var inputPhone: EditText
    private lateinit var inputMessage: EditText
    private lateinit var inputSearch: EditText
    private lateinit var txtCharCount: TextView
    private lateinit var txtListHeader: TextView
    private lateinit var txtEmpty: TextView
    private lateinit var listMessages: ListView
    private lateinit var btnSendSms: Button

    private val allMessages = ArrayList<SmsItem>()
    private val displayedMessages = ArrayList<SmsItem>()
    private lateinit var adapter: SmsAdapter

    private val handler = Handler(Looper.getMainLooper())
    private val autoRefreshRunnable = object : Runnable {
        override fun run() {
            loadMessages(silent = true)
            handler.postDelayed(this, 3000)
        }
    }

    private val permissions = arrayOf(
        Manifest.permission.SEND_SMS,
        Manifest.permission.READ_SMS,
        Manifest.permission.RECEIVE_SMS,
        Manifest.permission.READ_PHONE_STATE
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        ensureToken()
        autoInitCloudService()
        initViews()
        setupListeners()
        updateStatus()

        val missingPermissions = permissions.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missingPermissions.isNotEmpty()) {
            requestPermissions(missingPermissions.toTypedArray(), 100)
        } else {
            SmsCommandReceiver.writeSimStatus(this)
        }

        loadMessages()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        SmsCommandReceiver.writeSimStatus(this)
        updateStatus()
        loadMessages()
    }

    override fun onResume() {
        super.onResume()
        SmsCommandReceiver.writeSimStatus(this)
        updateStatus()
        loadMessages()
        handler.removeCallbacks(autoRefreshRunnable)
        handler.postDelayed(autoRefreshRunnable, 3000)
    }

    override fun onPause() {
        super.onPause()
        handler.removeCallbacks(autoRefreshRunnable)
    }

    private fun initViews() {
        statusView = findViewById(R.id.status)
        statusDot = findViewById(R.id.status_dot)
        btnOpenSettings = findViewById(R.id.btn_open_settings)
        inputPhone = findViewById(R.id.input_phone)
        inputMessage = findViewById(R.id.input_message)
        inputSearch = findViewById(R.id.input_search)
        txtCharCount = findViewById(R.id.txt_char_count)
        txtListHeader = findViewById(R.id.txt_list_header)
        txtEmpty = findViewById(R.id.txt_empty)
        listMessages = findViewById(R.id.list_messages)
        btnSendSms = findViewById(R.id.btn_send_sms)

        adapter = SmsAdapter(this, displayedMessages)
        listMessages.adapter = adapter

        val shape = GradientDrawable().apply {
            this.shape = GradientDrawable.OVAL
            setColor(Color.parseColor("#00E676"))
        }
        statusDot.background = shape
    }

    private fun setupListeners() {
        btnOpenSettings.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }

        btnSendSms.setOnClickListener { sendDirectSms() }

        inputMessage.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                updateCharCounter(s?.toString() ?: "")
            }
            override fun afterTextChanged(s: Editable?) {}
        })

        inputSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                filterMessages(s?.toString() ?: "")
            }
            override fun afterTextChanged(s: Editable?) {}
        })

        listMessages.setOnItemClickListener { _, _, position, _ ->
            if (position in displayedMessages.indices) {
                showSmsDetailDialog(displayedMessages[position])
            }
        }
    }

    private fun updateCharCounter(text: String) {
        val len = text.length
        val isUnicode = text.any { it.code > 127 }
        val partSize = if (isUnicode) (if (len > 70) 67 else 70) else (if (len > 160) 153 else 160)
        val parts = if (len == 0) 1 else (len + partSize - 1) / partSize
        val type = if (isUnicode) "Unicode" else "GSM"
        txtCharCount.text = "$len ký tự | $parts SMS ($type)"
    }

    private fun ensureToken() {
        val file = filesDir.resolve("bridge_token")
        if (!file.exists()) {
            val bytes = ByteArray(32).also(SecureRandom()::nextBytes)
            file.writeText(bytes.joinToString("") { "%02x".format(it) })
        }
    }

    private fun autoInitCloudService() {
        try {
            val prefs = getSharedPreferences(CloudSyncService.PREFS, MODE_PRIVATE)
            val devId = prefs.getString(CloudSyncService.DEVICE_ID, "")
            if (devId.isNullOrBlank()) {
                val newDevId = "phone-${Build.MODEL.replace(" ", "-").lowercase(Locale.ROOT)}"
                prefs.edit().putString(CloudSyncService.DEVICE_ID, newDevId).putString(CloudSyncService.DEVICE_TOKEN, "123").apply()
            }
            val serviceIntent = Intent(this, CloudSyncService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(serviceIntent)
            } else {
                startService(serviceIntent)
            }
        } catch (_: Exception) {}
    }

    private fun updateStatus() {
        val granted = permissions.all { checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED }
        val defaultSms = Telephony.Sms.getDefaultSmsPackage(this) == packageName

        var simDesc = ""
        if (granted) {
            try {
                val sm = getSystemService(android.telephony.SubscriptionManager::class.java)
                val count = sm?.activeSubscriptionInfoCount ?: 0
                if (count > 0) {
                    simDesc = " - $count SIM"
                }
            } catch (_: Exception) {}
        }

        val dotShape = GradientDrawable().apply { shape = GradientDrawable.OVAL }
        if (granted && defaultSms) {
            dotShape.setColor(Color.parseColor("#00E676"))
            statusView.text = "SMS Bridge (Sẵn sàng$simDesc)"
        } else if (granted) {
            dotShape.setColor(Color.parseColor("#00E676"))
            statusView.text = "SMS Bridge (Sẵn sàng SIM$simDesc)"
        } else {
            dotShape.setColor(Color.parseColor("#EF4444"))
            statusView.text = "SMS Bridge (Chưa cấp quyền)"
        }
        statusDot.background = dotShape
    }

    private fun loadMessages(silent: Boolean = false) {
        val newMessages = ArrayList<SmsItem>()
        val hasReadPerm = checkSelfPermission(Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED

        // 1. Gom tất cả sự kiện từ events.jsonl theo job_id (tổng hợp đầy đủ mọi đoạn tin nhắn multipart)
        val jobEventsMap = LinkedHashMap<String, MutableList<JSONObject>>()
        val file = filesDir.resolve("events.jsonl")
        if (file.exists()) {
            try {
                file.readLines().forEach { line ->
                    try {
                        val ev = JSONObject(line)
                        val jId = ev.optString("job_id", "")
                        if (jId.isNotEmpty()) {
                            jobEventsMap.computeIfAbsent(jId) { ArrayList() }.add(ev)
                        }
                    } catch (_: Throwable) {}
                }
            } catch (_: Throwable) {}
        }

        // 2. Phân tích trạng thái THỰC TẾ của từng job
        val bridgePhonesAndTimes = ArrayList<Pair<String, Long>>()
        var jobIndex = 0

        for ((jobId, jobEvents) in jobEventsMap) {
            val phone = jobEvents.firstOrNull { it.optString("phone").isNotEmpty() }?.optString("phone") ?: "Không rõ"
            val message = jobEvents.firstOrNull { it.optString("message").isNotEmpty() }?.optString("message") ?: ""
            val expected = jobEvents.maxOfOrNull { it.optInt("part_count", 1) } ?: 1
            val timestamp = jobEvents.map { it.optLong("timestamp", 0L) }.maxOrNull() ?: System.currentTimeMillis()
            val subId = jobEvents.firstOrNull { it.has("subscription_id") }?.optInt("subscription_id", -1) ?: -1
            val simTag = if (subId >= 0) " [SIM ${subId + 1}]" else ""

            // Tìm sự kiện lỗi (bất kỳ đoạn nào lỗi đều khiến toàn bộ tin nhắn bị coi là lỗi)
            val failedEvent = jobEvents.firstOrNull { ev ->
                val stage = ev.optString("stage", "")
                val isSuccess = ev.optBoolean("is_success", stage != "FAILED")
                val code = ev.optInt("result_code", 0)
                !isSuccess || stage == "FAILED" || (stage == "SENT" && code != Activity.RESULT_OK && code != 0) || (stage == "DELIVERED" && code != Activity.RESULT_OK && code != 0)
            }

            // Tập hợp các part đã gửi và đã giao thành công
            val sentParts = jobEvents.filter {
                it.optString("stage") == "SENT" && it.optInt("result_code", 0) == Activity.RESULT_OK
            }.map { it.optInt("part_index", 0) }.toSet()

            val deliveredParts = jobEvents.filter {
                it.optString("stage") == "DELIVERED" && it.optInt("result_code", 0) == Activity.RESULT_OK
            }.map { it.optInt("part_index", 0) }.toSet()

            val statusCode: Int
            val statusText: String
            val errorDetail: String

            if (failedEvent != null) {
                statusCode = 1
                statusText = "❌ GỬI LỖI$simTag"
                val err = failedEvent.optString("error", "")
                val errCode = failedEvent.optInt("result_code", 0)
                errorDetail = if (err.isNotEmpty()) err else if (errCode != 0) "Mã lỗi nhà mạng: $errCode" else "Lỗi từ nhà mạng viễn thông"
            } else if (deliveredParts.size >= expected) {
                statusCode = 0
                statusText = "✅ ĐÃ GIAO$simTag"
                errorDetail = ""
            } else if (sentParts.size >= expected) {
                statusCode = 0
                statusText = "✅ ĐÃ GỬI$simTag"
                errorDetail = ""
            } else {
                if (System.currentTimeMillis() - timestamp > 35000) {
                    statusCode = 1
                    statusText = "❌ GỬI LỖI$simTag"
                    errorDetail = "Không nhận được phản hồi từ SIM/Nhà mạng sau 35s"
                } else {
                    statusCode = 2
                    statusText = "⏳ ĐANG GỬI$simTag"
                    errorDetail = ""
                }
            }

            val cleanPhone = phone.replace(Regex("[^0-9]"), "")
            if (cleanPhone.length >= 7) {
                bridgePhonesAndTimes.add(Pair(cleanPhone.takeLast(9), timestamp))
            }

            val itemType = if (statusCode == 1) Telephony.Sms.MESSAGE_TYPE_FAILED else if (statusCode == 0) Telephony.Sms.MESSAGE_TYPE_SENT else Telephony.Sms.MESSAGE_TYPE_OUTBOX
            newMessages.add(
                SmsItem(
                    -1000L - jobIndex++,
                    phone,
                    if (message.isNotEmpty()) message else "Lệnh gửi: $jobId",
                    timestamp,
                    itemType,
                    statusText,
                    statusCode,
                    errorDetail
                )
            )
        }

        // 3. Đọc từ Telephony.Sms nếu đã cấp quyền (Hộp thư nhận INBOX hoặc tin gửi từ app ngoài)
        if (hasReadPerm) {
            try {
                val projection = arrayOf(
                    Telephony.Sms._ID,
                    Telephony.Sms.ADDRESS,
                    Telephony.Sms.BODY,
                    Telephony.Sms.DATE,
                    Telephony.Sms.TYPE,
                    Telephony.Sms.STATUS,
                    Telephony.Sms.ERROR_CODE
                )
                val cursor = contentResolver.query(
                    Telephony.Sms.CONTENT_URI,
                    projection,
                    null,
                    null,
                    "${Telephony.Sms.DATE} DESC LIMIT 200"
                )
                cursor?.use {
                    val idIdx = it.getColumnIndex(Telephony.Sms._ID)
                    val addrIdx = it.getColumnIndex(Telephony.Sms.ADDRESS)
                    val bodyIdx = it.getColumnIndex(Telephony.Sms.BODY)
                    val dateIdx = it.getColumnIndex(Telephony.Sms.DATE)
                    val typeIdx = it.getColumnIndex(Telephony.Sms.TYPE)
                    val statusIdx = it.getColumnIndex(Telephony.Sms.STATUS)
                    val errorIdx = it.getColumnIndex(Telephony.Sms.ERROR_CODE)

                    while (it.moveToNext()) {
                        val id = if (idIdx >= 0) it.getLong(idIdx) else 0L
                        val address = if (addrIdx >= 0) it.getString(addrIdx) ?: "Không rõ" else "Không rõ"
                        val body = if (bodyIdx >= 0) it.getString(bodyIdx) ?: "" else ""
                        val date = if (dateIdx >= 0) it.getLong(dateIdx) else System.currentTimeMillis()
                        val type = if (typeIdx >= 0) it.getInt(typeIdx) else Telephony.Sms.MESSAGE_TYPE_SENT
                        val status = if (statusIdx >= 0) it.getInt(statusIdx) else -1
                        val errorCode = if (errorIdx >= 0) it.getInt(errorIdx) else 0

                        if (type == Telephony.Sms.MESSAGE_TYPE_INBOX) {
                            newMessages.add(SmsItem(id, address, body, date, type, "📩 ĐÃ NHẬN", 3, ""))
                        } else {
                            // Kiểm tra xem tin nhắn này đã có trong danh sách bridge chưa
                            val cleanAddr = address.replace(Regex("[^0-9]"), "")
                            val matchedBridge = bridgePhonesAndTimes.any { pair ->
                                cleanAddr.endsWith(pair.first) && Math.abs(pair.second - date) < 60000
                            }
                            if (!matchedBridge) {
                                val statusCode: Int
                                val statusText: String
                                val errorDetail: String
                                if (type == Telephony.Sms.MESSAGE_TYPE_FAILED || errorCode != 0) {
                                    statusCode = 1
                                    statusText = "❌ GỬI LỖI"
                                    errorDetail = if (errorCode != 0) "Mã lỗi: $errorCode" else "Gửi không thành công"
                                } else if (type == Telephony.Sms.MESSAGE_TYPE_SENT || status == Telephony.Sms.STATUS_COMPLETE) {
                                    statusCode = 0
                                    statusText = "✅ ĐÃ GỬI"
                                    errorDetail = ""
                                } else {
                                    statusCode = 2
                                    statusText = "⏳ ĐANG GỬI"
                                    errorDetail = ""
                                }
                                newMessages.add(SmsItem(id, address, body, date, type, statusText, statusCode, errorDetail))
                            }
                        }
                    }
                }
            } catch (e: Throwable) {
                e.printStackTrace()
            }
        }

        newMessages.sortByDescending { it.date }

        allMessages.clear()
        allMessages.addAll(newMessages)
        filterMessages(inputSearch.text.toString())
    }

    private fun filterMessages(query: String) {
        displayedMessages.clear()
        val q = query.trim().lowercase()
        if (q.isEmpty()) {
            displayedMessages.addAll(allMessages)
        } else {
            displayedMessages.addAll(allMessages.filter {
                it.address.lowercase().contains(q) || it.body.lowercase().contains(q) || it.statusText.lowercase().contains(q) || it.errorDetail.lowercase().contains(q)
            })
        }
        adapter.notifyDataSetChanged()
        txtListHeader.text = "📋 Hộp thư SMS (${displayedMessages.size})"
        txtEmpty.visibility = if (displayedMessages.isEmpty()) View.VISIBLE else View.GONE
    }

    private fun showSmsDetailDialog(item: SmsItem) {
        val dateFormat = SimpleDateFormat("HH:mm:ss dd/MM/yyyy", Locale.getDefault())
        val dateStr = dateFormat.format(Date(item.date))
        val typeStr = if (item.type == Telephony.Sms.MESSAGE_TYPE_INBOX) "Tin nhắn nhận về (INBOX)" else "Tin nhắn gửi đi (SENT)"

        val statusInfo = if (item.errorDetail.isNotEmpty()) {
            "${item.statusText}\n⚠️ Chi tiết lỗi: ${item.errorDetail}"
        } else {
            item.statusText
        }

        val messageDetails = """
📱 Số điện thoại: ${item.address}
🕒 Thời gian: $dateStr
🏷️ Loại: $typeStr
📊 Trạng thái thực tế:
$statusInfo

📝 Nội dung tin nhắn:
${item.body}
        """.trimIndent()

        AlertDialog.Builder(this)
            .setTitle("Chi tiết tin nhắn")
            .setMessage(messageDetails)
            .setPositiveButton("Soạn tin cho số này") { _, _ ->
                inputPhone.setText(item.address)
                inputMessage.requestFocus()
                Toast.makeText(this, "Đã chọn số ${item.address}", Toast.LENGTH_SHORT).show()
            }
            .setNeutralButton("Sao chép nội dung") { _, _ ->
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("SMS Content", item.body))
                Toast.makeText(this, "Đã sao chép nội dung tin nhắn!", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("Đóng", null)
            .show()
    }

    private fun sendDirectSms() {
        val phone = inputPhone.text.toString().trim()
        val message = inputMessage.text.toString().trim()

        if (phone.isEmpty()) {
            Toast.makeText(this, "Vui lòng nhập số điện thoại nhận!", Toast.LENGTH_SHORT).show()
            inputPhone.requestFocus()
            return
        }

        if (message.isEmpty()) {
            Toast.makeText(this, "Vui lòng nhập nội dung tin nhắn!", Toast.LENGTH_SHORT).show()
            inputMessage.requestFocus()
            return
        }

        if (checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(permissions, 100)
            Toast.makeText(this, "Vui lòng cấp quyền gửi SMS!", Toast.LENGTH_SHORT).show()
            return
        }

        try {
            @Suppress("DEPRECATION")
            val smsManager = SmsManager.getDefault()
            val parts = smsManager.divideMessage(message)
            val jobId = UUID.randomUUID().toString()

            val sent = ArrayList<PendingIntent>()
            val delivered = ArrayList<PendingIntent>()
            val flags = PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0)

            parts.indices.forEach { index ->
                val sentIntent = Intent(this, SmsResultReceiver::class.java).apply {
                    action = "vn.smsbridge.sender.SMS_SENT"
                    putExtra("job_id", jobId)
                    putExtra("phone", phone)
                    putExtra("message", message)
                    putExtra("part_index", index)
                    putExtra("part_count", parts.size)
                    putExtra("stage", "SENT")
                }

                val delIntent = Intent(this, SmsResultReceiver::class.java).apply {
                    action = "vn.smsbridge.sender.SMS_DELIVERED"
                    putExtra("job_id", jobId)
                    putExtra("phone", phone)
                    putExtra("message", message)
                    putExtra("part_index", index)
                    putExtra("part_count", parts.size)
                    putExtra("stage", "DELIVERED")
                }

                sent += PendingIntent.getBroadcast(this, "$jobId:SENT:$index".hashCode(), sentIntent, flags)
                delivered += PendingIntent.getBroadcast(this, "$jobId:DELIVERED:$index".hashCode(), delIntent, flags)
            }

            smsManager.sendMultipartTextMessage(phone, null, parts, sent, delivered)

            try {
                val values = ContentValues().apply {
                    put(Telephony.Sms.ADDRESS, phone)
                    put(Telephony.Sms.BODY, message)
                    put(Telephony.Sms.DATE, System.currentTimeMillis())
                    put(Telephony.Sms.TYPE, Telephony.Sms.MESSAGE_TYPE_OUTBOX)
                    put(Telephony.Sms.STATUS, Telephony.Sms.STATUS_PENDING)
                    put(Telephony.Sms.READ, 1)
                    put(Telephony.Sms.SEEN, 1)
                }
                contentResolver.insert(Telephony.Sms.Sent.CONTENT_URI, values)
            } catch (_: Exception) {}

            EventLog.append(
                this,
                JSONObject()
                    .put("job_id", jobId)
                    .put("phone", phone)
                    .put("message", message)
                    .put("stage", "QUEUED")
                    .put("part_count", parts.size)
                    .put("timestamp", System.currentTimeMillis())
            )

            Toast.makeText(this, "🚀 Đang gửi tin nhắn tới $phone...", Toast.LENGTH_SHORT).show()
            inputMessage.setText("")
            loadMessages()

        } catch (e: Exception) {
            Toast.makeText(this, "Lỗi gửi SMS: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    class SmsAdapter(private val context: Context, private val list: List<SmsItem>) : BaseAdapter() {
        private val dateFormat = SimpleDateFormat("HH:mm dd/MM", Locale.getDefault())

        override fun getCount(): Int = list.size
        override fun getItem(position: Int): Any = list[position]
        override fun getItemId(position: Int): Long = list[position].id

        override fun getView(position: Int, convertView: View?, parent: ViewGroup?): View {
            val view = convertView ?: LayoutInflater.from(context).inflate(R.layout.item_sms, parent, false)
            val item = list[position]

            val txtAvatar = view.findViewById<TextView>(R.id.item_avatar)
            val txtAddress = view.findViewById<TextView>(R.id.item_address)
            val txtDate = view.findViewById<TextView>(R.id.item_date)
            val txtBody = view.findViewById<TextView>(R.id.item_body)
            val txtBadge = view.findViewById<TextView>(R.id.item_badge)

            txtAddress.text = item.address
            txtBody.text = item.body
            txtDate.text = dateFormat.format(Date(item.date))

            val initial = if (item.address.isNotEmpty()) item.address.first().uppercase() else "S"
            txtAvatar.text = initial

            val avatarBg = GradientDrawable().apply { shape = GradientDrawable.OVAL }

            when (item.statusCode) {
                0 -> { // SENT / DELIVERED OK
                    avatarBg.setColor(Color.parseColor("#0081CB"))
                    txtBadge.text = item.statusText
                    txtBadge.setTextColor(Color.parseColor("#2E7D32"))
                    txtBadge.setBackgroundColor(Color.parseColor("#E8F5E9"))
                }
                1 -> { // FAILED / ERROR
                    avatarBg.setColor(Color.parseColor("#D32F2F"))
                    txtBadge.text = if (item.errorDetail.isNotBlank()) "${item.statusText}: ${item.errorDetail}" else item.statusText
                    txtBadge.setTextColor(Color.parseColor("#C62828"))
                    txtBadge.setBackgroundColor(Color.parseColor("#FFEBEE"))
                }
                2 -> { // PENDING / SENDING
                    avatarBg.setColor(Color.parseColor("#FF9800"))
                    txtBadge.text = item.statusText
                    txtBadge.setTextColor(Color.parseColor("#E65100"))
                    txtBadge.setBackgroundColor(Color.parseColor("#FFF3E0"))
                }
                3 -> { // INBOX
                    avatarBg.setColor(Color.parseColor("#7C4DFF"))
                    txtBadge.text = item.statusText
                    txtBadge.setTextColor(Color.parseColor("#5E35B1"))
                    txtBadge.setBackgroundColor(Color.parseColor("#EDE7F6"))
                }
                else -> {
                    avatarBg.setColor(Color.parseColor("#0081CB"))
                    txtBadge.text = item.statusText
                    txtBadge.setTextColor(Color.parseColor("#2E7D32"))
                    txtBadge.setBackgroundColor(Color.parseColor("#E8F5E9"))
                }
            }
            txtAvatar.background = avatarBg

            return view
        }
    }
}
