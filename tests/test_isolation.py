import os
from pathlib import Path
import socket
import sqlite3
import unittest

from tests.support import OfflineCase, OfflineEnvironment, OfflineViolation, ROOT


class IsolationTests(OfflineCase):
    def expected_violation(self, function, category):
        before = len(self.sandbox.violations)
        with self.assertRaises(OfflineViolation): function()
        self.assertEqual(self.sandbox.violations[before:], [category])
        # Acknowledged only by this tripwire unit test, never by business code.
        del self.sandbox.violations[before:]

    def test_private_config_read_blocked_before_file_exists(self):
        self.expected_violation(lambda: (ROOT / "synthetic-private" / ".env").read_text(), "private_file_read")

    def test_outside_database_blocked(self):
        self.expected_violation(lambda: sqlite3.connect(ROOT / "storage" / "synthetic-forbidden.db"), "database_outside_fixture")

    def test_external_dns_never_reaches_resolver(self):
        self.expected_violation(lambda: socket.getaddrinfo("synthetic.invalid", 443), "external_dns")

    def test_external_socket_blocked_before_connect(self):
        with socket.socket() as sock:
            self.expected_violation(lambda: sock.connect(("203.0.113.1", 443)), "unregistered_network_connection")

    def test_source_write_blocked(self):
        self.expected_violation(lambda: (ROOT / "synthetic-never-written.txt").write_text("synthetic"), "file_write")

    def test_relative_source_directory_creation_blocked(self):
        self.expected_violation(lambda: os.mkdir("synthetic-never-created"), "filesystem_mutation_outside_fixture")

    def test_swallowed_violation_still_fails_environment(self):
        with self.assertRaisesRegex(AssertionError, "swallowed"):
            with OfflineEnvironment() as inner:
                try: (ROOT / "synthetic-private" / ".env").read_text()
                except OfflineViolation: pass

    def test_all_paths_and_adapters_are_fresh_and_scoped(self):
        from dataclasses import fields
        first = self.sandbox
        first.api.module_c._initialised = True
        with OfflineEnvironment() as second:
            self.assertNotEqual(first.root, second.root)
            self.assertFalse(second.api.module_c._initialised)
            for field in fields(second.config):
                value = getattr(second.config, field.name)
                if isinstance(value, Path): self.assertTrue(value.is_relative_to(second.root))
            self.assertNotIn("LLM_D_API_KEY", os.environ)
        self.assertEqual(first.api.settings.project_root, first.root)
        self.assertTrue(first.api.module_c._initialised)

    def test_cleanup_removes_temporary_state(self):
        with OfflineEnvironment() as inner:
            root = inner.root
            (root / ".env").write_text("SYNTHETIC=1")
        self.assertFalse(root.exists())
