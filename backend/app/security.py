"""Single-owner API boundary. CORS is not authentication or CSRF protection."""
from __future__ import annotations

import hmac
import os
import json
import re
import threading
from pathlib import PurePosixPath
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pathlib import PureWindowsPath
from fastapi.routing import APIRoute

from starlette.responses import JSONResponse

_MUTATIONS = threading.BoundedSemaphore(2)

MAX_REQUEST_BYTES = 21 * 1024 * 1024  # includes multipart framing


def public_payload(value):
    """Do not expose internal command output, paths or raw upstream errors."""
    hidden = {"command", "commands", "stdout", "stderr", "detail", "path",
              "env_file_path", "last_errors", "collector_log_errors", "error_summary", "index_dir"}
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            if k in hidden or k.endswith("_path"):
                continue
            if k == "error" and v:
                v = "Operation failed"
            if k in {"source_file", "citation"} and isinstance(v, str):
                # Preserve relative course references, hide machine/user roots.
                if PurePosixPath(v).is_absolute() or PureWindowsPath(v).is_absolute():
                    v = PureWindowsPath(v).name
            result[k] = public_payload(v)
        return result
    if isinstance(value, list):
        return [public_payload(v) for v in value]
    return value


class RedactedRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                response = await handler(request)
            except (HTTPException, RequestValidationError):
                raise
            except ValueError:
                return JSONResponse({"detail": "Invalid configuration value"}, status_code=400)
            except Exception:
                # Returning here prevents ServerErrorMiddleware/uvicorn from
                # logging a traceback containing raw upstream credentials.
                return JSONResponse({"detail": "Operation failed"}, status_code=500)
            if response.headers.get("content-type", "").startswith("application/json"):
                data = public_payload(json.loads(response.body))
                response.body = json.dumps(data, ensure_ascii=False).encode()
                response.headers["content-length"] = str(len(response.body))
            return response
        return safe_handler


def allowed_origins() -> list[str]:
    # Exact origins only. Never derive trust from attacker-controlled Host.
    return ["http://127.0.0.1:8000", "http://localhost:8000",
            "http://127.0.0.1:5173", "http://localhost:5173"]


class SecurityBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope["headers"]}
        path = scope["path"]
        protected = path.startswith("/api/") and path != "/api/health"
        protected = protected or path in {"/docs", "/redoc", "/openapi.json"}

        async def secure_send(message):
            if message["type"] == "http.response.start":
                extra = [(b"x-content-type-options", b"nosniff"),
                         (b"referrer-policy", b"no-referrer"),
                         (b"x-frame-options", b"DENY")]
                if path.startswith("/api/"):
                    extra.append((b"cache-control", b"no-store"))
                if path.startswith("/app"):
                    extra.append((b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; frame-src blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"))
                message = {**message, "headers": list(message.get("headers", [])) + extra}
            await send(message)

        async def reject(code, message):
            return await JSONResponse({"detail": message}, status_code=code)(scope, receive, secure_send)

        origin = headers.get("origin")
        if origin is not None and origin not in allowed_origins():
            return await reject(403, "Untrusted origin")
        if headers.get("sec-fetch-site") == "cross-site":
            return await reject(403, "Cross-site request denied")
        if protected:
            token = os.getenv("SCHOLAROS_API_TOKEN", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
                return await reject(503, "API access is not configured")
            supplied = headers.get("authorization", "")
            if scope["method"] != "OPTIONS" and not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
                return await reject(401, "Authorization required")
        try:
            if int(headers.get("content-length", "0")) > MAX_REQUEST_BYTES:
                return await reject(413, "Request too large")
        except ValueError:
            return await reject(400, "Invalid request length")
        mutation = scope["method"] not in {"GET", "HEAD", "OPTIONS"}
        if not mutation:
            return await self.app(scope, receive, secure_send)
        if not _MUTATIONS.acquire(blocking=False):
            return await reject(429, "Too many active operations")
        try:
            # Bound the stream before Starlette's multipart parser can spool it.
            size = 0
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                size += len(message.get("body", b""))
                if size > MAX_REQUEST_BYTES:
                    return await reject(413, "Request too large")
                body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    break

            received = False
            async def bounded_receive():
                nonlocal received
                if not received:
                    received = True
                    data = bytes(body)
                    body.clear()
                    return {"type": "http.request", "body": data, "more_body": False}
                return await receive()
            await self.app(scope, bounded_receive, secure_send)
        finally:
            if mutation:
                _MUTATIONS.release()
