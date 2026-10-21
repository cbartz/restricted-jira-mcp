import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

from restricted_jira_mcp.http_auth import BearerAuthMiddleware, load_client_token_hashes

CLIENT_TOKEN = "client-token-1"
OTHER_CLIENT_TOKEN = "client-token-2"
CLIENT_TOKEN_HASH = hashlib.sha256(CLIENT_TOKEN.encode()).hexdigest()
OTHER_CLIENT_TOKEN_HASH = hashlib.sha256(OTHER_CLIENT_TOKEN.encode()).hexdigest()


def _dummy_asgi_app(scopes_seen):
    """A minimal ASGI app that records scope types and answers 200 for http scopes."""

    async def app(scope, receive, send):
        scopes_seen.append(scope["type"])
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        else:
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({"type": "http.response.body", "body": b"ok"})

    return app


class LoadClientTokenHashesTests(unittest.TestCase):
    def test_loads_lowercase_hashes_skipping_comments_and_blank_lines(self):
        # Happy path: mixed-case hex digests, comments and blank lines all tolerated.
        content = (
            "# client token hashes\n"
            f"{CLIENT_TOKEN_HASH.upper()}\n"
            "\n"
            f"{OTHER_CLIENT_TOKEN_HASH}\n"
            "   \n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "client-token-hashes.txt"
            path.write_text(content, encoding="utf-8")
            self.assertEqual(
                load_client_token_hashes(path),
                (CLIENT_TOKEN_HASH, OTHER_CLIENT_TOKEN_HASH),
            )

    def test_rejects_malformed_lines(self):
        # Error cases: any non-comment line that is not exactly 64 hex chars must fail.
        malformed_lines = {
            "short line": "abc\n",
            "63 hex chars": "a" * 63 + "\n",
            "65 hex chars": "a" * 65 + "\n",
            "non-hex characters": "z" * 64 + "\n",
        }
        for label, bad_line in malformed_lines.items():
            with self.subTest(label=label):
                content = f"{CLIENT_TOKEN_HASH}\n{bad_line}"
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "client-token-hashes.txt"
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_client_token_hashes(str(path))

    def test_rejects_file_without_any_hash(self):
        # Fail closed: comments and blank lines alone must not produce an empty allowlist.
        content = "# just a comment\n\n   \n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "client-token-hashes.txt"
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                load_client_token_hashes(str(path))


class BearerAuthMiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.scopes_seen = []

    def _app(self):
        return _dummy_asgi_app(self.scopes_seen)

    def test_rejects_requests_without_a_valid_bearer_token(self):
        # Table-driven rejection cases: every failure mode is 401 + JSON error + challenge header.
        headers_by_case = {
            "missing authorization header": {},
            "wrong bearer token": {"Authorization": f"Bearer {OTHER_CLIENT_TOKEN}"},
            "wrong scheme": {"Authorization": f"Basic {CLIENT_TOKEN}"},
            "bearer without token": {"Authorization": "Bearer"},
        }
        middleware = BearerAuthMiddleware(self._app(), (CLIENT_TOKEN_HASH,))
        for label, headers in headers_by_case.items():
            with self.subTest(label=label):
                self.scopes_seen.clear()
                response = TestClient(middleware).get("/", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"error": "unauthorized"})
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
                self.assertNotIn("http", self.scopes_seen)

    def test_allows_request_with_valid_bearer_token(self):
        # Happy path: matching bearer token reaches the wrapped app and gets its 200.
        middleware = BearerAuthMiddleware(self._app(), (CLIENT_TOKEN_HASH,))
        response = TestClient(middleware).get(
            "/", headers={"Authorization": f"Bearer {CLIENT_TOKEN}"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "ok")
        self.assertIn("http", self.scopes_seen)

    def test_allows_token_matching_a_file_loaded_hash(self):
        # Happy path: hash loaded from a file (stored uppercase) authorizes the raw client token.
        content = f"{CLIENT_TOKEN_HASH.upper()}\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "client-token-hashes.txt"
            path.write_text(content, encoding="utf-8")
            middleware = BearerAuthMiddleware(self._app(), load_client_token_hashes(str(path)))
        response = TestClient(middleware).get(
            "/", headers={"Authorization": f"Bearer {CLIENT_TOKEN}"}
        )
        self.assertEqual(response.status_code, 200)

    def test_passes_lifespan_scope_through_to_the_wrapped_app(self):
        # Lifespan must reach the wrapped app so MCP task-group startup still runs.
        middleware = BearerAuthMiddleware(self._app(), (CLIENT_TOKEN_HASH,))
        with TestClient(middleware):
            self.assertIn("lifespan", self.scopes_seen)

    def test_closes_websocket_scope_without_reaching_the_app(self):
        # A websocket scope must be refused with a 1008 close, never proxied open.
        async def scenario():
            sent = []

            async def receive():
                return {"type": "websocket.connect"}

            async def send(message):
                sent.append(message)

            middleware = BearerAuthMiddleware(self._app(), (CLIENT_TOKEN_HASH,))
            await middleware({"type": "websocket", "headers": ()}, receive, send)
            return sent

        sent = asyncio.run(scenario())

        self.assertEqual(sent, [{"type": "websocket.close", "code": 1008}])
        self.assertEqual(self.scopes_seen, [])

    def test_unknown_scope_types_fail_closed_without_touching_the_app(self):
        # Unknown scope types must neither reach the app nor emit anything.
        async def scenario():
            sent = []

            async def receive():
                return {"type": "mystery"}

            async def send(message):
                sent.append(message)

            middleware = BearerAuthMiddleware(self._app(), (CLIENT_TOKEN_HASH,))
            await middleware({"type": "mystery"}, receive, send)
            return sent

        sent = asyncio.run(scenario())

        self.assertEqual(sent, [])
        self.assertEqual(self.scopes_seen, [])
