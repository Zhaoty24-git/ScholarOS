"""Real Chromium interaction with the independent offline bundle; no API fixture."""
import asyncio
import json


async def exercise(ws_url, origin):
    import websockets
    async with websockets.connect(ws_url, max_size=2**22) as ws:
        counter, requests = 0, []
        async def command(method, params=None):
            nonlocal counter
            counter += 1
            ident = counter
            await ws.send(json.dumps(dict(id=ident, method=method, params=params or {})))
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if m.get("method") == "Network.requestWillBeSent": requests.append(m["params"]["request"]["url"])
                if m.get("id") == ident:
                    assert "error" not in m, "CDP command failed"
                    return m.get("result", {})
        async def js(expression):
            r = await command("Runtime.evaluate", dict(expression=expression, awaitPromise=True, returnByValue=True))
            assert "exceptionDetails" not in r, "Offline UI expression failed"
            return r["result"].get("value")
        async def wait(condition):
            assert await js("new Promise(resolve=>{let end=Date.now()+8000;const check=()=>{if("+condition+")resolve(true);else if(Date.now()>end)resolve(false);else setTimeout(check,25)};check()})"), condition
        async def click(text, selector="button"):
            await js("[...document.querySelectorAll("+json.dumps(selector)+")].find(b=>b.textContent.includes("+json.dumps(text)+")).click()")
        async def page(label):
            await click(label, "nav button"); await wait("document.querySelector('nav [aria-current]').textContent.includes("+json.dumps(label)+")")
        await command("Page.enable"); await command("Network.enable")
        await command("Emulation.setDeviceMetricsOverride", dict(width=390,height=844,deviceScaleFactor=1,mobile=True))
        await command("Page.navigate", dict(url=origin+"/"))
        await wait("document.body.textContent.includes('让学习，井然有序。')")
        assert not await js("!!document.querySelector('input[type=password]')")
        assert await js("document.body.textContent.includes('离线演示模式')")
        print("PASS offline home without token or backend")
        await command("Network.emulateNetworkConditions", dict(offline=True,latency=0,downloadThroughput=0,uploadThroughput=0))
        await page("课程"); await click("电力系统分析"); await wait("document.querySelector('article h1')?.textContent==='电力系统分析'")
        await click("返回"); await wait("!document.querySelector('article')")
        print("PASS course list, detail and back while offline")
        await page("作业"); await click("日期异常示例"); await wait("document.querySelector('article')?.textContent.includes('截止时间格式异常')")
        await click("返回"); await wait("!document.querySelector('article')")
        await click("反馈系统阅读笔记"); await wait("document.querySelector('article')?.textContent.includes('截止时间待定')")
        await click("返回"); await wait("!document.querySelector('article')")
        await click("电力网络基础回顾"); await wait("document.querySelector('article')?.textContent.includes('已提交（演示）')")
        await click("返回"); await wait("!document.querySelector('article')")
        await click("加载更多"); await wait("document.querySelectorAll('.task-row').length===16")
        print("PASS assignment details, invalid/missing dates, submitted and long list")
        await page("通知"); await click("实验准备事项"); await wait("document.querySelector('article h1')?.textContent==='实验准备事项'")
        print("PASS notice list and detail")
        await page("资料"); assert await js("document.querySelector('main').textContent.includes('未实现阅读') && !document.querySelector('main button')")
        print("PASS honest unsupported material operations")
        await page("设置"); assert await js("document.querySelector('main').textContent.includes('未连接') && document.querySelector('main').textContent.includes('0.2.0-dev')")
        await js("(()=>{const s=document.querySelector('select');s.value='dark';s.dispatchEvent(new Event('change',{bubbles:true}));})()")
        await wait("!!document.querySelector('.theme-dark')")
        assert await js("document.documentElement.scrollWidth<=innerWidth")
        await command("Emulation.setDeviceMetricsOverride", dict(width=844,height=390,deviceScaleFactor=1,mobile=True))
        await wait("innerWidth>innerHeight && document.documentElement.scrollWidth<=innerWidth")
        await command("Emulation.setDeviceMetricsOverride", dict(width=390,height=844,deviceScaleFactor=1,mobile=True))
        print("PASS settings, dark mode and portrait/landscape layout")
        assert all(u.startswith(origin+"/") and "/api/" not in u for u in requests), "Unexpected network/API request"
        assert await js("localStorage.length===0 && sessionStorage.length===0")
        print("PASS zero API/external requests or persisted credentials")
        print("offline_browser_scenarios=7 passed=7 failed=0 skipped=0")
