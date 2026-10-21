from __future__ import annotations

import hmac
import json
from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class BearerAuthMiddleware:
    """Pure ASGI middleware gating http scopes behind bearer-token auth.

    Requests must present `Authorization: Bearer <token>` with the configured
    client token. Tokens are never logged or echoed; every failed check gets a
    generic 401. Only lifespan scopes pass through untouched: websocket scopes
    are closed with 1008 and unknown scope types fail closed without reaching
    the wrapped app.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._token = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]
        if scope_type == "http":
            token = _bearer_token(scope.get("headers") or ())
            if token is None or not self._matches(token):
                await _send_unauthorized(send)
                return
            await self.app(scope, receive, send)
            return
        if scope_type == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope_type == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        # Unknown scope type: fail closed without calling the app or the wire.
        return

    def _matches(self, token: str) -> bool:
        # Bytes, because compare_digest raises on non-ASCII str instead of returning False.
        return hmac.compare_digest(token.encode(), self._token)


def _bearer_token(headers: Iterable[tuple[bytes, bytes]]) -> str | None:
    """Extract the bearer token from ASGI headers, or None when absent/invalid."""
    value: bytes | None = None
    for name, raw in headers:
        if name == b"authorization":
            value = raw
    if value is None:
        return None
    scheme, _, token = value.decode("latin-1").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def _send_unauthorized(send: Send) -> None:
    body = json.dumps({"error": "unauthorized"}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
