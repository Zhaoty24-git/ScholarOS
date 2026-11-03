"""Chromium UI smoke against a local synthetic HTTP fixture, never the backend.

Run after frontend build: python tests/browser_security_smoke.py
Uses installed Chromium and websockets (already provided by uvicorn[standard]).
"""
import argparse
import asyncio
import http.server
import json
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request

import websockets

ROOT = Path(__file__).resolve().parents[1]
PHASE = "initialization"

FIXTURE_TOKEN = "".join(["synthetic-browser-", "x" * 40])


class Fixture(http.server.BaseHTTPRequestHandler):
    static_root = ROOT / "frontend/dist"
    base_path = "/app/"
    revoked = False
    api_calls = 0
    def log_message(self, *args): pass
    def do_GET(self):
        if self.path.startswith("/api/"):
            type(self).api_calls += 1
            valid = self.headers.get("Authorization") == "Bearer " + FIXTURE_TOKEN
            self.send_response(200 if valid and not type(self).revoked else 401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ready", "fields": {}, "items": [], "stats": {}}).encode())
            return
        relative = self.path.split("?", 1)[0].removeprefix(type(self).base_path)
        file = (type(self).static_root / (relative or "index.html")).resolve()
        if not file.is_relative_to(type(self).static_root) or not file.is_file():
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/javascript" if file.suffix == ".js" else "text/css" if file.suffix == ".css" else "text/html")
        self.end_headers()
        self.wfile.write(file.read_bytes())


async def exercise(ws_url, origin):
    global PHASE
    async with websockets.connect(ws_url, max_size=2**22) as ws:
        counter = 0
        async def command(method, params=None):
            nonlocal counter
            counter += 1
            ident = counter
            await ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if message.get("id") == ident:
                    if "error" in message: raise AssertionError("CDP command failed")
                    return message.get("result", {})
        async def js(expression):
            result = await command("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
            if "exceptionDetails" in result: raise AssertionError("Browser expression failed")
            return result["result"].get("value")
        async def wait(condition):
            assert await js("new Promise(resolve => { const end = Date.now()+8000; const check=()=>{ if (" + condition + ") resolve(true); else if(Date.now()>end) resolve(false); else setTimeout(check,25); }; check(); })"), "Browser state timed out"
        async def login(value):
            # Trusted browser input avoids React controlled-input races caused
            # by manually assigning .value and dispatching an untrusted event.
            await wait("document.querySelector('button[type=submit]') && !document.querySelector('button[type=submit]').disabled")
            await js("(()=>{const input=document.querySelector('input[type=password]'); input.focus(); input.select();})()")
            await command("Input.insertText", {"text": value})
            await js("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
            await js("document.querySelector('form').requestSubmit()")
        await command("Page.enable")
        await command("Page.bringToFront")
        PHASE = "initial locked page"
        await command("Page.navigate", {"url": origin + "/app/"})
        await wait("document.querySelector('input[type=password]') !== null")
        assert Fixture.api_calls == 0
        print("PASS initial locked page makes no API requests")
        PHASE = "invalid token"
        await login("synthetic-wrong")
        await wait("document.querySelector('[role=alert]') !== null")
        assert not await js("document.body.textContent.includes('锁定会话')")
        print("PASS invalid token stays locked")
        PHASE = "authorized login"
        await login(FIXTURE_TOKEN)
        await wait("document.body.textContent.includes('锁定会话')")
        await wait("document.body.textContent.includes('学习概览')")
        assert not await js("JSON.stringify(localStorage).includes(" + json.dumps(FIXTURE_TOKEN) + ") || JSON.stringify(sessionStorage).includes(" + json.dumps(FIXTURE_TOKEN) + ")")
        print("PASS authorized business UI and no persistent token")
        PHASE = "manual lock"
        await js("[...document.querySelectorAll('button')].find(b=>b.textContent==='锁定会话').click()")
        await wait("document.querySelector('input[type=password]') !== null")
        assert await js("document.querySelector('input[type=password]').value === ''")
        print("PASS manual lock clears the credential form")
        await login(FIXTURE_TOKEN)
        await wait("document.body.textContent.includes('锁定会话')")
        PHASE = "page reload"
        await command("Page.reload")
        await wait("document.querySelector('input[type=password]') !== null")
        print("PASS reload requires reauthorization")
        await login(FIXTURE_TOKEN)
        await wait("document.body.textContent.includes('锁定会话')")
        PHASE = "backend revocation"
        Fixture.revoked = True
        await js("[...document.querySelectorAll('nav button')].find(b=>b.textContent.includes('偏好设置')).click()")
        await wait("document.querySelector('input[type=password]') !== null")
        print("PASS backend rejection relocks the UI")
        print("browser_scenarios=6 passed=6 failed=0 skipped=0")


def main():
    global PHASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", help="Explicit browser executable, e.g. google-chrome on GitHub runners")
    parser.add_argument("--dist", type=Path, default=ROOT / "frontend/dist")
    parser.add_argument("--offline", action="store_true", help="Exercise the independent Android offline bundle")
    args = parser.parse_args()
    Fixture.static_root = args.dist.resolve()
    Fixture.base_path = "/" if args.offline else "/app/"
    candidates = [args.browser] if args.browser else ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
    chromium = next((path for name in candidates if (path := shutil.which(name))), None)
    if not chromium: raise RuntimeError("Chromium required; browser checks were not run")
    if not (Fixture.static_root / "index.html").exists(): raise RuntimeError("Build frontend first")
    PHASE = "browser version probe"
    print("browser_version=" + subprocess.check_output([chromium, "--version"], text=True).strip())
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="scholaros-browser-") as directory:
            profile = Path(directory)
            PHASE = "browser startup"
            process = subprocess.Popen([chromium, "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run", "--no-default-browser-check", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1", "--remote-debugging-port=0", "--user-data-dir=" + str(profile), "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 15
                while not (profile / "DevToolsActivePort").exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError(f"Browser could not start; exit_code={process.poll()}")
                    time.sleep(0.05)
                PHASE = "DevTools connection"
                port = (profile / "DevToolsActivePort").read_text().splitlines()[0]
                with urllib.request.urlopen("http://127.0.0.1:" + port + "/json/list", timeout=3) as response:
                    target = next(t for t in json.load(response) if t["type"] == "page")
                scenario = exercise
                if args.offline:
                    from browser_offline_smoke import exercise as scenario
                asyncio.run(scenario(target["webSocketDebuggerUrl"], "http://127.0.0.1:" + str(server.server_port)))
            finally:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # The public job page exposes annotations even when logs need login.
        # Only synthetic scenarios run here; redact local DevTools capabilities.
        message = re.sub(r"ws://\S+", "[local-devtools]", str(exc))[:500]
        annotation = f"{PHASE}: {type(exc).__name__}: {message}"
        annotation = annotation.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error title=Browser security smoke::" + annotation, flush=True)
        raise
