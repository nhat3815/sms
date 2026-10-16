package vn.smsbridge.master

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONObject
import java.security.SecureRandom
import java.util.UUID

class MasterStore(context: Context) : SQLiteOpenHelper(context, "master.sqlite3", null, 1) {
    private val appContext = context.applicationContext
    companion object {
        private const val PREFS = "master_config"
        private const val TOKEN = "cluster_token"
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE jobs(id TEXT PRIMARY KEY, device_id TEXT, phone TEXT, message TEXT, subscription_id INTEGER, status TEXT, detail TEXT, created_at INTEGER, claimed_at INTEGER, finished_at INTEGER)")
        db.execSQL("CREATE TABLE devices(id TEXT PRIMARY KEY, last_seen INTEGER)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    fun clusterToken(): String {
        val prefs = appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val existing = prefs.getString(TOKEN, null)
        if (existing != null) return existing
        val bytes = ByteArray(24)
        SecureRandom().nextBytes(bytes)
        val generated = bytes.joinToString("") { "%02x".format(it) }
        prefs.edit().putString(TOKEN, generated).apply()
        return generated
    }

    fun enqueue(deviceId: String, phone: String, message: String): String {
        val id = UUID.randomUUID().toString()
        writableDatabase.execSQL(
            "INSERT INTO jobs(id, device_id, phone, message, subscription_id, status, detail, created_at) VALUES (?, ?, ?, ?, -1, 'QUEUED', '', ?)",
            arrayOf(id, deviceId, phone, message, System.currentTimeMillis())
        )
        return id
    }

    fun claim(deviceId: String): JSONObject? {
        val db = writableDatabase
        db.beginTransaction()
        try {
            val cursor = db.rawQuery("SELECT id, phone, message, subscription_id FROM jobs WHERE device_id = ? AND status = 'QUEUED' ORDER BY created_at LIMIT 1", arrayOf(deviceId))
            cursor.use {
                if (!it.moveToFirst()) return null
                val job = JSONObject()
                    .put("id", it.getString(0))
                    .put("phone", it.getString(1))
                    .put("message", it.getString(2))
                    .put("subscription_id", it.getInt(3))
                db.execSQL("UPDATE jobs SET status = 'CLAIMED', claimed_at = ? WHERE id = ?", arrayOf(System.currentTimeMillis(), job.getString("id")))
                db.setTransactionSuccessful()
                return job
            }
        } finally {
            db.endTransaction()
        }
    }

    fun heartbeat(deviceId: String) {
        writableDatabase.execSQL("INSERT OR REPLACE INTO devices(id, last_seen) VALUES (?, ?)", arrayOf(deviceId, System.currentTimeMillis()))
    }

    fun result(deviceId: String, jobId: String, status: String, detail: String): Boolean {
        val db = writableDatabase
        val cursor = db.rawQuery("SELECT id FROM jobs WHERE id = ? AND device_id = ?", arrayOf(jobId, deviceId))
        cursor.use { if (!it.moveToFirst()) return false }
        db.execSQL("UPDATE jobs SET status = ?, detail = ?, finished_at = ? WHERE id = ?", arrayOf(status, detail.take(2000), System.currentTimeMillis(), jobId))
        heartbeat(deviceId)
        return true
    }
}
