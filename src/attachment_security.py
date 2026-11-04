"""Fixed-origin, bounded attachment downloads. No automatic redirects."""
from __future__ import annotations

from contextlib import contextmanager
import ipaddress
import os
import socket
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from requests import Request
from requests.adapters import HTTPAdapter
from requests.utils import select_proxy
from urllib3 import HTTPSConnectionPool

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


class _PinnedHTTPSAdapter(HTTPAdapter):
    """Connect to a numeric validated address while verifying the original host.

    Requests 2.31 calls get_connection; 2.32+ calls the TLS-context variant.
    Neither path may resolve the campus hostname again or select a proxy.
    """
    def __init__(self, address: str):
        self._pool = HTTPSConnectionPool(address, port=443,
                                       assert_hostname=LEARN_HOST,
                                       server_hostname=LEARN_HOST)
        super().__init__(max_retries=0)

    def get_connection(self, url, proxies=None):
        if select_proxy(url, proxies or {}):
            raise DownloadError("Attachment proxy transport requires separate review")
        return self._pool

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        return self.get_connection(request.url, proxies)

    def close(self):
        self._pool.close()
        super().close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@contextmanager
def _open_download(session, url, headers, address):
    settings = session.merge_environment_settings(url, {}, True, True, None)
    # An HTTP CONNECT proxy resolves the hostname outside this process. Local
    # DNS checks cannot constrain it. Do not bypass an inherited proxy or claim
    # pinning through it: refuse until an enforceable proxy contract is provided.
    if select_proxy(url, settings["proxies"]):
        raise DownloadError("Attachment proxy transport requires separate review")
    request_headers = {**(headers or {}), "Host": LEARN_HOST, "Accept-Encoding": "identity"}
    prepared = session.prepare_request(Request("GET", url, headers=request_headers))
    with _PinnedHTTPSAdapter(address) as adapter:
        response = adapter.send(prepared, stream=True, timeout=(5, 15),
                                verify=settings["verify"], cert=settings["cert"], proxies={})
        try:
            yield response
        finally:
            response.close()


def download_attachment(session, url: str, output_dir: Path, filename: str, *, headers=None) -> tuple[Path, int, str]:
    validate_download_url(url)
    # Validate every answer, then pin the actual socket target to one answer.
    # The HTTP Host, TLS SNI and certificate identity remain the campus hostname.
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
        with _open_download(session, url, headers, addresses[0][4][0]) as response:
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
