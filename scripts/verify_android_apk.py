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


def android_attribute(tree, field):
    # SDK 36 aapt2 prints full namespace URIs and plain decimals; older aapt2
    # prints android: aliases and typed hex values. Read both without defaults.
    match = re.search(r"A:\s+(?:android:|http://schemas\.android\.com/apk/res/android:)" +
                      field + r"(?:\([^\n)]+\))?=\s*(?:\(type [^)]+\))?([^\n]+)", tree)
    return match.group(1).strip() if match else None


def numeric_attribute(tree, field):
    raw = android_attribute(tree, field)
    if raw is None: return None
    try: return int(raw, 0)
    except ValueError: return None


def verify_permissions(tree, network=False):
    elements = []
    for block in re.split(r"\n(?=\s*E:)", tree):
        element = re.match(r"\s*E:\s*([\w-]+)\b", block)
        if element: elements.append((element.group(1), block))
    permissions = []
    for element, block in elements:
        if not element.startswith("uses-permission"): continue
        raw = android_attribute(block, "name")
        name = re.match(r'^"([^"\n]+)"', raw or "")
        if not name: raise ValueError("Unparseable compiled permission name")
        permissions.append(name.group(1))
    permissions = sorted(set(permissions))
    internal = "com.scholaros.app.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION"
    allowed = {internal, "android.permission.INTERNET"} if network else {internal}
    if set(permissions) - allowed:
        raise ValueError("Unexpected offline APK permissions: " + ", ".join(permissions))
    if network and "android.permission.INTERNET" not in permissions: raise ValueError("AI APK needs explicit INTERNET permission")
    if internal in permissions:
        if not any(element == "permission" and re.match(r'^"' + re.escape(internal) + r'"(?:\s|$)', android_attribute(block, "name") or "") and
                   numeric_attribute(block, "protectionLevel") == 2 for element, block in elements):
            raise ValueError("AndroidX internal receiver permission must be signature-only")
    return permissions


def verify_sdk(tree):
    values = {}
    for field in ("minSdkVersion", "targetSdkVersion"):
        values[field] = numeric_attribute(tree, field)
    if values != {"minSdkVersion": 24, "targetSdkVersion": 36}:
        relevant = [line.strip() for line in tree.splitlines() if "SdkVersion" in line]
        raise ValueError("Unexpected compiled Android SDK configuration: " + str(values) + " " + str(relevant))
    return values


def inspect(apk, tools, commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit): raise ValueError("Full build commit required")
    if not apk.is_file() or not 100_000 <= apk.stat().st_size <= 30_000_000: raise ValueError("Missing or unexpected APK size")
    def run(tool, *args):
        return subprocess.check_output([str(tools / tool), *args, str(apk)], text=True, stderr=subprocess.STDOUT)
    badging = run("aapt2", "dump", "badging")
    expected = "package: name='com.scholaros.app' versionCode='2' versionName='0.2.0-dev'"
    if expected not in badging or "launchable-activity: name='com.scholaros.app.MainActivity'" not in badging: raise ValueError("Unexpected package or launcher")
    tree = run("aapt2", "dump", "xmltree", "--file", "AndroidManifest.xml")
    permissions = verify_permissions(tree, network=True)
    verify_sdk(tree)
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
        if config.get("loggingBehavior") != "none" or config.get("plugins", {}).get("CapacitorHttp", {}).get("enabled") is not False: raise ValueError("Credential bridge logging or generic HTTP enabled")
        html = archive.read("assets/public/index.html").decode()
        if "connect-src 'none'" not in html: raise ValueError("Missing offline CSP")
        scripts = [n for n in assets if n.startswith("assets/public/assets/") and n.endswith(".js")]
        if not scripts: raise ValueError("Bundled app absent")
        js = "\n".join(archive.read(n).decode() for n in scripts)
        for text in ["离线演示模式", "电力系统分析", "电力电子技术基础", "自动控制原理"]:
            if text not in js: raise ValueError("Offline data or entry absent")
        for text in ["/api/settings/status", "VITE_API_BASE_URL", "synthetic-build-canary-", "BEGIN PRIVATE KEY", "LEARN_PASSWORD="]:
            if text in js: raise ValueError("Online entry or sensitive configuration in offline bundle")
        for text in ["agnes-3.0-flash", "https://api.agnes-ai.cn/v1"]:
            if text not in js: raise ValueError("Domestic Agnes configuration missing")
        for name in names:
            if name.endswith((".dex", ".js", ".json", ".html", ".xml")):
                data = archive.read(name)
                if b"synthetic-agnes-" in data or re.search(rb"sk-[A-Za-z0-9_-]{20,}", data):
                    raise ValueError("Credential-like value or test key entered production APK")
    with apk.open("rb") as stream: checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"commit": commit, "file": "ScholarOS-0.2.0-dev-debug.apk", "bytes": apk.stat().st_size,
            "sha256": checksum, "applicationId": "com.scholaros.app",
            "versionCode": 2, "versionName": "0.2.0-dev", "minSdk": 24, "targetSdk": 36,
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
