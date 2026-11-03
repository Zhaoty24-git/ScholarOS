"""Shared synthetic application environment and process-wide I/O tripwires.

This is a test safety net, not a sandbox for hostile native code. No secrets are
read to construct fixtures; each test gets fresh paths, adapters and caches.
"""
from contextlib import ExitStack
import importlib
import ipaddress
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "".join(["synthetic-access-", "x" * 40])
AUTH = {"Authorization": "Bearer " + TOKEN}
_active = None


def _restore_module(name, previous):
    if previous is ...:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = previous


class OfflineViolation(RuntimeError):
    pass


def _audit(event, args):
    guard = _active
    if guard is None:
        return
    if event == "open" and not isinstance(args[0], int):
        lexical = Path(os.fsdecode(args[0])).absolute()
        path = lexical.resolve()
        mode, flags = args[1], args[2]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool((flags or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
        sensitive = any(p.name in {".env", ".netrc", "_netrc"} or (p.name.startswith(".env.") and p.name != ".env.example") for p in (path, lexical))
        sensitive = sensitive or any(p.is_relative_to(ROOT / folder) for folder in ("storage", "logs") for p in (path, lexical))
        if not path.is_relative_to(guard.root) and (writing or sensitive):
            guard.deny("file_write" if writing else "private_file_read")
    elif event == "sqlite3.connect":
        if str(args[0]) != ":memory:" and not Path(args[0]).resolve().is_relative_to(guard.root):
            guard.deny("database_outside_fixture")
    elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.rename"}:
        positions = [(args[0], args[2]), (args[1], args[3])] if event == "os.rename" else [(args[0], args[2] if event == "os.mkdir" else args[1])]
        for value, descriptor in positions:
            if isinstance(value, (str, bytes)):
                path = Path(os.fsdecode(value))
                if not path.is_absolute() and descriptor not in (None, -1):
                    # Linux rmtree works relative to an open directory handle.
                    path = Path(os.readlink(f"/proc/self/fd/{descriptor}")) / path
                if not path.resolve().is_relative_to(guard.root):
                    guard.deny("filesystem_mutation_outside_fixture")
    elif event == "socket.getaddrinfo":
        host = args[0]
        if host in (None, "localhost", b"localhost"):
            return
        try:
            ipaddress.ip_address(host)
        except (ValueError, TypeError):
            guard.deny("external_dns")
    elif event == "socket.connect":
        address = args[1]
        try:
            allowed = isinstance(address, tuple) and ipaddress.ip_address(address[0]).is_loopback and address[1] in guard.ports
        except ValueError:
            allowed = False
        if not allowed:
            guard.deny("unregistered_network_connection")
    elif event == "subprocess.Popen":
        command = args[1]
        if not isinstance(command, (list, tuple)) or len(command) < 2:
            guard.deny("unexpected_subprocess")
        pair = (Path(str(command[0])).name, command[1])
        if pair not in {("git", "check-ignore"), ("openssl", "req")}:
            guard.deny("unexpected_subprocess")


sys.addaudithook(_audit)


def import_app():
    if "backend.app.main" not in sys.modules:
        with OfflineEnvironment(bind_app=False):
            importlib.import_module("backend.app.main")
    return sys.modules["backend.app.main"]


class OfflineEnvironment:
    def __init__(self, *, bind_app=True, seed=False):
        self.bind_app, self.seed = bind_app, seed
        self.ports, self.violations = set(), []

    def deny(self, category):
        self.violations.append(category)
        raise OfflineViolation("Forbidden test I/O: " + category)

    def __enter__(self):
        global _active
        if self.bind_app:
            import_app()
        previous = _active
        _active = None  # only trusted fixture directory allocation
        try:
            self.stack = ExitStack()
            self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="scholaros-test-")))
        finally:
            _active = previous
        environment = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR", "TMPDIR", "TEMP") if k in os.environ}
        environment.update(LEARNING_ASSISTANT_ROOT=str(self.root), SCHOLAROS_API_TOKEN=TOKEN,
                           HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", MATERIAL_OCR_LANG="eng")
        self.stack.enter_context(patch.dict(os.environ, environment, clear=True))
        self.stack.enter_context(patch.object(tempfile, "tempdir", str(self.root)))
        self.stack.enter_context(patch.object(sys, "dont_write_bytecode", True))
        self.stack.enter_context(patch("dotenv.load_dotenv"))
        # Semantic models are an explicitly unselected optional target. Match
        # the minimal CI installation even when the developer has them cached.
        for name in ("sentence_transformers", "transformers", "huggingface_hub"):
            previous_module = sys.modules.get(name, ...)
            sys.modules[name] = None
            self.stack.callback(_restore_module, name, previous_module)
        self.previous, _active = _active, self
        try:
            if self.bind_app:
                self.api = import_app()
                from backend.app.settings import BackendSettings
                self.config = BackendSettings.from_env()
                for name, module in list(sys.modules.items()):
                    if name.startswith("backend.app") and hasattr(module, "settings"):
                        self.stack.enter_context(patch.object(module, "settings", self.config))
                from backend.app import sync_jobs
                from backend.app.adapters import module_d
                self.stack.enter_context(patch.object(sync_jobs, "JOBS_DIR", self.root / "logs/sync_jobs"))
                self.stack.enter_context(patch.object(sync_jobs, "STATE_FILE", self.root / "storage/sync_job_state.json"))
                for name in ("_TASK_CACHE", "_TASK_CACHE_TIME", "_MATERIAL_CACHE", "_client", "_client_signature"):
                    self.stack.enter_context(patch.object(module_d, name, None))
                for name, adapter in (("module_a", self.api.ModuleAAdapter(self.config)),
                                      ("module_b", self.api.ModuleBAdapter(self.config)),
                                      ("module_c", self.api.ModuleCAdapter(self.config)),
                                      ("module_d", self.api.ModuleDAdapter())):
                    self.stack.enter_context(patch.object(self.api, name, adapter))
                if self.seed:
                    self.seed_demo()
            return self
        except BaseException:
            _active = None
            try: self.stack.close()
            finally: _active = self.previous
            raise

    def __exit__(self, exc_type, exc, tb):
        global _active
        _active = None
        try: self.stack.close()
        finally: _active = self.previous
        if exc_type is None and self.violations:
            raise AssertionError("Test swallowed forbidden I/O: " + ", ".join(self.violations))

    def write_records(self, path, records):
        import json
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")

    def seed_demo(self):
        self.write_records(self.config.demo_collector_jsonl, [{
            "source": "learn", "raw_id": "demo_synthetic_homework", "task_type": "homework",
            "course_name": "合成课程", "title": "合成作业", "content": "合成题目",
            "published_at": "2026-03-01T09:00:00+08:00", "ddl": "2026-03-10T23:59:00+08:00",
            "status": "unsubmitted", "completed": False,
        }])
        self.write_records(self.config.demo_material_chunks_jsonl, [{
            "chunk_id": "demo_synthetic_chunk", "source_file": "synthetic.md", "file_hash": "demo-sha256",
            "material_type": "markdown", "course_name": "合成课程", "title": "合成讲义",
            "chunk_index": 0, "text": "合成关键词检索资料",
        }])

    def client(self, *, authorized=True):
        from fastapi.testclient import TestClient
        return TestClient(self.api.app, base_url="http://localhost", headers=AUTH if authorized else {})


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.sandbox = self.enterContext(OfflineEnvironment())
        self.root = self.sandbox.root
        self.client = self.sandbox.client(authorized=False)
