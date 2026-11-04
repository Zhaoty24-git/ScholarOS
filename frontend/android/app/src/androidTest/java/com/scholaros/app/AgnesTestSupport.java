package com.scholaros.app;

import androidx.test.platform.app.InstrumentationRegistry;
import java.io.*;
import java.net.*;
import java.security.cert.Certificate;
import java.util.*;
import java.util.concurrent.CopyOnWriteArrayList;
import javax.net.ssl.HttpsURLConnection;
import org.json.*;
import static org.junit.Assert.*;

/** Only in the instrumentation APK: no Mock entry point or key in the app APK. */
final class AgnesTestSupport {
    static String key() { return String.join("-", "synthetic", "agnes", "x".repeat(40)); }
    static void requireSyntheticDevice() {
        assertEquals("Tests require the explicit synthetic-device argument", "true", InstrumentationRegistry.getArguments().getString("scholarosSynthetic"));
        assertTrue("Do not run these destructive fixture tests on a personal phone", android.os.Build.MODEL.contains("sdk") || android.os.Build.FINGERPRINT.contains("generic"));
    }
    static JSONArray messages(String text) throws Exception { return new JSONArray().put(new JSONObject().put("role", "user").put("content", text)); }
    static String answer(String text) throws Exception {
        return new JSONObject().put("choices", new JSONArray().put(new JSONObject().put("message", new JSONObject().put("role", "assistant").put("content", text)).put("finish_reason", "stop"))).toString();
    }
    static final class MockTransport extends AgnesTransport.Https {
        final List<JSONObject> requests = new CopyOnWriteArrayList<>();
        final List<String> providers = new CopyOnWriteArrayList<>();
        volatile int status = 200;
        volatile String body;
        volatile String contentType = "application/json";
        volatile boolean slowStream;
        volatile FakeConnection last;
        LoopbackServer loopback;
        MockTransport() throws Exception { body = answer("**合成 Mock 回答**\n```text\nnot a real Agnes response\n```\n<img src=\"https://untrusted.invalid/x\" onerror=\"window.modelScriptRan=true\"><script>window.modelScriptRan=true</script>"); }
        @Override HttpsURLConnection open(URL url) {
            FakeConnection connection = new FakeConnection(url, this); last = connection; return connection;
        }
    }
    static final class FakeConnection extends HttpsURLConnection {
        final ByteArrayOutputStream output = new ByteArrayOutputStream();
        final MockTransport owner;
        volatile boolean disconnected;
        byte[] response;
        FakeConnection(URL url, MockTransport owner) { super(url); this.owner = owner; }
        public OutputStream getOutputStream() { return output; }
        public int getResponseCode() throws IOException {
            try {
                JSONObject request = new JSONObject(output.toString("UTF-8")); owner.requests.add(request); owner.providers.add(url.getHost());
                if (owner.loopback != null) response = owner.loopback.exchange(output.toByteArray(), getRequestProperty("Authorization"));
                else response = owner.body.getBytes(java.nio.charset.StandardCharsets.UTF_8);
                return owner.status;
            } catch (Exception ex) { throw new IOException("Synthetic response failure"); }
        }
        public String getContentType() { return owner.contentType; }
        public InputStream getInputStream() {
            if (!owner.slowStream) return new ByteArrayInputStream(response);
            byte[] first = "data: {\"choices\":[{\"delta\":{\"content\":\"合成流式片段\"},\"finish_reason\":null}]}\n\n".getBytes(java.nio.charset.StandardCharsets.UTF_8);
            return new InputStream() {
                int pos;
                public int read() throws IOException {
                    if (pos < first.length) return first[pos++] & 255;
                    while (!disconnected) { try { Thread.sleep(20); } catch (InterruptedException ex) { throw new IOException("Cancelled fixture"); } }
                    throw new IOException("Cancelled fixture");
                }
                public int read(byte[] b, int off, int len) throws IOException {
                    if (pos >= first.length) return read();
                    int n = Math.min(len, first.length - pos); System.arraycopy(first, pos, b, off, n); pos += n; return n;
                }
            };
        }
        public void disconnect() { disconnected = true; }
        public boolean usingProxy() { return false; }
        public void connect() {}
        public String getCipherSuite() { return "TEST_ONLY"; }
        public Certificate[] getLocalCertificates() { return null; }
        public Certificate[] getServerCertificates() { return new Certificate[0]; }
    }

    /** Real loopback HTTP fixture under a test-only HTTPS connection adapter.
     * Production still opens only the official HTTPS URLs with platform TLS.
     */
    static final class LoopbackServer implements AutoCloseable {
        final ServerSocket listener;
        final Thread thread;
        final String response;
        volatile JSONObject received;
        volatile boolean bearerReceived;
        volatile Throwable failure;
        LoopbackServer(String response) throws Exception {
            this.response = response;
            listener = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")); listener.setSoTimeout(5000);
            thread = new Thread(() -> {
                try (Socket socket = listener.accept()) {
                    socket.setSoTimeout(5000); InputStream input = socket.getInputStream();
                    ByteArrayOutputStream header = new ByteArrayOutputStream(); int b;
                    while ((b = input.read()) >= 0) { header.write(b); if (header.toString("UTF-8").endsWith("\r\n\r\n")) break; if (header.size() > 10000) throw new IOException("Fixture header limit"); }
                    String headers = header.toString("UTF-8");
                    int length = Integer.parseInt(headers.split("Content-Length: ")[1].split("\r\n")[0]);
                    byte[] body = new byte[length]; int read = 0;
                    while (read < length) { int n = input.read(body, read, length-read); if (n < 0) throw new EOFException(); read += n; }
                    received = new JSONObject(new String(body, java.nio.charset.StandardCharsets.UTF_8));
                    bearerReceived = headers.contains("Authorization: Bearer " + key());
                    byte[] data = response.getBytes(java.nio.charset.StandardCharsets.UTF_8);
                    OutputStream out = socket.getOutputStream(); out.write(("HTTP/1.1 200 OK\r\nContent-Length: " + data.length + "\r\n\r\n").getBytes(java.nio.charset.StandardCharsets.US_ASCII)); out.write(data); out.flush();
                } catch (Throwable ex) { failure = ex; }
            }, "local-api-fixture"); thread.setDaemon(true); thread.start();
        }
        byte[] exchange(byte[] body, String authorization) throws Exception {
            try (Socket socket = new Socket("127.0.0.1", listener.getLocalPort())) {
                socket.setSoTimeout(5000); OutputStream out = socket.getOutputStream();
                out.write(("POST /v1/chat/completions HTTP/1.1\r\nHost: api.agnes-ai.cn\r\nAuthorization: " + authorization + "\r\nContent-Length: " + body.length + "\r\n\r\n").getBytes(java.nio.charset.StandardCharsets.UTF_8)); out.write(body); out.flush();
                InputStream in = socket.getInputStream(); ByteArrayOutputStream header = new ByteArrayOutputStream(); int b;
                while ((b = in.read()) >= 0) { header.write(b); if (header.toString("UTF-8").endsWith("\r\n\r\n")) break; }
                return AgnesProtocol.readBounded(in).getBytes(java.nio.charset.StandardCharsets.UTF_8);
            }
        }
        public void close() throws Exception { listener.close(); thread.join(2000); }
    }
}
