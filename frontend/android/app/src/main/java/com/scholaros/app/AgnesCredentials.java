package com.scholaros.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Native-only credential vault. No method returns a credential to JavaScript. */
final class AgnesCredentials {
    static final String PREFS = "agnes_credentials_v1";
    static final String ALIAS = "scholaros.agnes.aes.v1";
    private final SharedPreferences prefs;
    private byte[] memory;
    private String memoryProvider;

    AgnesCredentials(Context context) {
        prefs = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    synchronized boolean configured() { return memory != null || prefs.contains("ciphertext"); }
    synchronized boolean persistent() { return prefs.contains("ciphertext"); }
    synchronized String provider() { return memory != null ? memoryProvider : prefs.getString("provider", "agnes-cn"); }

    synchronized void save(String key, boolean persist, String provider) throws Exception {
        if (key == null || !key.matches("[\\x21-\\x7e]{1,4096}")) throw new IllegalArgumentException("KEY_FORMAT");
        AgnesProtocol.baseUrl(provider); // Reject unreviewed providers before mutation.
        clear(); // Rotation makes previous encrypted values undecryptable.
        byte[] plain = key.getBytes(StandardCharsets.UTF_8);
        if (!persist) { memory = plain; memoryProvider = provider; return; }
        try {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).build());
            SecretKey secret = generator.generateKey();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, secret);
            cipher.updateAAD(provider.getBytes(StandardCharsets.UTF_8));
            String encrypted = Base64.encodeToString(cipher.doFinal(plain), Base64.NO_WRAP);
            String iv = Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP);
            if (!prefs.edit().putString("ciphertext", encrypted).putString("iv", iv).putString("provider", provider).commit()) throw new IllegalStateException("STORAGE");
        } catch (Exception ex) {
            clear();
            throw new IllegalStateException("STORAGE");
        } finally { Arrays.fill(plain, (byte) 0); }
    }

    synchronized byte[] read() throws Exception {
        if (memory != null) return memory.clone();
        if (!prefs.contains("ciphertext")) throw new IllegalStateException("NO_KEY");
        try {
            KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
            SecretKey key = (SecretKey) store.getKey(ALIAS, null);
            if (key == null) throw new IllegalStateException("STORAGE");
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, Base64.decode(prefs.getString("iv", ""), Base64.NO_WRAP)));
            cipher.updateAAD(provider().getBytes(StandardCharsets.UTF_8));
            return cipher.doFinal(Base64.decode(prefs.getString("ciphertext", ""), Base64.NO_WRAP));
        } catch (Exception ex) { throw new IllegalStateException("STORAGE"); }
    }

    synchronized void clearMemory() { if (memory != null) Arrays.fill(memory, (byte) 0); memory = null; memoryProvider = null; }

    synchronized void clear() throws Exception {
        clearMemory();
        boolean wasPersistent = prefs.contains("ciphertext");
        boolean committed = prefs.edit().clear().commit();
        boolean keyDeleted = true;
        try {
            KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
            if (store.containsAlias(ALIAS)) store.deleteEntry(ALIAS);
        } catch (Exception ex) { keyDeleted = false; }
        // Memory-only mode must still work on devices without a usable Keystore.
        if (!committed || (wasPersistent && !keyDeleted)) throw new IllegalStateException("STORAGE");
    }
}
