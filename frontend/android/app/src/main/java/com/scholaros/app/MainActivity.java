package com.scholaros.app;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override public void onCreate(android.os.Bundle savedInstanceState) {
        registerPlugin(AgnesPlugin.class);
        registerPlugin(BlockedHttpPlugin.class);
        super.onCreate(savedInstanceState);
        // AI uses only its own Bearer header. Do not inherit the core cookie
        // manager's ambient native HTTP cookies or persist server cookies.
        java.net.CookieHandler.setDefault(new java.net.CookieHandler() {
            public java.util.Map<String, java.util.List<String>> get(java.net.URI uri, java.util.Map<String, java.util.List<String>> headers) { return java.util.Collections.emptyMap(); }
            public void put(java.net.URI uri, java.util.Map<String, java.util.List<String>> headers) {}
        });
    }
}
