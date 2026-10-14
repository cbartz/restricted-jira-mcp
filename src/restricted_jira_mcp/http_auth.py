from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from pathlib import Path
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def load_client_token_hashes(path: str | Path) -> tuple[str, ...]:
    """Read SHA-256 hex digests of accepted client tokens, one per line.

    Comment lines (#) and blank lines are skipped; any other line must be
    exactly 64 hex characters (lowercased on load). Fails closed when a line
    is malformed or the file yields no hashes at all.
    """
    hashes: list[str] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            digest = entry.lower()
            if not _HEX64_RE.fullmatch(digest):
                raise ValueError(
                    f"Invalid client-token hash in {path}: expected exactly 64 hex characters per line"
                )
            hashes.append(digest)
    if not hashes:
        raise ValueError(f"No client-token hashes found in {path}")
    return tuple(hashes)


class BearerAuthMiddleware:
    """Pure ASGI middleware gating http scopes behind bearer-token auth.

    Requests must present `Authorization: Bearer <token>` where the token's
    SHA-256 digest matches one of the precomputed hashes. Tokens are never
    logged or echoed; every failed check gets a generic 401.
    """

    def __init__(self, app: ASGIApp, token_hashes: Iterable[str]) -> None:
        self.app = app
        self._token_hashes = tuple(token_hashes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = _bearer_token(scope.get("headers") or ())
        if token is None or not self._matches(token):
            await _send_unauthorized(send)
            return

        await self.app(scope, receive, send)

    def _matches(self, token: str) -> bool:
        digest = hashlib.sha256(token.encode()).hexdigest()
        return any(hmac.compare_digest(digest, stored) for stored in self._token_hashes)


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
