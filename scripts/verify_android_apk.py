"""Inspect a real APK with pinned Android build-tools, then emit public metadata.

Only an explicit, synthetic offline build is accepted. Never reads local .env.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile


def verify_permissions(badging, tree):
    permissions = sorted(set(re.findall(r"uses-permission[^:]*: name='([^']+)'", badging)))
    internal = "com.scholaros.app.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION"
    if set(permissions) - {internal}:
        raise ValueError("Unexpected offline APK permissions: " + ", ".join(permissions))
    if internal in permissions:
        blocks = re.split(r"\n(?=\s*E:)", tree)
        if not any("E: permission " in block and internal in block and
                   re.search(r"android:protectionLevel[^\n]*0x0*2\b", block) for block in blocks):
            raise ValueError("AndroidX internal receiver permission must be signature-only")
    return permissions


def inspect(apk, tools, commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit): raise ValueError("Full build commit required")
    if not apk.is_file() or not 100_000 <= apk.stat().st_size <= 30_000_000: raise ValueError("Missing or unexpected APK size")
    def run(tool, *args):
        return subprocess.check_output([str(tools / tool), *args, str(apk)], text=True, stderr=subprocess.STDOUT)
    badging = run("aapt2", "dump", "badging")
    expected = "package: name='com.scholaros.app' versionCode='1' versionName='0.1.0-dev'"
    if expected not in badging or "launchable-activity: name='com.scholaros.app.MainActivity'" not in badging: raise ValueError("Unexpected package or launcher")
    permissions = verify_permissions(badging, run("aapt2", "dump", "xmltree", "--file", "AndroidManifest.xml"))
    if "sdkVersion:'24'" not in badging or "targetSdkVersion:'36'" not in badging: raise ValueError("Unexpected Android SDK configuration")
    signature = run("apksigner", "verify", "--verbose", "--print-certs")
    if "CN=Android Debug" not in signature: raise ValueError("Only Debug signing expected")
    cert = re.search(r"Signer #1 certificate SHA-256 digest: (\w+)", signature)
    if not cert: raise ValueError("Missing verified signing certificate")
    with zipfile.ZipFile(apk) as archive:
        if archive.testzip() is not None: raise ValueError("Corrupt APK zip")
        names = archive.namelist()
        if any(".." in Path(n).parts or n.startswith("/") for n in names): raise ValueError("Unsafe archive entry")
        assets = [n for n in names if n.startswith("assets/")]
        forbidden = re.compile(r"(?:^|/)(?:\.env(?:\..*)?|[^/]*\.(?:db|sqlite3?|jsonl|jks|keystore)|cookies?[^/]*|sessions?[^/]*|credentials?[^/]*)$", re.I)
        if any(forbidden.search(n) for n in names): raise ValueError("Private file in APK")
        notice = archive.read("assets/NOTICE.txt").decode()
        if "2026 fnoi16wjhui" not in notice or "Meta Platforms" not in notice or "Drifty Co." not in notice:
            raise ValueError("Missing upstream/runtime license notices")
        config = json.loads(archive.read("assets/capacitor.config.json"))
        if config.get("appId") != "com.scholaros.app" or config.get("server", {}).get("url") or config.get("server", {}).get("cleartext") is not False: raise ValueError("Unsafe Capacitor server configuration")
        html = archive.read("assets/public/index.html").decode()
        if "connect-src 'none'" not in html: raise ValueError("Missing offline CSP")
        scripts = [n for n in assets if n.startswith("assets/public/assets/") and n.endswith(".js")]
        if not scripts: raise ValueError("Bundled app absent")
        js = "\n".join(archive.read(n).decode() for n in scripts)
        for text in ["离线演示模式", "电力系统分析", "电力电子技术基础", "自动控制原理"]:
            if text not in js: raise ValueError("Offline data or entry absent")
        for text in ["/api/settings/status", "VITE_API_BASE_URL", "synthetic-build-canary-", "BEGIN PRIVATE KEY", "LEARN_PASSWORD="]:
            if text in js: raise ValueError("Online entry or sensitive configuration in offline bundle")
    with apk.open("rb") as stream: checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"commit": commit, "file": "ScholarOS-0.1.0-dev-debug.apk", "bytes": apk.stat().st_size,
            "sha256": checksum, "applicationId": "com.scholaros.app",
            "versionCode": 1, "versionName": "0.1.0-dev", "minSdk": 24, "targetSdk": 36,
            "signing": "Android Debug", "certificate_sha256": cert.group(1), "permissions": permissions, "zip_integrity": "passed"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    sdk = Path(os.environ.get("ANDROID_HOME", os.environ.get("ANDROID_SDK_ROOT", "")))
    manifest = inspect(args.apk, sdk / "build-tools/36.0.0", args.commit)
    args.output.mkdir()  # exclusive, do not replace prior artifacts
    shutil.copyfile(args.apk, args.output / manifest["file"])
    (args.output / "apk-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (args.output / "SHA256SUMS").write_text(manifest["sha256"] + "  " + manifest["file"] + "\n")
    print("::notice title=ScholarOS APK::" + json.dumps(manifest, ensure_ascii=False))
    print("::notice title=APK certificate::" + manifest["certificate_sha256"])
    print("APK verification passed")


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        message = str(exc)[:1000].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error title=APK verification::" + message, flush=True)
        raise
