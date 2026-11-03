"""Offline regressions. Synthetic configuration only; never load the real .env.

Run: python -m unittest discover -s tests -p 'test_security.py' -v
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

# Import the app with dotenv disabled and an empty environment. All later file
# and settings requests use a private temporary root, never the checkout data.
with patch.dict(os.environ, {}, clear=True), patch("dotenv.load_dotenv"):
    from backend.app import main as api
from fastapi.testclient import TestClient
from backend.app import env_manager
from backend.app.settings import BackendSettings
from backend.app.security import SecurityBoundary, public_payload
from src.security import private_write
from src.security import validate_auth_url
from src import attachment_security as downloads
from src.adapters.learn_adapter import encrypt_password_with_node_sm2
from src.adapters.base_adapter import AdapterError, RawPayload
from scripts.export_attachments import safe_filename, build_learn_target_name, resolve_download_url

TOKEN = "".join(["synthetic-access-", "x" * 40])
SYNTHETIC = "synthetic"
AUTH = {"Authorization": "Bearer " + TOKEN}


class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        config = BackendSettings(project_root=self.root)
        self.enterContext(patch.dict(os.environ, {"SCHOLAROS_API_TOKEN": TOKEN}, clear=True))
        self.enterContext(patch.object(env_manager, "settings", config))
        self.enterContext(patch.object(api, "settings", config))
        self.enterContext(patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")))
        self.client = TestClient(api.app, base_url="http://localhost")

    def test_all_sensitive_routes_require_auth(self):
        for route in api.app.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/api/") or path == "/api/health":
                continue
            path = path.replace("{job_id}", "synthetic")
            method = "POST" if "POST" in getattr(route, "methods", ()) else "GET"
            with self.subTest(path=path):
                self.assertEqual(self.client.request(method, path).status_code, 401)
        self.assertFalse((self.root / ".env").exists())

    def test_missing_token_fails_closed(self):
        with patch.dict(os.environ, {"SCHOLAROS_API_TOKEN": ""}):
            self.assertEqual(self.client.get("/api/settings/status", headers=AUTH).status_code, 503)

    def test_public_health_is_minimal(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})

    def test_token_not_accepted_from_cookie_or_query(self):
        self.assertEqual(self.client.get("/api/settings/status", params={"token": TOKEN}, headers={"Cookie": "synthetic=" + TOKEN}).status_code, 401)

    def test_authorized_sync_dry_run_preserved(self):
        response = self.client.post("/api/sync/run", headers=AUTH, json={"channel": "learn", "allow_network": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "queued")

    def test_owner_authorization_and_cache_headers(self):
        response = self.client.get("/api/settings/status", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_docs_also_require_auth(self):
        for path in ["/docs", "/redoc", "/openapi.json"]:
            self.assertEqual(self.client.get(path).status_code, 401)

    def test_unhandled_errors_neither_echo_nor_log_details(self):
        with patch.object(api, "write_env_incremental", side_effect=RuntimeError("synthetic-private-marker")):
            with self.assertNoLogs(level="ERROR"):
                response = self.client.post("/api/settings/local", headers=AUTH, json={"learn_username": "synthetic"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("synthetic-private-marker", response.text)

    def test_authorized_settings_write_roundtrip(self):
        value = "synthetic # quote ' slash \\ ${NOT_EXPANDED}"
        response = self.client.post("/api/settings/local", headers=AUTH, json={"learn_password": value})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(env_manager.parse_env_file(self.root / ".env")["LEARN_PASSWORD"], value)
        self.assertEqual((self.root / ".env").stat().st_mode & 0o777, 0o600)
        self.assertNotIn(value, response.text)
        self.assertNotIn(str(self.root), response.text)

    def test_newline_injection_is_atomic(self):
        for value in ["safe\nINJECTED=1", "safe\rINJECTED=1", "nul\x00"]:
            with self.subTest(value=repr(value)):
                response = self.client.post("/api/settings/local", headers=AUTH, json={"learn_password": value})
                self.assertEqual(response.status_code, 400)
                self.assertFalse((self.root / ".env").exists())
                self.assertNotIn("INJECTED", response.text)

    def test_duplicate_definitions_replaced(self):
        private_write(self.root / ".env", "LEARN_PASSWORD=old\nexport LEARN_PASSWORD=other\n")
        env_manager.write_env_incremental({"LEARN_PASSWORD": "new"})
        self.assertEqual(env_manager.parse_env_file(self.root / ".env")["LEARN_PASSWORD"], "new")
        self.assertEqual((self.root / ".env").read_text().count("LEARN_PASSWORD="), 1)

    def test_existing_multiline_config_not_partially_rewritten(self):
        original = "{}='synthetic\ncontinuation'\n".format("LEARN_PASSWORD")
        private_write(self.root / ".env", original)
        with self.assertRaises(ValueError):
            env_manager.write_env_incremental({"LEARN_PASSWORD": "replacement"})
        self.assertEqual((self.root / ".env").read_text(), original)

    def test_symlink_config_refused(self):
        outside = self.root / "private"
        outside.write_text("unchanged")
        (self.root / ".env").symlink_to(outside)
        self.assertEqual(self.client.post("/api/settings/local", headers=AUTH, json={"learn_username": "synthetic"}).status_code, 400)
        self.assertEqual(outside.read_text(), "unchanged")

    def test_credential_import_disabled_without_reading(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("Must not read credential files")):
            response = self.client.post("/api/settings/bootstrap", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "blocked")

    def test_explicit_credential_import_uses_only_temp_fixture(self):
        (self.root / "网络学堂账号和密码.txt").write_text("username: synthetic-user\npassword: synthetic-pass\n")
        with patch.dict(os.environ, {"SCHOLAROS_ALLOW_CREDENTIAL_IMPORT": "1"}):
            response = self.client.post("/api/settings/bootstrap", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(env_manager.parse_env_file(self.root / ".env")["LEARN_USERNAME"], "synthetic-user")
        self.assertNotIn("synthetic-pass", response.text)

    def test_concurrent_config_updates_are_preserved(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(env_manager.write_env_incremental, update) for update in [{"LEARN_USERNAME": "synthetic-user"}, {"MAIL_USERNAME": "synthetic-mail"}]]
            for future in futures: future.result()
        values = env_manager.parse_env_file(self.root / ".env")
        self.assertEqual(values["LEARN_USERNAME"], "synthetic-user")
        self.assertEqual(values["MAIL_USERNAME"], "synthetic-mail")

    def test_origin_check_independent_of_auth(self):
        for origin in ["https://attacker.invalid", "null", "http://localhost:8000.attacker.invalid"]:
            self.assertEqual(self.client.post("/api/settings/local", headers={**AUTH, "Origin": origin}, json={}).status_code, 403)
        self.assertEqual(self.client.post("/api/settings/local", headers={"Origin": "http://localhost:8000"}, json={}).status_code, 401)

    def test_trusted_preflight_and_cors(self):
        response = self.client.options("/api/settings/local", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Authorization,Content-Type"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")
        self.assertNotIn("access-control-allow-credentials", response.headers)
        self.assertEqual(self.client.options("/api/settings/local", headers={"Origin": "https://attacker.invalid", "Access-Control-Request-Method": "POST"}).status_code, 403)

    def test_host_and_fetch_metadata(self):
        self.assertEqual(self.client.get("/api/health", headers={"Host": "attacker.invalid"}).status_code, 400)
        self.assertEqual(self.client.post("/api/settings/local", headers={**AUTH, "Sec-Fetch-Site": "cross-site"}, json={}).status_code, 403)

    def test_validation_does_not_echo_input(self):
        response = self.client.post("/api/settings/local", headers=AUTH, json={"llm_timeout": "synthetic-private-marker"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("synthetic-private-marker", response.text)

    def test_valid_upload(self):
        response = self.client.post("/api/upload", headers=AUTH, files={"file": ("../../sample.md", b"synthetic material", "text/markdown")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "synthetic material")
        self.assertFalse((self.root / "sample.md").exists())

    def test_upload_limit(self):
        response = self.client.post("/api/upload", headers=AUTH, files={"file": ("sample.md", b"x" * (20 * 1024 * 1024 + 1))})
        self.assertEqual(response.status_code, 413)

    def test_declared_body_limit(self):
        response = self.client.post("/api/upload", headers={**AUTH, "Content-Length": str(22 * 1024 * 1024)}, content=b"")
        self.assertEqual(response.status_code, 413)

    def test_chunked_body_limit_before_handler(self):
        called = []
        async def downstream(scope, receive, send):
            called.append(True)
        app = SecurityBoundary(downstream)
        messages = iter([{"type": "http.request", "body": b"x" * (11 * 1024 * 1024), "more_body": True}, {"type": "http.request", "body": b"x" * (11 * 1024 * 1024), "more_body": False}])
        sent = []
        async def receive(): return next(messages)
        async def send(message): sent.append(message)
        asyncio.run(app({"type": "http", "path": "/api/upload", "method": "POST", "headers": [(b"authorization", ("Bearer " + TOKEN).encode())]}, receive, send))
        self.assertEqual(sent[0]["status"], 413)
        self.assertFalse(called)

    def test_debug_output_redacted(self):
        with patch.object(api, "debug_sync_errors", return_value={"status": "ready", "collector_log_errors": ["synthetic-private-marker"], "path": str(self.root), "nested": {"detail": "synthetic-private-marker", "stdout": "synthetic-private-marker"}}):
            response = self.client.get("/api/debug/sync-errors", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("synthetic-private-marker", response.text)
        self.assertNotIn(str(self.root), response.text)

    def test_absolute_citations_and_parser_errors_redacted(self):
        payload = public_payload({"source_file": "/private/user/course.pdf", "citation": "C:\\Users\\private\\course.pdf", "error": "synthetic-private-marker"})
        self.assertEqual(payload["source_file"], "course.pdf")
        self.assertEqual(payload["citation"], "course.pdf")
        self.assertNotIn("private", json.dumps(payload))

    def test_mutation_concurrency_limit(self):
        from backend.app import security
        self.assertTrue(security._MUTATIONS.acquire(False))
        self.assertTrue(security._MUTATIONS.acquire(False))
        try:
            self.assertEqual(self.client.post("/api/settings/local", headers=AUTH, json={}).status_code, 429)
        finally:
            security._MUTATIONS.release()
            security._MUTATIONS.release()
        self.assertEqual(self.client.post("/api/sync/run", headers=AUTH, json={}).status_code, 200)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.enterContext(patch.object(downloads.socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]))
        self.response = Mock(status_code=200, headers={"Content-Type": "application/pdf"})
        self.response.iter_content.return_value = [b"synthetic content"]
        self.response.__enter__ = Mock(return_value=self.response)
        self.response.__exit__ = Mock(return_value=False)
        self.session = Mock()
        self.session.get.return_value = self.response

    def download(self, filename="sample.pdf", url="https://learn.tsinghua.edu.cn/file.pdf"):
        return downloads.download_attachment(self.session, url, self.root, filename, headers={"X-XSRF-TOKEN": "synthetic"})

    def test_valid_download_bounded_request(self):
        path, count, mime = self.download()
        self.assertEqual(path.read_bytes(), b"synthetic content")
        self.assertEqual(count, 17)
        self.assertEqual(mime, "application/pdf")
        self.assertFalse(self.session.get.call_args.kwargs["allow_redirects"])
        self.assertTrue(self.session.get.call_args.kwargs["stream"])
        self.assertEqual(self.session.get.call_args.kwargs["timeout"], (5, 15))
        self.assertTrue(self.session.get.call_args.kwargs["verify"])

    def test_untrusted_urls_never_receive_session(self):
        for url in ["http://learn.tsinghua.edu.cn/a", "https://127.0.0.1/a", "https://169.254.169.254/a", "https://learn.tsinghua.edu.cn.attacker.invalid/a", "https://learn.tsinghua.edu.cn@attacker.invalid/a", "https://user@learn.tsinghua.edu.cn/a", "file:///etc/passwd", "https://learn.tsinghua.edu.cn:444/a", "https://learn.tsinghua.edu.cn/\\evil", "https://learn.tsinghua.edu.cn/\na"]:
            with self.subTest(url=url), self.assertRaises(downloads.DownloadError): self.download(url=url)
        self.session.get.assert_not_called()

    def test_redirects_refused_without_forwarding(self):
        for code in [301, 302, 303, 307, 308]:
            self.response.status_code = code
            self.response.headers = {"Location": "http://169.254.169.254/private"}
            with self.assertRaises(downloads.DownloadError): self.download()
        self.assertEqual(self.session.get.call_count, 5)
        self.assertFalse(list(self.root.iterdir()))

    def test_private_dns_refused(self):
        with patch.object(downloads.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(downloads.DownloadError): self.download()
        self.session.get.assert_not_called()

    def test_declared_download_limit(self):
        self.response.headers = {"Content-Length": str(downloads.MAX_DOWNLOAD_BYTES + 1)}
        with self.assertRaises(downloads.DownloadError): self.download()
        self.assertFalse(list(self.root.iterdir()))

    def test_encoded_response_refused_before_decompression(self):
        self.response.headers = {"Content-Encoding": "gzip"}
        with self.assertRaises(downloads.DownloadError): self.download()
        self.response.iter_content.assert_not_called()

    def test_streamed_download_limit_cleanup(self):
        with patch.object(downloads, "MAX_DOWNLOAD_BYTES", 3):
            with self.assertRaises(downloads.DownloadError): self.download()
        self.assertFalse(list(self.root.iterdir()))

    def test_total_download_timeout(self):
        with patch.object(downloads.time, "monotonic", side_effect=[0, 121]):
            with self.assertRaises(downloads.DownloadError): self.download()
        self.assertFalse(list(self.root.iterdir()))

    def test_timeout_errors_do_not_echo_urls(self):
        self.session.get.side_effect = TimeoutError("synthetic-private-marker")
        with self.assertRaises(downloads.DownloadError) as caught: self.download()
        self.assertNotIn("synthetic-private-marker", str(caught.exception))

    def test_traversal_and_symlink_cannot_overwrite(self):
        for name in ["../outside", "..", "/tmp/outside", "a/b", "a\\b"]:
            with self.assertRaises(downloads.DownloadError): self.download(filename=name)
        outside = self.root / "outside"
        outside.write_bytes(b"unchanged")
        (self.root / "sample.pdf").symlink_to(outside)
        path, _, _ = self.download()
        self.assertNotEqual(path.name, "sample.pdf")
        self.assertEqual(outside.read_bytes(), b"unchanged")

    def test_candidate_and_filename_sanitization(self):
        self.assertEqual(resolve_download_url("//attacker.invalid/a.pdf", "https://learn.tsinghua.edu.cn"), "")
        self.assertEqual(resolve_download_url("/a.pdf", "https://learn.tsinghua.edu.cn"), "https://learn.tsinghua.edu.cn/a.pdf")
        for name in ["..", "../a.pdf", "a\\b.pdf", "\x00x.pdf"]:
            filename = build_learn_target_name({"record_raw_id": "../../synthetic"}, safe_filename(name))
            self.assertNotIn("/", filename)
            self.assertNotIn("\\", filename)


class CredentialAndHygieneTests(unittest.TestCase):
    def test_auth_destinations_are_fixed_https_hosts(self):
        for url in ["https://id.tsinghua.edu.cn/f/login", "https://auth.cic.tsinghua.edu.cn/f/login"]:
            self.assertEqual(validate_auth_url(url), url)
        for url in ["https://id.tsinghua.edu.cn.attacker.invalid/login", "http://id.tsinghua.edu.cn/login", "https://user@id.tsinghua.edu.cn/login", "https://127.0.0.1/login"]:
            with self.assertRaises(ValueError): validate_auth_url(url)

    def test_no_plaintext_password_fallback(self):
        from src.adapters.learn_adapter import LearnAdapter
        from src.adapters.jwch_adapter import JwchAdapter
        for adapter in [LearnAdapter(), JwchAdapter()]:
            with self.assertRaises(AdapterError):
                adapter._prepare_password("https://id.tsinghua.edu.cn/f/login", "<html></html>")

    def test_credential_post_redirect_is_blocked(self):
        from src.adapters.learn_adapter import LearnAdapter
        from src.adapters.base_adapter import AdapterConfig
        config = AdapterConfig(source="learn", base_url="https://learn.tsinghua.edu.cn", username=SYNTHETIC, password=SYNTHETIC)
        adapter = LearnAdapter(config)
        adapter._session = Mock()
        adapter._session.get.return_value = Mock(url="https://id.tsinghua.edu.cn/f/login", text='<form method="post" action="/submit"><input name="i_user"><input name="i_pass"></form>')
        adapter._session.post.return_value = Mock(status_code=307)
        with patch.object(adapter, "_prepare_password", return_value=SYNTHETIC), patch("src.adapters.learn_adapter.load_trusted_device_fields", return_value={}):
            with self.assertRaises(AdapterError): adapter._login_with_password()
        self.assertFalse(adapter._session.post.call_args.kwargs["allow_redirects"])
        self.assertEqual(adapter._session.get.call_count, 1)

    def test_scoped_session_roundtrip_and_legacy_refusal(self):
        import requests
        from scripts import probe_learn_double_auth as probe
        with tempfile.TemporaryDirectory() as directory, patch.object(probe, "SESSION_PATH", Path(directory) / "session.json"):
            session = requests.Session()
            session.cookies.set("synthetic", SYNTHETIC, domain="id.tsinghua.edu.cn", path="/b")
            probe.save_session(session, auth_url="https://id.tsinghua.edu.cn/f/login", auth_html="synthetic")
            adapter = Mock()
            adapter._build_session.return_value = requests.Session()
            restored, _ = probe.load_session(adapter)
            cookie = next(iter(restored.cookies))
            self.assertEqual(cookie.domain, "id.tsinghua.edu.cn")
            self.assertEqual(cookie.path, "/b")
            self.assertTrue(cookie.secure)
            private_write(probe.SESSION_PATH, json.dumps({"cookies": {"synthetic": SYNTHETIC}}))
            with self.assertRaises(SystemExit): probe.load_session(adapter)

    def test_info_cookie_import_cannot_widen_domain(self):
        import requests
        from src.adapters.jwch_adapter import JwchAdapter
        from src.adapters.base_adapter import AdapterConfig
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cookies.json"
            config = AdapterConfig(source="jwch", extra={"info_cookie_path": str(path)})
            adapter = JwchAdapter(config, session=requests.Session())
            private_write(path, json.dumps([{"name": SYNTHETIC, "value": SYNTHETIC, "domain": ".tsinghua.edu.cn"}]))
            with self.assertRaises(AdapterError): adapter._load_info_cookies()
            self.assertEqual(len(adapter._session.cookies), 0)
            private_write(path, json.dumps({SYNTHETIC: SYNTHETIC}))
            adapter._load_info_cookies()
            cookie = next(iter(adapter._session.cookies))
            self.assertEqual(cookie.domain, "info.tsinghua.edu.cn")
            self.assertTrue(cookie.secure)

    def test_unpinned_remote_code_never_executes(self):
        with patch.dict(os.environ, {}, clear=True), patch("subprocess.run") as run:
            with self.assertRaises(AdapterError):
                encrypt_password_with_node_sm2(password=SYNTHETIC, public_key="synthetic", sm2_javascript="untrusted()")
            run.assert_not_called()

    def test_pin_mismatch_never_executes(self):
        with patch.dict(os.environ, {"SCHOLAROS_SM2_SHA256": "0" * 64}), patch("subprocess.run") as run:
            with self.assertRaises(AdapterError):
                encrypt_password_with_node_sm2(password=SYNTHETIC, public_key="synthetic", sm2_javascript="untrusted()")
            run.assert_not_called()

    def test_private_session_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private_write(root / "session.json", "synthetic")
            self.assertEqual((root / "session.json").stat().st_mode & 0o777, 0o600)
            (root / "link").symlink_to(root / "session.json")
            with self.assertRaises(ValueError): private_write(root / "link", "changed")
            self.assertEqual((root / "session.json").read_text(), "synthetic")

    def test_failed_atomic_write_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "private.json"
            private_write(target, "original")
            with patch("src.security.os.replace", side_effect=OSError("synthetic")):
                with self.assertRaises(OSError): private_write(target, "changed")
            self.assertEqual(target.read_text(), "original")
            self.assertEqual([p.name for p in target.parent.iterdir()], ["private.json"])

    def test_upstream_html_not_logged(self):
        import main as collector
        fake = Mock()
        fake.fetch_endpoint.return_value = RawPayload(source="learn", raw_id="synthetic", content="<html>synthetic-private-marker</html>", content_type="text/html", metadata={"url": "https://learn.tsinghua.edu.cn/?ticket=synthetic-private-marker"})
        with self.assertLogs(level="ERROR") as logs:
            with self.assertRaises(AdapterError) as caught:
                collector.fetch_learn_json(fake, "/synthetic", raw_id="synthetic")
        self.assertNotIn("synthetic-private-marker", " ".join(logs.output) + str(caught.exception))

    def test_personal_report_not_tracked_and_remains_ignored(self):
        root = Path(__file__).resolve().parents[1]
        # At development time the deletion may be unstaged. The file must be
        # absent, and the ignore rule prevents accidentally adding a new report.
        self.assertFalse((root / "storage/material_parse_report.json").exists())
        result = subprocess.run(["git", "check-ignore", "--no-index", "storage/material_parse_report.json"], cwd=root, capture_output=True)
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
