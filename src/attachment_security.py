"""Fixed-origin, bounded attachment downloads. No automatic redirects."""
from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
LEARN_HOST = "learn.tsinghua.edu.cn"


class DownloadError(ValueError):
    pass


def validate_download_url(url: str) -> str:
    try:
        p = urlsplit(url)
        if (any(ord(c) < 33 or ord(c) > 126 for c in url) or "\\" in url
                or p.scheme != "https" or p.hostname != LEARN_HOST
                or p.username is not None or p.password is not None
                or p.port not in (None, 443) or p.fragment):
            raise ValueError
    except ValueError:
        raise DownloadError("Untrusted attachment URL") from None
    return url


def download_attachment(session, url: str, output_dir: Path, filename: str, *, headers=None) -> tuple[Path, int, str]:
    validate_download_url(url)
    # Defence in depth against private-address resolution; HTTPS certificate
    # validation and the fixed administratively trusted host remain mandatory.
    try:
        addresses = socket.getaddrinfo(LEARN_HOST, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError
    except (OSError, ValueError):
        raise DownloadError("Attachment host is unavailable") from None
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if filename in {"", ".", ".."} or "/" in filename or "\\" in filename or "\x00" in filename:
        raise DownloadError("Invalid attachment filename")
    target = root / filename
    if target.parent != root:
        raise DownloadError("Invalid attachment path")
    temporary = None
    started = time.monotonic()
    try:
        with session.get(url, headers=headers or {}, timeout=(5, 15), stream=True, allow_redirects=False, verify=True) as response:
            if response.status_code != 200:
                raise DownloadError("Attachment download refused")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise DownloadError("Encoded attachment response refused")
            if int(response.headers.get("Content-Length", "0")) > MAX_DOWNLOAD_BYTES:
                raise DownloadError("Attachment exceeds download limit")
            fd, temporary = tempfile.mkstemp(prefix=".download-", dir=root)
            total = 0
            with os.fdopen(fd, "wb") as stream:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES or time.monotonic() - started > 120:
                        raise DownloadError("Attachment exceeds download limits")
                    stream.write(chunk)
            # Hard-link publication refuses existing files and symlinks, even
            # when a competing process races the destination name.
            for index in range(1, 10000):
                candidate = target if index == 1 else target.with_name(f"{target.stem}_{index}{target.suffix}")
                try:
                    os.link(temporary, candidate)
                    return candidate, total, response.headers.get("Content-Type", "").split(";")[0]
                except FileExistsError:
                    continue
            raise DownloadError("Cannot allocate attachment file")
    except DownloadError:
        raise
    except Exception:
        # Requests exceptions can embed credential-bearing URLs and headers.
        raise DownloadError("Attachment download failed") from None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
