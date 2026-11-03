package com.scholaros.app;

import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/** Replace the core generic HTTP bridge; only AgnesAI may access the network. */
@CapacitorPlugin(name = "CapacitorHttp")
public class BlockedHttpPlugin extends Plugin {
    private void deny(PluginCall call) { call.reject("通用原生网络接口未开放", "TARGET"); }
    @PluginMethod public void request(PluginCall call) { deny(call); }
    @PluginMethod public void get(PluginCall call) { deny(call); }
    @PluginMethod public void post(PluginCall call) { deny(call); }
    @PluginMethod public void put(PluginCall call) { deny(call); }
    @PluginMethod public void patch(PluginCall call) { deny(call); }
    @PluginMethod public void delete(PluginCall call) { deny(call); }
}
