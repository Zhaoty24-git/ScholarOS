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

/** Offline workbench remains usable even though AI now has INTERNET permission. */
@RunWith(AndroidJUnit4.class)
public class OfflineSmokeTest extends DeviceFixture {
    @Test public void launchWithoutNetworkOrCredentials() throws Exception {
        assertEquals(PackageManager.PERMISSION_GRANTED, InstrumentationRegistry.getInstrumentation().getTargetContext().checkSelfPermission(Manifest.permission.INTERNET));
        waitFor("document.body.textContent.includes('离线演示模式') && !document.querySelector('input[type=password]')");
        assertEquals("true", js("location.origin==='https://localhost' && performance.getEntriesByType('resource').every(r=>new URL(r.name).origin===location.origin)"));
        assertEquals("true", js("document.querySelector('meta[http-equiv=\"Content-Security-Policy\"]').content.includes(\"connect-src 'none'\")"));
    }
    @Test public void courseDetailAndNativeBack() throws Exception {
        page("courses");
        js("[...document.querySelectorAll('button')].find(b=>b.textContent.includes('电力系统分析')).click()");
        waitFor("document.querySelector('article h1')?.textContent==='电力系统分析'");
        InstrumentationRegistry.getInstrumentation().sendKeyDownUpSync(KeyEvent.KEYCODE_BACK);
        waitFor("location.hash==='#courses' && !document.querySelector('article')");
    }
    @Test public void assignmentDetailsAndLongList() throws Exception {
        page("assignments");
        js("document.querySelector('[data-testid=task-invalid]').click()");
        waitFor("document.querySelector('article')?.textContent.includes('截止时间格式异常')");
        js("document.querySelector('button.back').click()");
        waitFor("!document.querySelector('article')");
        js("document.querySelector('[data-testid=task-undated]').click()");
        waitFor("document.querySelector('article')?.textContent.includes('截止时间待定')");
        js("document.querySelector('button.back').click()");
        waitFor("!document.querySelector('article')");
        js("document.querySelector('[data-testid=task-submitted]').click()");
        waitFor("document.querySelector('article')?.textContent.includes('已提交（演示）')");
        js("document.querySelector('button.back').click()");
        waitFor("!document.querySelector('article')");
        js("document.querySelector('.load-more').click()");
        waitFor("document.querySelectorAll('.task-row').length===16");
    }
    @Test public void noticesMaterialsSettingsAndRotation() throws Exception {
        page("notices");
        js("document.querySelector('main .list-row').click()");
        waitFor("document.querySelector('article h1')?.textContent==='实验准备事项'");
        page("materials");
        waitFor("document.querySelector('main').textContent.includes('未实现阅读') && !document.querySelector('main button')");
        page("settings");
        waitFor("document.querySelector('main').textContent.includes('0.2.0-dev') && document.querySelector('main').textContent.includes('未连接')");
        js("(()=>{const s=document.querySelector('select');s.value='dark';s.dispatchEvent(new Event('change',{bubbles:true}));})()");
        waitFor("!!document.querySelector('.theme-dark')");
        scenario.onActivity(a -> a.setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE));
        waitFor("innerWidth>innerHeight && document.documentElement.scrollWidth<=innerWidth");
        scenario.onActivity(a -> a.setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT));
        waitFor("innerHeight>innerWidth && document.documentElement.scrollWidth<=innerWidth");
    }
}
