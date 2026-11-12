package za.co.kwikpay.kwikpay_merchant

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
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
    private fun accessKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val existing = store.getKey("kwikpay_merchant_access_v1", null) as? SecretKey
        if (existing != null) return existing
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder("kwikpay_merchant_access_v1", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        return generator.generateKey()
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "kwikpay/merchant_access")
            .setMethodCallHandler { call, result ->
                try {
                    val prefs = getSharedPreferences("merchant_access", MODE_PRIVATE)
                    when (call.method) {
                        "configured" -> result.success(prefs.contains("ciphertext") && prefs.contains("iv"))
                        "load" -> {
                            val encrypted = prefs.getString("ciphertext", null)
                            val iv = prefs.getString("iv", null)
                            if (encrypted == null || iv == null) return@setMethodCallHandler result.success(null)
                            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                            cipher.init(Cipher.DECRYPT_MODE, accessKey(), GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)))
                            result.success(String(cipher.doFinal(Base64.decode(encrypted, Base64.NO_WRAP)), Charsets.UTF_8))
                        }
                        "save" -> {
                            val value = call.arguments as String
                            require(value.length in 1..256 && value.all { it.code in 33..126 })
                            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                            cipher.init(Cipher.ENCRYPT_MODE, accessKey())
                            val encrypted = Base64.encodeToString(cipher.doFinal(value.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP)
                            check(prefs.edit().putString("ciphertext", encrypted).putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP)).commit())
                            result.success(null)
                        }
                        "clear" -> { check(prefs.edit().clear().commit()); result.success(null) }
                        else -> result.notImplemented()
                    }
                } catch (_: Exception) { result.error("access_storage", "Could not access merchant settings", null) }
            }
        val preferences = getSharedPreferences("demo_sales", MODE_PRIVATE)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "kwikpay/demo_sales")
            .setMethodCallHandler { call, result ->
                try {
                    when (call.method) {
                        "list" -> result.success(preferences.getString("sales", "[]"))
                        "add" -> {
                            val sale = JSONObject(call.arguments as String)
                            val previous = JSONArray(preferences.getString("sales", "[]"))
                            val next = JSONArray().put(sale)
                            // shortcut: keep 100 device-local demo records; use a real ledger for sales.
                            for (i in 0 until previous.length()) {
                                val old = previous.getJSONObject(i)
                                if (sale.has("id") && sale.optString("id") == old.optString("id")) continue
                                if (next.length() >= 100) break
                                next.put(old)
                            }
                            if (!preferences.edit().putString("sales", next.toString()).commit()) {
                                result.error("storage", "Could not save demo sale", null)
                            } else result.success(null)
                        }
                        else -> result.notImplemented()
                    }
                } catch (e: Exception) {
                    result.error("storage", "Could not access demo sales", null)
                }
            }
    }
}
