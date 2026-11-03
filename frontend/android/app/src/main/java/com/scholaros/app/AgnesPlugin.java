package com.scholaros.app;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.util.Arrays;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

@CapacitorPlugin(name = "AgnesAI")
public class AgnesPlugin extends Plugin {
    private AgnesCredentials credentials;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final ScheduledExecutorService timer = Executors.newSingleThreadScheduledExecutor();
    private AgnesTransport.Operation active;
    private String activeId;
    private long revision;
    // AndroidTest can substitute a synthetic transport; not exposed by the bridge.
    AgnesTransport transport = new AgnesTransport.Https();

    @Override public void load() { credentials = new AgnesCredentials(getContext()); }
    private synchronized JSObject state() {
        return new JSObject().put("configured", credentials.configured()).put("persistent", credentials.persistent())
            .put("provider", credentials.provider()).put("baseUrl", AgnesProtocol.baseUrl(credentials.provider())).put("model", AgnesProtocol.MODEL);
    }
    @PluginMethod public void status(PluginCall call) { call.resolve(state()); }
    private synchronized void stop() {
        revision++;
        if (active != null) active.cancel();
        active = null; activeId = null;
    }
    @PluginMethod public synchronized void configure(PluginCall call) {
        if (!Boolean.TRUE.equals(call.getBoolean("consent"))) { call.reject("配置未确认", "CONSENT"); return; }
        stop();
        try { credentials.save(call.getString("key"), Boolean.TRUE.equals(call.getBoolean("persist")), call.getString("provider")); call.resolve(state()); }
        catch (IllegalArgumentException ex) { call.reject("密钥格式不正确", "KEY_FORMAT"); }
        catch (Exception ex) { call.reject("安全存储不可用，可主动选择仅内存模式", "STORAGE"); }
    }
    @PluginMethod public synchronized void remove(PluginCall call) {
        stop();
        try { credentials.clear(); call.resolve(state()); }
        catch (Exception ex) { call.reject("密钥已停用，清理设备存储时发生错误", "STORAGE"); }
    }
    @PluginMethod public synchronized void cancel(PluginCall call) {
        if (activeId != null && activeId.equals(call.getString("requestId"))) stop();
        call.resolve();
    }
    @PluginMethod public synchronized void send(PluginCall call) {
        if (!Boolean.TRUE.equals(call.getBoolean("consent"))) { call.reject("请先确认隐私与费用说明", "CONSENT"); return; }
        if (active != null) { call.reject("已有请求处理中", "BUSY"); return; }
        if (!credentials.configured()) { call.reject("请先配置密钥", "NO_KEY"); return; }
        final String id = call.getString("requestId");
        if (id == null || !id.matches("[a-zA-Z0-9-]{1,80}")) { call.reject("请求格式不正确", "FORMAT"); return; }
        final org.json.JSONObject request;
        try { request = AgnesProtocol.request(call.getArray("messages"), Boolean.TRUE.equals(call.getBoolean("stream"))); }
        catch (Exception ex) { call.reject("消息格式或长度不正确", "FORMAT"); return; }
        final AgnesTransport.Operation operation = new AgnesTransport.Operation();
        final long started = revision;
        active = operation; activeId = id;
        worker.execute(() -> {
            byte[] key = null;
            final java.util.concurrent.atomic.AtomicBoolean timedOut = new java.util.concurrent.atomic.AtomicBoolean();
            ScheduledFuture<?> timeout = timer.schedule(() -> { timedOut.set(true); operation.cancel(); }, 60, TimeUnit.SECONDS);
            try {
                synchronized (AgnesPlugin.this) { operation.check(); if (revision != started) throw new IllegalStateException("CANCELLED"); key = credentials.read(); }
                final String provider;
                synchronized (AgnesPlugin.this) { operation.check(); provider = credentials.provider(); }
                AgnesProtocol.Result answer = transport.execute(provider, request, key, operation, text -> {
                    synchronized (AgnesPlugin.this) {
                        operation.check(); if (revision != started) throw new IllegalStateException("CANCELLED");
                        notifyListeners("chunk", new JSObject().put("requestId", id).put("text", text));
                    }
                });
                synchronized (AgnesPlugin.this) {
                    operation.check(); if (revision != started) throw new IllegalStateException("CANCELLED");
                    call.resolve(new JSObject().put("content", answer.content).put("truncated", answer.truncated));
                }
            } catch (Exception ex) {
                String code = timedOut.get() ? "TIMEOUT" : operation.cancelled.get() ? "CANCELLED" :
                    ex instanceof AgnesTransport.HttpFailure ? ((AgnesTransport.HttpFailure) ex).code :
                    ex instanceof java.io.IOException && "RESPONSE_LIMIT".equals(ex.getMessage()) ? "RESPONSE_LIMIT" :
                    ex instanceof IllegalStateException && "STORAGE".equals(ex.getMessage()) ? "STORAGE" :
                    ex instanceof IllegalArgumentException || ex instanceof org.json.JSONException ? "FORMAT" : "NETWORK";
                call.reject("AI 请求未完成", code); // No exception, response, URL query, body or headers in logs/errors.
            } finally {
                timeout.cancel(false); if (key != null) Arrays.fill(key, (byte) 0);
                synchronized (AgnesPlugin.this) { if (active == operation) { active = null; activeId = null; } }
            }
        });
    }
    @Override protected void handleOnDestroy() { stop(); credentials.clearMemory(); worker.shutdownNow(); timer.shutdownNow(); }
}
