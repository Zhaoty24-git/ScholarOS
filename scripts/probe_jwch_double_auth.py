"""Interactive JWCH/auth.cic double-auth probe."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.adapters.base_adapter import AdapterConfig
from src.security import private_write, auth_post, validate_session_age
from src.adapters.jwch_adapter import JwchAdapter
from src.adapters.learn_adapter import select_login_form
from src.env_loader import load_project_env


SESSION_PATH = ROOT / "storage" / "jwch_double_auth_session.json"
TRUST_PATH = ROOT / "storage" / "jwch_trust_device.json"
AUTH_BASE = "https://auth.cic.tsinghua.edu.cn"
DOUBLE_AUTH_URL = AUTH_BASE + "/b/doubleAuth/login"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe JWCH/auth.cic double authentication.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Start auth.cic login and send a verification code.")
    start.add_argument("--type", choices=("mobile", "wechat"), default="mobile")

    verify = subparsers.add_parser("verify", help="Submit verification code and optionally trust device.")
    verify.add_argument("--code", required=True)
    verify.add_argument("--trust-device", action="store_true")
    verify.add_argument("--device-name", default="CourseAgentCollector-JWCH")
    return parser


def jwch_config() -> AdapterConfig:
    config = AdapterConfig.from_env("jwch", prefix="JWCH", defaults={"base_url": "https://zhjw.cic.tsinghua.edu.cn"})
    extra = dict(config.extra)
    extra.update(
        {
            "login_url": AUTH_BASE + "/f/login",
            "username_field": "username",
            "password_field": "password",
            "trust_path": str(TRUST_PATH),
            "timeout_seconds": int(extra.get("timeout_seconds", 20)),
        }
    )
    return AdapterConfig(
        source="jwch",
        base_url=config.base_url,
        username=config.username,
        password=config.password,
        token=config.token,
        data_path=config.data_path,
        extra=extra,
    )


def save_session(session) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "created_at": datetime.now().isoformat(),
        "cookies": session.cookies.get_dict(domain="auth.cic.tsinghua.edu.cn"),
    }
    private_write(SESSION_PATH, json.dumps(data, ensure_ascii=False))


def load_session(adapter: JwchAdapter):
    if not SESSION_PATH.exists():
        raise SystemExit("No saved JWCH double-auth session. Run start first.")
    data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    try:
        validate_session_age(data)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    session = adapter._build_session()
    for name, value in data.get("cookies", {}).items():
        session.cookies.set(name, value, domain="auth.cic.tsinghua.edu.cn", path="/", secure=True)
    adapter._session = session
    return session


def start_double_auth(kind: str) -> int:
    load_project_env()
    adapter = JwchAdapter(jwch_config())
    session = adapter._build_session()
    adapter._session = session

    page = session.get(AUTH_BASE + "/f/login", timeout=20)
    page.raise_for_status()
    form = select_login_form(page.text, username_field="username", password_field="password")
    payload = dict(form.get("inputs", {}))
    payload["username"] = adapter._credential("username")
    payload["password"] = adapter._prepare_password(page.url, page.text)
    login = auth_post(session, urljoin(page.url, str(form.get("action") or "")), data=payload, timeout=20)
    login.raise_for_status()

    approaches = auth_post(session, DOUBLE_AUTH_URL, data={"action": "FIND_APPROACHES"}, timeout=20)
    approaches.raise_for_status()
    if approaches.json().get("result") != "success":
        raise SystemExit("JWCH double-auth approach discovery failed.")

    send = auth_post(session, DOUBLE_AUTH_URL, data={"action": "SEND_CODE", "type": kind}, timeout=20)
    send.raise_for_status()
    data = send.json()
    save_session(session)
    print(f"jwch_double_auth_start success={data.get('result') == 'success'} msg_present={bool(data.get('msg'))}")
    print(f"session_saved={SESSION_PATH}")
    return 0 if data.get("result") == "success" else 2


def verify_double_auth(code: str, *, trust_device: bool, device_name: str) -> int:
    load_project_env()
    adapter = JwchAdapter(jwch_config())
    session = load_session(adapter)

    verify = auth_post(session, DOUBLE_AUTH_URL, data={"action": "VERITY_CODE", "vericode": code}, timeout=20)
    verify.raise_for_status()
    verify_data = verify.json()
    print(f"jwch_double_auth_verify success={verify_data.get('result') == 'success'} msg_present={bool(verify_data.get('msg'))}")
    if verify_data.get("result") != "success":
        return 2

    if trust_device:
        trust = auth_post(session,
            AUTH_BASE + "/b/doubleAuth/personal/saveFinger",
            data={
                "fingerprint": "CourseAgentCollector-JWCH",
                "deviceName": device_name,
                "radioVal": "是",
                "singleLogin": "yes",
            },
            timeout=20,
        )
        trust.raise_for_status()
        trust_data = trust.json()
        TRUST_PATH.parent.mkdir(parents=True, exist_ok=True)
        private_write(TRUST_PATH, json.dumps(trust_data, ensure_ascii=False))
        print(f"jwch_trust_device success={trust_data.get('result') == 'success'} msg_present={bool(trust_data.get('msg'))}")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "start":
        return start_double_auth(args.type)
    if args.command == "verify":
        return verify_double_auth(args.code, trust_device=args.trust_device, device_name=args.device_name)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
