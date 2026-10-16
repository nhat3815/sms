package vn.smsbridge.sender

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap

class SmsResultReceiver : BroadcastReceiver() {

    companion object {
        // Ghi nhớ các job đã từng bị lỗi bất kỳ đoạn nào để không bị sự kiện DELIVERED của đoạn khác ghi đè
        private val failedJobs = ConcurrentHashMap<String, String>()
        // Theo dõi số đoạn đã gửi thành công theo job_id: jobId -> Set of partIndex
        private val sentParts = ConcurrentHashMap<String, MutableSet<Int>>()
        private val deliveredParts = ConcurrentHashMap<String, MutableSet<Int>>()
    }

    override fun onReceive(context: Context, intent: Intent) {
        val stage = intent.getStringExtra("stage") ?: "EVENT"
        val jobId = intent.getStringExtra("job_id") ?: ""
        val phone = intent.getStringExtra("phone") ?: ""
        val message = intent.getStringExtra("message") ?: ""
        val partIndex = intent.getIntExtra("part_index", 0)
        val partCount = intent.getIntExtra("part_count", 1)
        val code = resultCode
        val networkErrorCode = intent.getIntExtra("errorCode", -1)

        val isSuccess = (code == Activity.RESULT_OK)
        val finalStage = if (isSuccess) stage else "FAILED"

        val errorDescription: String? = if (!isSuccess) {
            val netCodeStr = if (networkErrorCode > 0) " [RIL code $networkErrorCode]" else ""
            val partInfo = if (partCount > 1) " (Đoạn ${partIndex + 1}/$partCount bị lỗi)" else ""
            when (code) {
                1 -> "GENERIC_FAILURE$netCodeStr$partInfo: Hết tiền tài khoản gốc / Hết gói SMS ngoại mạng / Lỗi SIM hoặc nhà mạng từ chối"
                2 -> "RADIO_OFF$netCodeStr$partInfo: Tắt sóng / Đang bật Chế độ máy bay"
                3 -> "NULL_PDU$netCodeStr$partInfo: Lỗi định dạng tin nhắn PDU"
                4 -> "NO_SERVICE$netCodeStr$partInfo: Không có sóng mạng di động"
                5 -> "LIMIT_EXCEEDED$netCodeStr$partInfo: Vượt hạn mức số lượng SMS của nhà mạng"
                6 -> "FDN_CHECK_FAILURE$netCodeStr$partInfo: Bị chặn bởi danh bạ cố định FDN trên SIM"
                7 -> "SHORT_CODE_NOT_ALLOWED$netCodeStr$partInfo: Đầu số ngắn bị chặn"
                8 -> "SHORT_CODE_NEVER_ALLOWED$netCodeStr$partInfo: Đầu số ngắn không được phép"
                else -> "Mã lỗi $code$netCodeStr$partInfo từ nhà mạng viễn thông"
            }
        } else {
            null
        }

        if (!isSuccess && jobId.isNotEmpty() && errorDescription != null) {
            failedJobs[jobId] = errorDescription
        }

        val subscriptionId = intent.getIntExtra("subscription_id", -1)

        // Cập nhật trạng thái vào SMS Provider nếu có thể (chỉ cập nhật tin nhắn trong vòng 60 giây gần nhất)
        tryUpdateSmsStore(context, phone, isSuccess, finalStage, code)

        // Ghi log sự kiện cho cả App và Web đọc
        EventLog.append(
            context,
            JSONObject()
                .put("job_id", jobId)
                .put("phone", phone)
                .put("message", message)
                .put("stage", finalStage)
                .put("subscription_id", subscriptionId)
                .put("part_index", partIndex)
                .put("part_count", partCount)
                .put("result_code", code)
                .put("network_error_code", networkErrorCode)
                .put("is_success", isSuccess)
                .put("error", errorDescription ?: "")
                .put("timestamp", System.currentTimeMillis())
        )

        // Xử lý báo cáo CloudSyncService chính xác cho multipart:
        if (jobId.isNotEmpty()) {
            val hasFailed = failedJobs.containsKey(jobId)
            if (hasFailed) {
                // Đã có đoạn bị lỗi -> Báo cáo FAILED và không cho phép bất kỳ sự kiện DELIVERED nào ghi đè
                val err = failedJobs[jobId] ?: errorDescription ?: "Lỗi gửi SMS"
                CloudSyncService.reportResult(
                    context = context,
                    jobId = jobId,
                    status = "FAILED",
                    detail = err,
                    phone = phone,
                    message = message,
                    resultCode = if (code != Activity.RESULT_OK) code else 1,
                    subscriptionId = subscriptionId
                )
            } else if (isSuccess) {
                if (stage == "DELIVERED") {
                    val parts = deliveredParts.computeIfAbsent(jobId) { ConcurrentHashMap.newKeySet() }
                    parts.add(partIndex)
                    if (parts.size >= partCount) {
                        CloudSyncService.reportResult(
                            context = context,
                            jobId = jobId,
                            status = "DELIVERED",
                            detail = "Đã giao đến người nhận",
                            phone = phone,
                            message = message,
                            resultCode = code,
                            subscriptionId = subscriptionId
                        )
                    }
                } else if (stage == "SENT") {
                    val parts = sentParts.computeIfAbsent(jobId) { ConcurrentHashMap.newKeySet() }
                    parts.add(partIndex)
                    if (parts.size >= partCount) {
                        CloudSyncService.reportResult(
                            context = context,
                            jobId = jobId,
                            status = "SENT",
                            detail = "Đã gửi qua SIM thành công",
                            phone = phone,
                            message = message,
                            resultCode = code,
                            subscriptionId = subscriptionId
                        )
                    }
                }
            }
        }

        // Dọn dẹp cache cũ sau 10 phút
        if (failedJobs.size > 500) {
            failedJobs.clear()
            sentParts.clear()
            deliveredParts.clear()
        }
    }

    private fun tryUpdateSmsStore(
        context: Context,
        phone: String,
        isSuccess: Boolean,
        stage: String,
        resultCode: Int
    ) {
        try {
            val values = ContentValues().apply {
                if (!isSuccess) {
                    put(Telephony.Sms.TYPE, Telephony.Sms.MESSAGE_TYPE_FAILED)
                    put(Telephony.Sms.STATUS, Telephony.Sms.STATUS_FAILED)
                    put(Telephony.Sms.ERROR_CODE, resultCode)
                } else if (stage == "DELIVERED") {
                    put(Telephony.Sms.TYPE, Telephony.Sms.MESSAGE_TYPE_SENT)
                    put(Telephony.Sms.STATUS, Telephony.Sms.STATUS_COMPLETE)
                } else {
                    put(Telephony.Sms.TYPE, Telephony.Sms.MESSAGE_TYPE_SENT)
                    put(Telephony.Sms.STATUS, Telephony.Sms.STATUS_NONE)
                }
            }

            // Chỉ cập nhật tin nhắn trong vòng 60 giây gần nhất, tránh làm hỏng lịch sử tin cũ
            val oneMinuteAgo = System.currentTimeMillis() - 60_000L
            val selection = "(${Telephony.Sms.ADDRESS} = ? OR ${Telephony.Sms.ADDRESS} LIKE ?) AND ${Telephony.Sms.DATE} >= ?"
            val selectionArgs = arrayOf(phone, "%${phone.takeLast(9)}", oneMinuteAgo.toString())
            context.contentResolver.update(
                Telephony.Sms.CONTENT_URI,
                values,
                selection,
                selectionArgs
            )
        } catch (_: Exception) {
            // Ignored if not default SMS app
        }
    }
}
