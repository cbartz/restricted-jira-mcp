"""Streamable-HTTP transport wiring tests: bearer auth gates the MCP endpoint."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from starlette.testclient import TestClient

import test_jira_client
from restricted_jira_mcp.jira_client import JiraClient
from restricted_jira_mcp.server import build_http_app, create_server, main

CLIENT_TOKEN = "client-token-1"
CLIENT_TOKEN_HASH = hashlib.sha256(CLIENT_TOKEN.encode()).hexdigest()
ACCEPT_HEADERS = {"Accept": "application/json, text/event-stream"}


def _tools_call_body(name: str, arguments: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


class HTTPTransportTests(unittest.TestCase):
    """POST /mcp through the full bearer-auth + MCP stack over a real JiraClient."""

    def setUp(self):
        self.session = test_jira_client.FakeSession()
        self.client = test_jira_client.client(self.session)
        tokens_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tokens_dir.cleanup)
        tokens_path = Path(tokens_dir.name) / "client-token-hashes.txt"
        tokens_path.write_text(CLIENT_TOKEN_HASH + "\n", encoding="utf-8")
        env_patcher = mock.patch.dict(
            os.environ, {"JIRA_MCP_CLIENT_TOKENS_FILE": str(tokens_path)}
        )
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    def _post_tools_call(self, name: str, arguments: dict, headers: dict):
        app = build_http_app(self.client, host="127.0.0.1", port=8000)
        with TestClient(app, base_url="http://127.0.0.1:8000") as http:
            return http.post(
                "/mcp",
                json=_tools_call_body(name, arguments),
                headers={**ACCEPT_HEADERS, **headers},
            )

    def test_http_rejects_missing_token(self):
        # No Authorization header at all: the middleware answers 401 before the MCP app runs.
        response = self._post_tools_call("jira_get_issue", {"issue_key": "ISD-5444"}, {})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "unauthorized"})
        self.assertEqual(self.session.calls, [])

    def test_http_rejects_wrong_token(self):
        # A bearer token whose hash is not in the file must get the same generic 401.
        response = self._post_tools_call(
            "jira_get_issue",
            {"issue_key": "ISD-5444"},
            {"Authorization": "Bearer nope"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "unauthorized"})
        self.assertEqual(self.session.calls, [])

    def test_http_enforces_allowlist_for_authenticated_call(self):
        # A valid client token gets through, and the Jira policy still blocks non-allowlisted keys.
        response = self._post_tools_call(
            "jira_get_issue",
            {"issue_key": "NDA-1"},
            {"Authorization": f"Bearer {CLIENT_TOKEN}"},
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("Project NDA is not allowlisted", result["content"][0]["text"])
        self.assertEqual(self.session.calls, [])

    def test_http_returns_issue_for_authenticated_call(self):
        # Happy path: a valid client token reads an allowlisted issue end to end.
        response = self._post_tools_call(
            "jira_get_issue",
            {"issue_key": "ISD-5444"},
            {"Authorization": f"Bearer {CLIENT_TOKEN}"},
        )

        self.assertEqual(response.status_code, 200)
        issue = json.loads(response.json()["result"]["content"][0]["text"])
        self.assertEqual(issue["key"], "ISD-5444")


class CreateServerTests(unittest.TestCase):
    """create_server() must register the full tool set on the injected client only."""

    def setUp(self):
        self.session = test_jira_client.FakeSession()
        self.client = test_jira_client.client(self.session)

    def _tool_names(self, mcp) -> list[str]:
        return sorted(tool.name for tool in mcp._tool_manager.list_tools())

    def test_create_server_uses_injected_client(self):
        # Injecting a client registers every tool on it, without touching JiraClient.from_env.
        with mock.patch.object(
            JiraClient,
            "from_env",
            side_effect=AssertionError("create_server must use the injected client"),
        ):
            names = self._tool_names(create_server(self.client))

        self.assertEqual(
            names,
            [
                "jira_add_comment",
                "jira_create_issue",
                "jira_delete_comment",
                "jira_get_comments",
                "jira_get_issue",
                "jira_link_issues",
                "jira_link_types",
                "jira_search",
                "jira_update_comment",
                "jira_update_issue",
            ],
        )

    def test_create_server_defaults_to_from_env(self):
        # The zero-argument path keeps existing behaviour: one JiraClient built from env.
        with mock.patch.object(JiraClient, "from_env", return_value=self.client) as from_env:
            mcp = create_server()

        from_env.assert_called_once_with()
        self.assertIn("jira_get_issue", self._tool_names(mcp))


class BuildHTTPAppTokensTests(unittest.TestCase):
    """build_http_app() must fail closed at startup without usable client-token hashes."""

    def setUp(self):
        self.session = test_jira_client.FakeSession()
        self.client = test_jira_client.client(self.session)

    def test_build_http_app_fails_closed_without_usable_tokens_file(self):
        # Every unusable $JIRA_MCP_CLIENT_TOKENS_FILE must raise ValueError, never serve open.
        with tempfile.TemporaryDirectory() as tmp:
            empty_file = Path(tmp) / "only-comments.txt"
            empty_file.write_text("\n# no hashes here\n", encoding="utf-8")
            env_without_tokens = {
                key: value
                for key, value in os.environ.items()
                if key != "JIRA_MCP_CLIENT_TOKENS_FILE"
            }
            cases = [
                ("env var unset", dict(env_without_tokens)),
                ("env var empty", {**env_without_tokens, "JIRA_MCP_CLIENT_TOKENS_FILE": ""}),
                (
                    "tokens file missing",
                    {**env_without_tokens, "JIRA_MCP_CLIENT_TOKENS_FILE": str(Path(tmp) / "nope.txt")},
                ),
                (
                    "tokens file without hashes",
                    {**env_without_tokens, "JIRA_MCP_CLIENT_TOKENS_FILE": str(empty_file)},
                ),
            ]
            for label, env in cases:
                with self.subTest(label=label):
                    with mock.patch.dict(os.environ, env, clear=True):
                        with self.assertRaises(ValueError):
                            build_http_app(self.client, host="127.0.0.1", port=8000)
                    self.assertEqual(self.session.calls, [])


class MainEntrypointTests(unittest.TestCase):
    """main() must pick the transport before touching any Jira config or token files."""

    def setUp(self):
        self.session = test_jira_client.FakeSession()
        self.client = test_jira_client.client(self.session)

    def _env_without(self, *names: str) -> dict:
        return {
            key: value
            for key, value in os.environ.items()
            if key not in names
        }

    def test_help_exits_zero_before_any_config_load(self):
        # --help prints usage and exits 0 with no env at all and no JiraClient.from_env call.
        with mock.patch.dict(os.environ, self._env_without("JIRA_MCP_TRANSPORT"), clear=True):
            with mock.patch.object(
                JiraClient,
                "from_env",
                side_effect=AssertionError("config must not load before --help"),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    main(["--help"])

        self.assertEqual(ctx.exception.code, 0)

    def test_main_defaults_to_stdio_transport(self):
        # No flag and no env: the stdio server runs via create_server().run().
        with mock.patch.dict(os.environ, self._env_without("JIRA_MCP_TRANSPORT"), clear=True):
            with mock.patch.object(JiraClient, "from_env", return_value=self.client):
                with mock.patch("mcp.server.fastmcp.FastMCP.run") as run:
                    main([])

        run.assert_called_once_with()

    def test_main_transport_env_selects_http(self):
        # $JIRA_MCP_TRANSPORT=http must serve the bearer-authenticated app via uvicorn.
        env = {**self._env_without("JIRA_MCP_TRANSPORT"), "JIRA_MCP_TRANSPORT": "http"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(JiraClient, "from_env", return_value=self.client):
                with mock.patch(
                    "restricted_jira_mcp.server.build_http_app", return_value="asgi-app"
                ) as build:
                    with mock.patch("uvicorn.run") as run:
                        main(["--host", "0.0.0.0", "--port", "9000"])

        build.assert_called_once_with(self.client, "0.0.0.0", 9000)
        run.assert_called_once_with("asgi-app", host="0.0.0.0", port=9000)

    def test_main_invalid_transport_env_fails_closed(self):
        # A typo in $JIRA_MCP_TRANSPORT must exit with an error, not silently serve stdio.
        env = {**self._env_without("JIRA_MCP_TRANSPORT"), "JIRA_MCP_TRANSPORT": "bogus"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(
                JiraClient,
                "from_env",
                side_effect=AssertionError("config must not load before validation"),
            ):
                with self.assertRaises(SystemExit) as ctx:
                    main([])

        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
