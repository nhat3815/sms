package vn.smsbridge.sender

import android.content.Context
import org.json.JSONObject

object EventLog {
    private var writeCount = 0

    @Synchronized
    fun append(context: Context, event: JSONObject) {
        try {
            context.openFileOutput("events.jsonl", Context.MODE_APPEND).bufferedWriter().use {
                it.append(event.toString()).append('\n')
            }
            writeCount++
            // Định kỳ cắt tỉa file nếu vượt quá 300 dòng để tiết kiệm dung lượng và tăng tốc truyền qua Wi-Fi
            if (writeCount % 30 == 0) {
                pruneEvents(context)
            }
        } catch (_: Exception) {}
    }

    @Synchronized
    private fun pruneEvents(context: Context) {
        try {
            val file = context.filesDir.resolve("events.jsonl")
            if (file.exists()) {
                val lines = file.readLines()
                if (lines.size > 300) {
                    val kept = lines.takeLast(200)
                    file.writeText(kept.joinToString("\n") + "\n")
                }
            }
        } catch (_: Exception) {}
    }
}

