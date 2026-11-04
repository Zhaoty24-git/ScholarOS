package com.scholaros.app;

import android.Manifest;
import android.content.pm.PackageManager;
import android.content.pm.ActivityInfo;
import android.os.SystemClock;
import android.view.KeyEvent;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.Assert.*;

/** Runs on an actual emulator with airplane mode enabled; no Python server. */
@RunWith(AndroidJUnit4.class)
public abstract class DeviceFixture {
    protected ActivityScenario<MainActivity> scenario;
    @Before public void launch() throws Exception {
        AgnesTestSupport.requireSyntheticDevice();
        new AgnesCredentials(InstrumentationRegistry.getInstrumentation().getTargetContext()).clear();
        scenario = ActivityScenario.launch(MainActivity.class);
        waitFor("document.body.textContent.includes('让学习，井然有序。')");
    }
    @After public void close() throws Exception { if (scenario != null) scenario.close(); new AgnesCredentials(InstrumentationRegistry.getInstrumentation().getTargetContext()).clear(); }
    protected String js(String expression) throws Exception {
        AtomicReference<String> result = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);
        scenario.onActivity(a -> a.getBridge().getWebView().evaluateJavascript(expression, value -> { result.set(value); done.countDown(); }));
        assertTrue("WebView evaluation timed out", done.await(10, TimeUnit.SECONDS));
        return result.get();
    }
    protected void waitFor(String expression) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + 15000;
        do {
            if ("true".equals(js(expression))) return;
            SystemClock.sleep(100);
        } while (SystemClock.elapsedRealtime() < deadline);
        fail("Offline UI condition failed: " + expression);
    }
    protected void page(String route) throws Exception {
        js("location.hash='" + route + "'");
        waitFor("document.querySelector('nav [aria-current=page]').textContent.includes('" +
            (route.equals("ai") ? "AI 助手" : route.equals("courses") ? "课程" : route.equals("assignments") ? "作业" : route.equals("notices") ? "通知" : route.equals("materials") ? "资料" : "设置") + "')");
    }
}
