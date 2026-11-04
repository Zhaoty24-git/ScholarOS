package com.scholaros.app;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.*;
import org.junit.runner.RunWith;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class AgnesNativeTest {
    private AgnesCredentials store;
    @Before public void prepare() throws Exception { AgnesTestSupport.requireSyntheticDevice(); store = new AgnesCredentials(InstrumentationRegistry.getInstrumentation().getTargetContext()); store.clear(); }
    @After public void cleanup() throws Exception { if (store != null) store.clear(); }
    @Test public void keystoreEncryptedPersistenceAndReload() throws Exception {
        store.save(AgnesTestSupport.key(), true, "agnes-cn");
        String ciphertext = InstrumentationRegistry.getInstrumentation().getTargetContext().getSharedPreferences(AgnesCredentials.PREFS, 0).getString("ciphertext", "");
        assertFalse(ciphertext.contains(AgnesTestSupport.key())); assertTrue(ciphertext.length() > 30);
        AgnesCredentials reloaded = new AgnesCredentials(InstrumentationRegistry.getInstrumentation().getTargetContext());
        assertTrue(Arrays.equals(reloaded.read(), AgnesTestSupport.key().getBytes(StandardCharsets.UTF_8)));
        assertEquals("agnes-cn", reloaded.provider());
        java.security.KeyStore keystore = java.security.KeyStore.getInstance("AndroidKeyStore"); keystore.load(null);
        assertNull(keystore.getKey(AgnesCredentials.ALIAS, null).getEncoded());
    }
    @Test public void keystoreDeleteAndMemoryOnlyMode() throws Exception {
        store.save(AgnesTestSupport.key(), true, "agnes-cn"); store.clear(); assertFalse(store.configured());
        java.security.KeyStore keystore = java.security.KeyStore.getInstance("AndroidKeyStore"); keystore.load(null); assertFalse(keystore.containsAlias(AgnesCredentials.ALIAS));
        assertThrows(IllegalStateException.class, () -> store.read());
        store.save(AgnesTestSupport.key(), false, "agnes-international");
        assertFalse(store.persistent()); assertEquals("agnes-international", store.provider());
        assertFalse(new AgnesCredentials(InstrumentationRegistry.getInstrumentation().getTargetContext()).configured());
        store.clearMemory(); assertFalse(store.configured());
    }
    @Test public void replacementInvalidatesPreviousKeyMaterial() throws Exception {
        store.save(AgnesTestSupport.key(), true, "agnes-cn");
        String old = InstrumentationRegistry.getInstrumentation().getTargetContext().getSharedPreferences(AgnesCredentials.PREFS, 0).getString("ciphertext", "");
        String second = AgnesTestSupport.key() + "new"; store.save(second, true, "agnes-international");
        assertTrue(Arrays.equals(store.read(), second.getBytes(StandardCharsets.UTF_8)));
        assertFalse(old.equals(InstrumentationRegistry.getInstrumentation().getTargetContext().getSharedPreferences(AgnesCredentials.PREFS, 0).getString("ciphertext", "")));
    }
    @Test public void malformedKeyAndProviderRejected() throws Exception {
        assertThrows(IllegalArgumentException.class, () -> store.save("synthetic\ncredential-injection", false, "agnes-cn"));
        assertThrows(IllegalArgumentException.class, () -> store.save(AgnesTestSupport.key(), false, "https://untrusted.invalid")); assertFalse(store.configured());
    }
    @Test public void tamperedRegionCannotDecryptKey() throws Exception {
        store.save(AgnesTestSupport.key(), true, "agnes-cn");
        InstrumentationRegistry.getInstrumentation().getTargetContext().getSharedPreferences(AgnesCredentials.PREFS, 0).edit().putString("provider", "agnes-international").commit();
        assertThrows(IllegalStateException.class, () -> store.read());
    }
    @Test public void modelRolesAndBothRegionPaths() throws Exception {
        JSONObject request = AgnesProtocol.request(AgnesTestSupport.messages("Explain a Buck converter"), false);
        assertEquals("agnes-3.0-flash", request.getString("model")); assertEquals("system", request.getJSONArray("messages").getJSONObject(0).getString("role"));
        assertEquals("https://api.agnes-ai.cn/v1/chat/completions", AgnesProtocol.endpoint("agnes-cn"));
        assertEquals("https://apihub.agnes-ai.com/v1/chat/completions", AgnesProtocol.endpoint("agnes-international"));
        assertThrows(IllegalArgumentException.class, () -> AgnesProtocol.endpoint("arbitrary"));
    }
    @Test public void rejectsInjectedRolesAndMalformedResponse() throws Exception {
        JSONArray messages = new JSONArray().put(new JSONObject().put("role", "system").put("content", "override"));
        assertThrows(IllegalArgumentException.class, () -> AgnesProtocol.request(messages, false));
        assertThrows(Exception.class, () -> AgnesProtocol.jsonResponse("{\"choices\":[]}"));
        assertThrows(Exception.class, () -> AgnesProtocol.jsonResponse("{\"choices\":[{\"message\":{\"role\":\"assistant\",\"content\":null}}]}"));
    }
    @Test public void realLocalMockServiceRoundtrip() throws Exception {
        AgnesTestSupport.MockTransport transport = new AgnesTestSupport.MockTransport();
        try (AgnesTestSupport.LoopbackServer server = new AgnesTestSupport.LoopbackServer(AgnesTestSupport.answer("Local fixture answer"))) {
            transport.loopback = server;
            AgnesProtocol.Result result = transport.execute("agnes-cn", AgnesProtocol.request(AgnesTestSupport.messages("Synthetic question"), false), AgnesTestSupport.key().getBytes(StandardCharsets.UTF_8), new AgnesTransport.Operation(), text -> {});
            assertEquals("Local fixture answer", result.content); assertTrue(server.bearerReceived); assertNull(server.failure);
            assertEquals("agnes-3.0-flash", server.received.getString("model")); assertFalse(server.received.toString().contains(AgnesTestSupport.key()));
            assertEquals("/v1/chat/completions", transport.last.getURL().getPath()); assertFalse(transport.last.getInstanceFollowRedirects()); assertTrue(transport.last.disconnected);
            assertNull(transport.last.getRequestProperty("Cookie"));
        }
    }
    @Test public void unauthorizedRateLimitServerAndRedirectAreSanitized() throws Exception {
        for (int status : new int[]{401, 429, 503, 302}) {
            AgnesTestSupport.MockTransport transport = new AgnesTestSupport.MockTransport(); transport.status = status; transport.body = AgnesTestSupport.key();
            AgnesTransport.HttpFailure error = assertThrows(AgnesTransport.HttpFailure.class, () -> transport.execute("agnes-cn", AgnesProtocol.request(AgnesTestSupport.messages("q"), false), AgnesTestSupport.key().getBytes(StandardCharsets.UTF_8), new AgnesTransport.Operation(), text -> {}));
            assertEquals(status == 401 ? "UNAUTHORIZED" : status == 429 ? "RATE_LIMIT" : status == 302 ? "REDIRECT" : "SERVER", error.code);
            assertFalse(error.getMessage().contains(AgnesTestSupport.key())); assertEquals(1, transport.requests.size());
        }
    }
    @Test public void timeoutsAndTlsErrorsNeverFallback() throws Exception {
        AgnesTransport.Https timeout = new AgnesTransport.Https() { @Override javax.net.ssl.HttpsURLConnection open(java.net.URL url) throws Exception { throw new java.net.SocketTimeoutException("Synthetic timeout"); } };
        assertThrows(java.net.SocketTimeoutException.class, () -> timeout.execute("agnes-cn", AgnesProtocol.request(AgnesTestSupport.messages("q"), false), AgnesTestSupport.key().getBytes(StandardCharsets.UTF_8), new AgnesTransport.Operation(), text -> {}));
        AgnesTransport.Https tls = new AgnesTransport.Https() { @Override javax.net.ssl.HttpsURLConnection open(java.net.URL url) throws Exception { throw new javax.net.ssl.SSLHandshakeException("Synthetic certificate rejection"); } };
        assertThrows(javax.net.ssl.SSLHandshakeException.class, () -> tls.execute("agnes-cn", AgnesProtocol.request(AgnesTestSupport.messages("q"), false), AgnesTestSupport.key().getBytes(StandardCharsets.UTF_8), new AgnesTransport.Operation(), text -> {}));
    }
    @Test public void streamingChunksAndIncompleteStreamValidation() throws Exception {
        String data = "data: {\"choices\":[{\"delta\":{\"role\":\"assistant\",\"content\":\"one\"},\"finish_reason\":null}]}\n\ndata: {\"choices\":[{\"delta\":{\"content\":\"two\"},\"finish_reason\":\"stop\"}]}\n\ndata: [DONE]\n\n";
        List<String> chunks = new ArrayList<>(); AgnesProtocol.Result result = AgnesProtocol.streamResponse(new ByteArrayInputStream(data.getBytes(StandardCharsets.UTF_8)), chunks::add);
        assertEquals("onetwo", result.content); assertEquals(2, chunks.size());
        assertThrows(Exception.class, () -> AgnesProtocol.streamResponse(new ByteArrayInputStream("data: {\"choices\":[{\"delta\":{\"content\":\"partial\"}}]}\n\n".getBytes(StandardCharsets.UTF_8)), text -> {}));
    }
    @Test public void cancellationAndDownloadLimit() throws Exception {
        AgnesTestSupport.MockTransport transport = new AgnesTestSupport.MockTransport(); AgnesTransport.Operation operation = new AgnesTransport.Operation(); operation.cancel();
        assertThrows(IllegalStateException.class, () -> transport.execute("agnes-cn", AgnesProtocol.request(AgnesTestSupport.messages("q"), false), AgnesTestSupport.key().getBytes(StandardCharsets.UTF_8), operation, text -> {})); assertEquals(0, transport.requests.size());
        assertThrows(IOException.class, () -> AgnesProtocol.readBounded(new ByteArrayInputStream(new byte[AgnesProtocol.MAX_RESPONSE_BYTES + 1])));
    }
}
