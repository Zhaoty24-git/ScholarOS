"""Regress real native configuration and emulator acceptance gates, without SDK."""
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from scripts.check_ci_policy import validate_android
from scripts.check_android_test_results import check
from scripts.verify_android_apk import verify_permissions, verify_sdk

ROOT = Path(__file__).resolve().parents[1]


class AndroidContractTests(unittest.TestCase):
    def test_compiled_sdk_attributes_decoded(self):
        tree = 'A: android:minSdkVersion(0x0101020c)=(type 0x10)0x18\nA: android:targetSdkVersion(0x01010270)=(type 0x10)0x24'
        self.assertEqual(verify_sdk(tree), {"minSdkVersion": 24, "targetSdkVersion": 36})

    def test_sdk36_full_namespace_and_decimal_output_decoded(self):
        tree = 'A: http://schemas.android.com/apk/res/android:minSdkVersion(0x0101020c)=24\nA: http://schemas.android.com/apk/res/android:targetSdkVersion(0x01010270)=36'
        self.assertEqual(verify_sdk(tree), {"minSdkVersion": 24, "targetSdkVersion": 36})

    def test_wrong_compiled_sdk_rejected(self):
        tree = 'A: android:minSdkVersion(0x0101020c)=(type 0x10)0x18\nA: android:targetSdkVersion(0x01010270)=(type 0x10)0x23'
        with self.assertRaises(ValueError): verify_sdk(tree)

    def test_missing_sdk_metadata_is_not_success(self):
        with self.assertRaises(ValueError): verify_sdk('E: manifest')

    def test_actual_system_network_permission_rejected(self):
        tree = 'E: uses-permission (line=1)\n  A: http://schemas.android.com/apk/res/android:name(0x01010003)="android.permission.INTERNET"'
        with self.assertRaises(ValueError): verify_permissions(tree)

    def test_androidx_private_signature_permission_accepted(self):
        name = "com.scholaros.app.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION"
        tree = 'E: permission (line=18)\n  A: android:name="' + name + '"\n  A: android:protectionLevel=(type 0x11)0x2\nE: application'
        tree += '\nE: uses-permission (line=21)\n  A: android:name="' + name + '"'
        self.assertEqual(verify_permissions(tree), [name])

    def test_sdk36_private_permission_format_decoded(self):
        name = "com.scholaros.app.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION"
        prefix = 'A: http://schemas.android.com/apk/res/android:'
        tree = 'E: permission (line=18)\n  ' + prefix + 'name(0x01010003)="' + name + '" (Raw: "' + name + '")\n  ' + prefix + 'protectionLevel(0x01010009)=0x00000002\nE: uses-permission (line=21)\n  ' + prefix + 'name(0x01010003)="' + name + '"'
        self.assertEqual(verify_permissions(tree), [name])

    def test_unparseable_permission_is_rejected(self):
        with self.assertRaises(ValueError): verify_permissions('E: uses-permission (line=1)\n A: unsupported:name="android.permission.INTERNET"')

    def test_androidx_permission_without_signature_rejected(self):
        name = "com.scholaros.app.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION"
        tree = 'E: permission (line=18)\n  A: android:name="' + name + '"\n  A: android:protectionLevel=(type 0x11)0x0'
        tree += '\nE: uses-permission (line=21)\n  A: android:name="' + name + '"'
        with self.assertRaises(ValueError): verify_permissions(tree)

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
