"""Small security primitives shared by CLI and API. No credential discovery."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def validate_auth_url(url: str) -> str:
    """Credential-bearing requests must stay on the two known SSO hosts."""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in {"id.tsinghua.edu.cn", "auth.cic.tsinghua.edu.cn"}
            or parsed.port not in (None, 443) or parsed.username is not None
            or parsed.password is not None or "\\" in url
            or any(ord(c) < 33 for c in url)):
        raise ValueError("Untrusted authentication URL")
    return url


def private_write(path: Path, text: str) -> None:
    """Atomically replace a private file; never follow a destination symlink."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Refusing a symlink configuration file")
    fd, name = tempfile.mkstemp(prefix=".private-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
