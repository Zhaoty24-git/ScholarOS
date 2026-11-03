"""Regress real native configuration and emulator acceptance gates, without SDK."""
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from scripts.check_ci_policy import validate_android
from scripts.check_android_test_results import check

ROOT = Path(__file__).resolve().parents[1]


class AndroidContractTests(unittest.TestCase):
    def test_manifest_has_no_permissions_and_real_launcher(self):
        manifest = ET.parse(ROOT / "frontend/android/app/src/main/AndroidManifest.xml").getroot()
        self.assertEqual(manifest.findall("uses-permission"), [])
        a = "{http://schemas.android.com/apk/res/android}"
        app = manifest.find("application")
        self.assertEqual(app.get(a + "allowBackup"), "false")
        self.assertEqual(app.get(a + "usesCleartextTraffic"), "false")
        self.assertEqual(app.find("activity").get(a + "name"), ".MainActivity")

    def test_capacitor_cannot_connect_to_developer_server(self):
        c = json.loads((ROOT / "frontend/capacitor.config.json").read_text())
        self.assertEqual(c["appId"], "com.scholaros.app")
        self.assertNotIn("url", c["server"])
        self.assertEqual(c["server"]["cleartext"], False)
        self.assertFalse(c["android"]["allowMixedContent"])
        self.assertFalse(c["android"]["webContentsDebuggingEnabled"])

    def test_plugin_versions_fixed_and_match_lock(self):
        p = json.loads((ROOT / "frontend/package.json").read_text())
        lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
        for name, version in [("core", "8.6.0"), ("android", "8.6.0"), ("app", "8.1.2")]:
            key = "@capacitor/" + name
            self.assertEqual(p["dependencies"][key], version)
            self.assertEqual(lock["packages"]["node_modules/" + key]["version"], version)

    def test_android_workflow_policy(self):
        self.assertIn("android", validate_android((ROOT / ".github/workflows/android-debug.yml").read_text())["jobs"])

    def test_android_write_permissions_rejected(self):
        with self.assertRaises(ValueError): validate_android((ROOT / ".github/workflows/android-debug.yml").read_text().replace("contents: read", "contents: write"))

    def test_android_floating_action_rejected(self):
        with self.assertRaises(ValueError): validate_android((ROOT / ".github/workflows/android-debug.yml").read_text().replace("b7c566a772e6b6bfb58ed0dc250532a479d7789f", "v6"))

    def test_android_ignored_failure_rejected(self):
        with self.assertRaises(ValueError): validate_android((ROOT / ".github/workflows/android-debug.yml").read_text() + "\n# continue-on-error: true\n")

    def test_missing_emulator_results_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): check(tmp)

    def test_skipped_emulator_acceptance_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "TEST-example.xml").write_text('<testsuite tests="4" failures="0" errors="0" skipped="4" />')
            with self.assertRaises(ValueError): check(tmp)

    def test_real_named_passing_emulator_results_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = ["launchWithoutNetworkOrCredentials", "courseDetailAndNativeBack", "assignmentDetailsAndLongList", "noticesMaterialsSettingsAndRotation"]
            (Path(tmp) / "TEST-example.xml").write_text('<testsuite tests="4" failures="0" errors="0" skipped="0">' + ''.join('<testcase name="' + n + '" />' for n in names) + '</testsuite>')
            self.assertEqual(check(tmp)["tests"], 4)
