"""Small ASGI middleware for existing same-origin and request-size protections."""
import time
import uuid
from starlette.datastructures import Headers
from starlette.responses import JSONResponse


class RequestPolicy:
    def __init__(self, app, max_body_bytes=50000):
        self.app, self.max_body_bytes = app, max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        max_body_bytes = scope["app"].state.settings.max_body_bytes
        headers = Headers(scope=scope)
        request_id = str(uuid.uuid4())
        started = time.perf_counter()

        async def secured_send(message):
            if message["type"] == "http.response.start":
                docs = scope["path"] in ("/docs", "/redoc", "/docs/oauth2-redirect")
                csp = ("default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                       "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; "
                       "object-src 'none'; frame-ancestors 'none'") if docs else (
                    "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; "
                    "base-uri 'none'; frame-ancestors 'none'")
                message["headers"] += [(b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                    (b"x-request-id", request_id.encode()),
                    (b"server-timing", f"total;dur={(time.perf_counter()-started)*1000:.1f}".encode())]
                if scope["path"] != "/legacy":
                    message["headers"].append((b"content-security-policy", csp.encode()))
            await send(message)

        async def reject(status, code):
            await JSONResponse({"error": code}, status_code=status)(scope, receive, secured_send)

        if scope["method"] == "POST":
            port = scope.get("server", ("127.0.0.1", 8000))[1]
            scheme = scope.get("scheme", "http")
            suffix = f":{port}" if port != (443 if scheme == "https" else 80) else ""
            origin = headers.get("origin")
            if origin and origin not in (f"{scheme}://127.0.0.1{suffix}", f"{scheme}://localhost{suffix}"):
                return await reject(403, "ORIGIN_REJECTED")
            if headers.get("content-type", "").split(";")[0].strip() != "application/json":
                return await reject(415, "JSON_REQUIRED")
            try:
                length = int(headers.get("content-length", "0"))
            except ValueError:
                return await reject(400, "INVALID_JSON")
            if length < 0 or length > max_body_bytes:
                return await reject(413, "INVALID_BODY_SIZE")
            chunks, size = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > max_body_bytes:
                    return await reject(413, "INVALID_BODY_SIZE")
                chunks.append(chunk)
                if not message.get("more_body"):
                    break
            if not size:
                return await reject(413, "INVALID_BODY_SIZE")
            body = b"".join(chunks)
            delivered = False

            async def buffered_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()
            return await self.app(scope, buffered_receive, secured_send)
        return await self.app(scope, receive, secured_send)
