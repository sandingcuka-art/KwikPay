package za.co.kwikpay.kwikpay_customer

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import android.content.Intent
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class MainActivity : FlutterActivity() {
    private fun receiptKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val existing = store.getKey("kwikpay_receipts_v1", null) as? SecretKey
        if (existing != null) return existing
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder("kwikpay_receipts_v1", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        return generator.generateKey()
    }

    private fun encryptPath(path: String): JSONObject {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, receiptKey())
        return JSONObject().put("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .put("data", Base64.encodeToString(cipher.doFinal(path.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP))
    }

    private fun decryptPath(value: JSONObject): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, receiptKey(), GCMParameterSpec(128, Base64.decode(value.getString("iv"), Base64.NO_WRAP)))
        return String(cipher.doFinal(Base64.decode(value.getString("data"), Base64.NO_WRAP)), Charsets.UTF_8)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "kwikpay/receipts")
            .setMethodCallHandler { call, result ->
                try {
                    val prefs = getSharedPreferences("kwikpay_receipts", MODE_PRIVATE)
                    val receipts = JSONArray(prefs.getString("items", "[]"))
                    when (call.method) {
                        "list" -> {
                            val visible = JSONArray()
                            for (i in 0 until receipts.length()) {
                                val item = receipts.getJSONObject(i)
                                val encrypted = item.optJSONObject("lookup")
                                item.remove("lookup")
                                if (encrypted != null) {
                                    try { item.put("requestPath", decryptPath(encrypted)) } catch (_: Exception) { }
                                }
                                visible.put(item)
                            }
                            result.success(visible.toString())
                        }
                        "save" -> {
                            val args = call.arguments as Map<*, *>
                            val receipt = JSONObject(args["receipt"] as String)
                            val path = args["path"] as? String
                            if (path != null) receipt.put("lookup", encryptPath(path))
                            val items = JSONArray()
                            var found = false
                            for (i in 0 until receipts.length()) {
                                val old = receipts.getJSONObject(i)
                                if (old.getString("executionId") == receipt.getString("executionId")) {
                                    if (path == null && old.has("lookup")) receipt.put("lookup", old.getJSONObject("lookup"))
                                    items.put(receipt)
                                    found = true
                                } else if (items.length() < 100) items.put(old)
                            }
                            if (!found) {
                                val updated = JSONArray().put(receipt)
                                for (i in 0 until minOf(items.length(), 99)) updated.put(items.getJSONObject(i))
                                check(prefs.edit().putString("items", updated.toString()).commit())
                                return@setMethodCallHandler result.success(null)
                            }
                            check(prefs.edit().putString("items", items.toString()).commit())
                            result.success(null)
                        }
                        else -> result.notImplemented()
                    }
                } catch (e: Exception) {
                    result.error("receipt_storage", "Could not access receipts", null)
                }
            }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "kwikpay/settings")
            .setMethodCallHandler { call, result ->
                try {
                    val prefs = getSharedPreferences("kwikpay_settings", MODE_PRIVATE)
                    when (call.method) {
                        "load" -> result.success(prefs.getString("wallet", ""))
                        "save" -> {
                            val wallet = call.arguments as String
                            check(prefs.edit().putString("wallet", wallet).commit())
                            result.success(null)
                        }
                        else -> result.notImplemented()
                    }
                } catch (_: Exception) {
                    result.error("settings_storage", "Could not save or load settings", null)
                }
            }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "kwikpay/test_wallet")
            .setMethodCallHandler { call, result ->
                if (call.method != "open") return@setMethodCallHandler result.notImplemented()
                try {
                    val uri = Uri.parse(call.arguments as String)
                    require(uri.scheme == "https" && uri.host == "auth.interledger-test.dev" && uri.port == -1 && uri.userInfo == null)
                    startActivity(Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE))
                    result.success(null)
                } catch (e: Exception) {
                    result.error("wallet_unavailable", "Could not open Test Wallet", null)
                }
            }
    }
}
