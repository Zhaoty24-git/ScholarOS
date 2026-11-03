package com.scholaros.app;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class AiUiTest extends DeviceFixture {
    private AgnesTestSupport.MockTransport mock;
    private void configure() throws Exception {
        mock = new AgnesTestSupport.MockTransport();
        scenario.onActivity(a -> ((AgnesPlugin) a.getBridge().getPlugin("AgnesAI").getInstance()).transport = mock);
        page("ai"); waitFor("document.querySelector('#ai-key')!==null");
        assertEquals("true", js("document.querySelector('#ai-provider').value==='agnes-cn' && document.body.textContent.includes('https://api.agnes-ai.cn/v1')"));
        js("document.querySelector('.ai-check input').click()");
        type("ai-key", AgnesTestSupport.key());
        js("document.querySelector('.ai-config').requestSubmit()");
        waitFor("document.body.textContent.includes('密钥已配置')");
        assertEquals("true", js("!document.querySelector('#ai-key') && localStorage.length===0 && sessionStorage.length===0"));
        assertFalse(com.getcapacitor.Logger.shouldLog());
        scenario.onActivity(a -> assertEquals(BlockedHttpPlugin.class, a.getBridge().getPlugin("CapacitorHttp").getPluginClass()));
    }
    private void type(String id, String text) throws Exception {
        js("document.getElementById('" + id + "').focus()");
        InstrumentationRegistry.getInstrumentation().sendStringSync(text);
        waitFor("document.getElementById('" + id + "').value.length>0");
        scenario.onActivity(a -> ((android.view.inputmethod.InputMethodManager) a.getSystemService(android.content.Context.INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(a.getBridge().getWebView().getWindowToken(), 0));
    }
    private void send(String question) throws Exception { type("ai-question", question); js("document.querySelector('.ai-composer').requestSubmit()"); }
    @Test public void aiMultiTurnContextMarkdownAndKeyDeletion() throws Exception {
        configure();
        js("(()=>{const s=document.querySelector('#ai-context');s.value='0';s.dispatchEvent(new Event('change',{bubbles:true}));})()");
        send("Explain power flow"); waitFor("document.querySelector('.ai-messages').textContent.includes('合成 Mock 回答') && !document.querySelector('.ai-messages').getAttribute('aria-busy').includes('true')");
        assertEquals("true", js("!document.querySelector('.ai-messages img') && !document.querySelector('.ai-messages script') && !window.modelScriptRan && !!document.querySelector('.ai-messages pre code')"));
        assertTrue(mock.requests.get(0).getJSONArray("messages").getJSONObject(1).getString("content").contains("不是真实课程"));
        send("Explain the second step"); waitFor("document.querySelectorAll('.ai-assistant').length===2 && document.querySelector('.ai-messages').getAttribute('aria-busy')==='false'");
        assertEquals(4, mock.requests.get(1).getJSONArray("messages").length());
        js("[...document.querySelectorAll('button')].find(b=>b.textContent==='新建会话').click()"); waitFor("document.querySelectorAll('.ai-message').length===0");
        js("(()=>{const s=document.querySelector('#ai-session');s.value=s.options[0].value;s.dispatchEvent(new Event('change',{bubbles:true}));})()"); waitFor("document.querySelectorAll('.ai-assistant').length===2");
        js("[...document.querySelectorAll('button')].find(b=>b.textContent==='清除会话').click()"); waitFor("document.querySelectorAll('.ai-message').length===0");
        js("[...document.querySelectorAll('button')].find(b=>b.textContent==='删除密钥').click()"); waitFor("!!document.querySelector('#ai-key') && !document.body.textContent.includes('密钥已配置')");
        assertEquals("true", js("document.querySelector('#ai-key').value==='' && document.querySelector('.ai-send button').disabled"));
        assertFalse(new AgnesCredentials(InstrumentationRegistry.getInstrumentation().getTargetContext()).configured());
    }
    @Test public void aiStreamingCancelAndSafeErrors() throws Exception {
        configure(); mock.contentType = "text/event-stream"; mock.slowStream = true;
        js("document.querySelector('.ai-send input').click()"); send("Stream a short explanation"); waitFor("document.querySelector('.ai-messages').textContent.includes('合成流式片段')");
        js("[...document.querySelectorAll('button')].find(b=>b.textContent==='取消请求').click()"); waitFor("document.body.textContent.includes('请求已取消')");
        assertEquals("true", js("document.querySelector('.ai-messages').textContent.includes('未完成')"));
        mock.slowStream = false; mock.contentType = "application/json"; mock.status = 401;
        js("[...document.querySelectorAll('button')].find(b=>b.textContent==='新建会话').click()"); send("Synthetic invalid key test"); waitFor("document.body.textContent.includes('密钥无效')");
        assertEquals("true", js("!document.querySelector('.ai-messages').textContent.includes('synthetic-agnes-')"));
    }
}
