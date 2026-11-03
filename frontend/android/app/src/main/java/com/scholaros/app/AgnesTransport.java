package com.scholaros.app;

import java.net.URL;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONObject;

/** Fixed HTTPS target, normal platform TLS, no redirects, cookies or retries. */
interface AgnesTransport {
    AgnesProtocol.Result execute(String provider, JSONObject request, byte[] credential, Operation operation, AgnesProtocol.Chunk chunk) throws Exception;

    final class Operation {
        final AtomicBoolean cancelled = new AtomicBoolean();
        volatile HttpsURLConnection connection;
        void check() { if (cancelled.get() || Thread.currentThread().isInterrupted()) throw new IllegalStateException("CANCELLED"); }
        void cancel() { cancelled.set(true); HttpsURLConnection c = connection; if (c != null) c.disconnect(); }
    }

    final class HttpFailure extends Exception {
        final String code;
        HttpFailure(String code) { super(code); this.code = code; }
    }

    class Https implements AgnesTransport {
        // Package-private injection seam; no JS API or alternate URL in production.
        HttpsURLConnection open(URL url) throws Exception { return (HttpsURLConnection) url.openConnection(); }
        public AgnesProtocol.Result execute(String provider, JSONObject request, byte[] credential, Operation operation, AgnesProtocol.Chunk chunk) throws Exception {
            operation.check();
            URL url = new URL(AgnesProtocol.endpoint(provider));
            if (!"https".equals(url.getProtocol()) || !("apihub.agnes-ai.com".equals(url.getHost()) || "api.agnes-ai.cn".equals(url.getHost())) || url.getPort() != -1 || !"/v1/chat/completions".equals(url.getPath())) throw new HttpFailure("TARGET");
            HttpsURLConnection connection = open(url); operation.connection = connection;
            try {
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(10000); connection.setReadTimeout(45000);
                connection.setRequestMethod("POST"); connection.setDoOutput(true); connection.setUseCaches(false);
                connection.setRequestProperty("Content-Type", "application/json");
                connection.setRequestProperty("Accept", request.getBoolean("stream") ? "text/event-stream, application/json" : "application/json");
                connection.setRequestProperty("Authorization", "Bearer " + new String(credential, StandardCharsets.UTF_8));
                byte[] body = request.toString().getBytes(StandardCharsets.UTF_8);
                connection.setFixedLengthStreamingMode(body.length);
                operation.check();
                try (java.io.OutputStream output = connection.getOutputStream()) { operation.check(); output.write(body); }
                operation.check();
                int status = connection.getResponseCode();
                if (status != 200) {
                    // Never return upstream bodies/headers: they may echo a key.
                    if (status == 401 || status == 403) throw new HttpFailure("UNAUTHORIZED");
                    if (status == 429) throw new HttpFailure("RATE_LIMIT");
                    if (status >= 300 && status < 400) throw new HttpFailure("REDIRECT");
                    if (status >= 500) throw new HttpFailure("SERVER");
                    throw new HttpFailure("REQUEST");
                }
                String type = connection.getContentType();
                if (type == null) throw new HttpFailure("FORMAT");
                try (java.io.InputStream input = connection.getInputStream()) {
                    AgnesProtocol.Result result;
                    if (type.toLowerCase(java.util.Locale.ROOT).startsWith("text/event-stream") && request.getBoolean("stream"))
                        result = AgnesProtocol.streamResponse(input, text -> { operation.check(); chunk.accept(text); });
                    else if (type.toLowerCase(java.util.Locale.ROOT).startsWith("application/json")) result = AgnesProtocol.jsonResponse(AgnesProtocol.readBounded(input));
                    else throw new HttpFailure("FORMAT");
                    operation.check(); return result;
                }
            } catch (SocketTimeoutException ex) { throw new HttpFailure("TIMEOUT"); }
            finally { connection.disconnect(); operation.connection = null; }
        }
    }
}
