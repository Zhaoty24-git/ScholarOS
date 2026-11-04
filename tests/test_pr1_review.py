"""Independent PR1 edge regressions; all data and transports are synthetic."""
import asyncio
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_security as fixtures
from backend.app import security, env_manager
from src.security import private_write
from src import attachment_security as downloads
import socket


class ReviewApiTests(unittest.TestCase):
    setUp = fixtures.ApiSecurityTests.setUp

    def test_explicit_trusted_dev_origin_can_cross_local_host_names(self):
        # localhost:5173 -> 127.0.0.1:8000 is cross-site in real browsers.
        headers = {**fixtures.AUTH, "Origin": "http://localhost:5173", "Sec-Fetch-Site": "cross-site"}
        response = self.client.get("/api/settings/status", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")
        del headers["Authorization"]
        self.assertEqual(self.client.get("/api/settings/status", headers=headers).status_code, 401)

    def test_trusted_origin_can_observe_auth_rejection_and_relock(self):
        response = self.client.get("/api/settings/status", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:5173")
        self.assertIn("Origin", response.headers.get("vary", ""))

    def test_unknown_and_public_paths_cannot_hold_write_slots(self):
        async def exercise():
            called = []
            async def app(scope, receive, send): called.append(True)
            async def receive():
                self.fail("Unauthenticated unsafe methods must be rejected before body read")
            async def send(message): pass
            boundary = security.SecurityBoundary(app)
            for path in ["/api/health", "/not-a-route", "/app/"]:
                await boundary({"type": "http", "method": "POST", "path": path, "headers": []}, receive, send)
            self.assertFalse(called)
        asyncio.run(exercise())

    def test_wrong_length_is_rejected_before_side_effects(self):
        async def exercise():
            called, sent = [], []
            async def app(scope, receive, send): called.append(True)
            async def receive(): return {"type": "http.request", "body": b"synthetic", "more_body": False}
            async def send(message): sent.append(message)
            await security.SecurityBoundary(app)({"type": "http", "method": "POST", "path": "/api/settings/local", "headers": [(b"authorization", ("Bearer " + fixtures.TOKEN).encode()), (b"content-length", b"1")]}, receive, send)
            self.assertFalse(called)
            self.assertEqual(sent[0]["status"], 400)
        asyncio.run(exercise())

    def test_duplicate_and_invalid_lengths_are_rejected(self):
        async def exercise():
            async def app(scope, receive, send): self.fail("Invalid headers reached handler")
            async def receive(): self.fail("Invalid headers caused a body read")
            for values in [[b"-1"], [b"bad"], [b"0", b"0"], [b"9" * 5000]]:
                sent = []
                async def send(message): sent.append(message)
                headers = [(b"authorization", ("Bearer " + fixtures.TOKEN).encode())] + [(b"content-length", value) for value in values]
                await security.SecurityBoundary(app)({"type": "http", "method": "POST", "path": "/api/upload", "headers": headers}, receive, send)
                self.assertIn(sent[0]["status"], [400, 413])
        asyncio.run(exercise())

    def test_literal_unicode_separator_survives_unrelated_update(self):
        value = "synthetic\u2028literal"
        env_manager.write_env_incremental({"LEARN_PASSWORD": value})
        env_manager.write_env_incremental({"MAIL_USERNAME": "synthetic"})
        self.assertEqual(env_manager.parse_env_file(self.root / ".env")["LEARN_PASSWORD"], value)

    def test_quoted_and_export_tab_duplicate_keys_removed(self):
        original = "'{}'=old\nexport\t{}=other\n".format("LEARN_PASSWORD", "LEARN_PASSWORD")
        private_write(self.root / ".env", original)
        env_manager.write_env_incremental({"LEARN_PASSWORD": "replacement"})
        text = (self.root / ".env").read_text()
        self.assertNotIn("old", text)
        self.assertNotIn("other", text)
        self.assertEqual(env_manager.parse_env_file(self.root / ".env")["LEARN_PASSWORD"], "replacement")

    def test_legal_secret_whitespace_not_trimmed(self):
        value = "  synthetic significant spaces  "
        env_manager.write_env_incremental({"LEARN_PASSWORD": value})
        self.assertEqual(env_manager.parse_env_file(self.root / ".env")["LEARN_PASSWORD"], value)


class ReviewAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_body_replay_and_handler_failure_release_capacity(self):
        received = []
        async def app(scope, receive, send):
            received.append(await receive())
            raise RuntimeError("synthetic handler failure")
        frames = iter([{"type": "http.request", "body": b"one", "more_body": True}, {"type": "http.request", "body": b"two", "more_body": False}])
        async def receive(): return next(frames)
        async def send(message): pass
        with patch.dict(os.environ, {"SCHOLAROS_API_TOKEN": fixtures.TOKEN}, clear=True):
            with self.assertRaises(RuntimeError):
                await security.SecurityBoundary(app)({"type": "http", "method": "POST", "path": "/api/upload", "headers": [(b"authorization", ("Bearer " + fixtures.TOKEN).encode())]}, receive, send)
        self.assertEqual(received[0]["body"], b"onetwo")
        self.assertFalse(received[0]["more_body"])
        self.assertTrue(security._MUTATIONS.acquire(False))
        self.assertTrue(security._MUTATIONS.acquire(False))
        security._MUTATIONS.release()
        security._MUTATIONS.release()
    async def test_body_deadline_rejects_and_releases_capacity(self):
        sent = []
        async def app(scope, receive, send): self.fail("Timed out body reached handler")
        async def receive(): await asyncio.Event().wait()
        async def send(message): sent.append(message)
        scope = {"type": "http", "method": "POST", "path": "/api/upload", "headers": [(b"authorization", ("Bearer " + fixtures.TOKEN).encode())]}
        with patch.dict(os.environ, {"SCHOLAROS_API_TOKEN": fixtures.TOKEN}, clear=True), patch.object(security, "REQUEST_BODY_TIMEOUT_SECONDS", 0.01):
            await security.SecurityBoundary(app)(scope, receive, send)
        self.assertEqual(sent[0]["status"], 408)
        self.assertTrue(security._MUTATIONS.acquire(False))
        self.assertTrue(security._MUTATIONS.acquire(False))
        security._MUTATIONS.release()
        security._MUTATIONS.release()

    async def test_disconnect_and_cancellation_release_capacity(self):
        async def app(scope, receive, send): self.fail("Handler must not run")
        boundary = security.SecurityBoundary(app)
        scope = {"type": "http", "method": "POST", "path": "/api/upload", "headers": [(b"authorization", ("Bearer " + fixtures.TOKEN).encode())]}
        async def send(message): pass
        with patch.dict(os.environ, {"SCHOLAROS_API_TOKEN": fixtures.TOKEN}, clear=True):
            async def disconnected(): return {"type": "http.disconnect"}
            await boundary(scope, disconnected, send)
            started = asyncio.Event()
            async def pending():
                started.set()
                await asyncio.Event().wait()
            task = asyncio.create_task(boundary(scope, pending, send))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            self.assertTrue(security._MUTATIONS.acquire(False))
            self.assertTrue(security._MUTATIONS.acquire(False))
            security._MUTATIONS.release()
            security._MUTATIONS.release()


class ReviewTransportTests(unittest.TestCase):
    def test_real_local_tls_preserves_sni_host_and_scoped_cookie(self):
        # Synthetic TLS endpoint only: no backend deployment or campus request.
        import http.server
        import ssl
        import subprocess
        import tempfile
        import threading
        import requests
        seen, names = [], []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.headers.get("Host"), self.headers.get("Cookie")))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"synthetic TLS")
            def log_message(self, *args): pass
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cert, key = root / "cert.pem", root / "key.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=" + downloads.LEARN_HOST, "-addext", "subjectAltName=DNS:" + downloads.LEARN_HOST], check=True, capture_output=True)
            server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            context.set_servername_callback(lambda sock, name, ctx: names.append(name))
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                session = requests.Session()
                session.trust_env = False  # synthetic local endpoint, never external
                session.cookies.set("synthetic", "fixture", domain=downloads.LEARN_HOST, secure=True)
                session.cookies.set("unrelated", "must-not-send", domain="attacker.invalid", secure=True)
                prepared = session.prepare_request(requests.Request("GET", "https://" + downloads.LEARN_HOST + "/fixture", headers={"Host": downloads.LEARN_HOST}))
                with downloads._PinnedHTTPSAdapter("127.0.0.1") as adapter:
                    adapter._pool.port = server.server_port  # test-only local port
                    response = adapter.send(prepared, verify=str(cert), proxies={}, timeout=(2, 2))
                    self.assertEqual(response.content, b"synthetic TLS")
                    response.close()
                    # A mismatched certificate identity must fail before HTTP.
                    adapter._pool.close()
                    adapter._pool = downloads.HTTPSConnectionPool("127.0.0.1", port=server.server_port, assert_hostname="wrong.invalid", server_hostname=downloads.LEARN_HOST)
                    with self.assertRaises(requests.exceptions.SSLError):
                        adapter.send(prepared, verify=str(cert), proxies={}, timeout=(2, 2))
                self.assertEqual(seen, [(downloads.LEARN_HOST, "synthetic=fixture")])
                self.assertTrue(all(name == downloads.LEARN_HOST for name in names))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_actual_pool_uses_validated_ip_and_original_tls_identity(self):
        # This exercises the real urllib3 pool and socket selection, not a mock
        # HTTP success. A second DNS lookup may only be for the numeric IP.
        with downloads._PinnedHTTPSAdapter("8.8.8.8") as adapter:
            pool = adapter.get_connection("https://learn.tsinghua.edu.cn/a")
            self.assertEqual(pool.host, "8.8.8.8")
            self.assertEqual(pool.assert_hostname, downloads.LEARN_HOST)
            self.assertEqual(pool.conn_kw["server_hostname"], downloads.LEARN_HOST)
            connection = pool._new_conn()
            with patch("urllib3.util.connection.create_connection") as connect:
                connection._new_conn()
                self.assertEqual(connect.call_args.args[0], ("8.8.8.8", 443))
            with self.assertRaises(downloads.DownloadError):
                adapter.get_connection("https://learn.tsinghua.edu.cn/a", {"https": "http://synthetic-proxy.invalid:8080"})

    def test_configured_proxy_is_refused_not_bypassed(self):
        import requests
        from unittest.mock import Mock
        session = requests.Session()
        session.trust_env = False  # test configuration, no real network
        session.proxies = {"https": "http://synthetic-proxy.invalid:8080"}
        with patch.object(downloads.socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]), patch.object(downloads._PinnedHTTPSAdapter, "send") as send:
            with fixtures.tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(downloads.DownloadError):
                    downloads.download_attachment(session, "https://learn.tsinghua.edu.cn/a", Path(directory), "a.pdf")
                self.assertFalse(list(Path(directory).iterdir()))
            send.assert_not_called()


class ReviewAuthenticationTests(unittest.TestCase):
    def test_matched_pin_only_tests_process_boundary_not_login_success(self):
        import hashlib
        from unittest.mock import Mock
        from src.adapters.learn_adapter import encrypt_password_with_node_sm2
        helper = "synthetic helper fixture"
        secret = "-".join(["synthetic", "input"])
        environment = {"SCHOLAROS_SM2_SHA256": hashlib.sha256(helper.encode()).hexdigest(), "SYNTHETIC_PARENT_CREDENTIAL": "must-not-inherit"}
        with patch.dict(os.environ, environment, clear=True), patch("subprocess.run", return_value=Mock(stdout="synthetic-cipher")) as run:
            self.assertEqual(encrypt_password_with_node_sm2(password=secret, public_key="synthetic", sm2_javascript=helper), "synthetic-cipher")
        kwargs = run.call_args.kwargs
        self.assertEqual(set(kwargs["env"]), {"PATH"})
        self.assertNotIn(secret, " ".join(run.call_args.args[0]))
        self.assertEqual(json.loads(kwargs["input"])["password"], secret)
        self.assertEqual(kwargs["timeout"], 20)

    def test_otp_redirect_never_forwards_body(self):
        from src.security import auth_post
        from unittest.mock import Mock
        session = Mock()
        session.post.return_value.status_code = 307
        with self.assertRaises(ValueError):
            auth_post(session, "https://id.tsinghua.edu.cn/b/doubleAuth/login", data={"synthetic": "fixture"})
        self.assertEqual(session.post.call_count, 1)
        self.assertFalse(session.post.call_args.kwargs["allow_redirects"])
        with self.assertRaises(ValueError):
            auth_post(session, "https://attacker.invalid/", data={})
        self.assertEqual(session.post.call_count, 1)

    def test_expired_or_future_mfa_session_refused(self):
        from src.security import validate_session_age
        for stamp in ["1970-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00", "invalid"]:
            with self.assertRaises(ValueError): validate_session_age({"created_at": stamp})
