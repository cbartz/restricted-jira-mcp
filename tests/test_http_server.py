"""Streamable-HTTP transport wiring tests: bearer auth gates the MCP endpoint."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from starlette.testclient import TestClient

import test_jira_client
from restricted_jira_mcp.config import HTTPConfig
from restricted_jira_mcp.server import build_http_app, create_server, main

CLIENT_TOKEN = "client-token-1"
HTTP_CONFIG = HTTPConfig(host="127.0.0.1", port=8000, client_token=CLIENT_TOKEN)
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

    def _post_tools_call(
        self,
        name: str,
        arguments: dict,
        headers: dict,
        http_config: HTTPConfig = HTTP_CONFIG,
        base_url: str = "http://127.0.0.1:8000",
    ):
        app = build_http_app(self.client, http_config)
        with TestClient(app, base_url=base_url) as http:
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
        # A bearer token that is not configured must get the same generic 401.
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

    def test_http_accepts_host_headers_on_the_allow_list(self):
        # Bound to a bridge address, the server accepts its own address, loopback, and
        # any configured allowed_hosts entry as the Host header.
        http_config = HTTPConfig(
            host="10.0.0.1",
            port=8000,
            allowed_hosts=("jira-mcp.lan:8000",),
            client_token=CLIENT_TOKEN,
        )
        for base_url in (
            "http://10.0.0.1:8000",
            "http://10.0.0.1",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            "http://jira-mcp.lan:8000",
        ):
            with self.subTest(base_url=base_url):
                response = self._post_tools_call(
                    "jira_get_issue",
                    {"issue_key": "ISD-5444"},
                    {"Authorization": f"Bearer {CLIENT_TOKEN}"},
                    http_config=http_config,
                    base_url=base_url,
                )
                self.assertEqual(response.status_code, 200)

    def test_http_rejects_unlisted_host_and_origin_headers(self):
        # DNS-rebinding protection stays on for non-loopback binds: an unknown Host gets
        # 421 and a foreign Origin gets 403, even with a valid token.
        http_config = HTTPConfig(host="10.0.0.1", port=8000, client_token=CLIENT_TOKEN)
        cases = {
            "unlisted host": ("http://evil.example:8000", {}, 421),
            "foreign origin": ("http://10.0.0.1:8000", {"Origin": "http://evil.example"}, 403),
        }
        for label, (base_url, extra_headers, status) in cases.items():
            with self.subTest(label=label):
                response = self._post_tools_call(
                    "jira_get_issue",
                    {"issue_key": "ISD-5444"},
                    {"Authorization": f"Bearer {CLIENT_TOKEN}", **extra_headers},
                    http_config=http_config,
                    base_url=base_url,
                )
                self.assertEqual(response.status_code, status)
        self.assertEqual(self.session.calls, [])

    def test_http_add_comment_accepts_raw_adf_dict_body(self):
        # A raw ADF doc dict body must pass FastMCP's schema validation and reach
        # Jira as exactly that dict, not die on "Input should be a valid string".
        adf_body = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "raw adf"}]},
            ],
        }
        response = self._post_tools_call(
            "jira_add_comment",
            {"issue_key": "ISD-5444", "body": adf_body},
            {"Authorization": f"Bearer {CLIENT_TOKEN}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["result"].get("isError", False))
        # The issue-resolution GET precedes the comment POST.
        self.assertEqual(len(self.session.calls), 2)
        method, url, kwargs = self.session.calls[1]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/rest/api/3/issue/ISD-5444/comment"))
        self.assertEqual(kwargs["json"], {"body": adf_body})

    def test_http_create_issue_accepts_raw_adf_dict_description(self):
        # A raw ADF doc dict description must pass schema validation unchanged too.
        adf_description = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "raw adf"}]},
            ],
        }
        response = self._post_tools_call(
            "jira_create_issue",
            {
                "project_key": "ISD",
                "issue_type": "Story",
                "summary": "S",
                "description": adf_description,
            },
            {"Authorization": f"Bearer {CLIENT_TOKEN}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["result"].get("isError", False))
        self.assertEqual(len(self.session.calls), 1)
        method, url, kwargs = self.session.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/rest/api/3/issue"))
        self.assertEqual(
            kwargs["json"],
            {
                "fields": {
                    "project": {"key": "ISD"},
                    "issuetype": {"name": "Story"},
                    "summary": "S",
                    "description": adf_description,
                }
            },
        )


class CreateServerTests(unittest.TestCase):
    """create_server() must register the full tool set on the injected client only."""

    def setUp(self):
        self.session = test_jira_client.FakeSession()
        self.client = test_jira_client.client(self.session)

    def _tool_names(self, mcp) -> list[str]:
        return sorted(tool.name for tool in mcp._tool_manager.list_tools())

    def test_create_server_registers_every_tool(self):
        # The stdio server exposes the full tool set over the given client.
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
                "jira_transition_issue",
                "jira_transitions",
                "jira_update_comment",
                "jira_update_issue",
            ],
        )


class MainEntrypointTests(unittest.TestCase):
    """main() must pick the transport and config file before touching Jira."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config_path = Path(tmp.name) / "config.json"
        self.config_data = {
            "jira": {
                "base_url": "https://example.atlassian.net",
                "email": "user@example.com",
                "api_token": "token",
                "allowed_projects": ["ISD"],
            },
            "http": {"bind_address": "10.0.0.1:9000", "client_token": CLIENT_TOKEN},
        }
        self._write_config()
        env_patcher = mock.patch.dict(
            os.environ,
            {
                key: value
                for key, value in os.environ.items()
                if key not in ("JIRA_MCP_TRANSPORT", "JIRA_MCP_CONFIG")
            },
            clear=True,
        )
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    def _write_config(self):
        self.config_path.write_text(json.dumps(self.config_data), encoding="utf-8")

    def test_help_exits_zero_before_any_config_load(self):
        # --help prints usage and exits 0 with no config file anywhere.
        with mock.patch(
            "restricted_jira_mcp.server.load_config",
            side_effect=AssertionError("config must not load before --help"),
        ):
            with self.assertRaises(SystemExit) as ctx:
                main(["--help"])

        self.assertEqual(ctx.exception.code, 0)

    def test_main_defaults_to_stdio_transport(self):
        # No transport flag or env: the stdio server runs via create_server().run(),
        # with the config named by --config.
        with mock.patch("mcp.server.fastmcp.FastMCP.run") as run:
            main(["--config", str(self.config_path)])

        run.assert_called_once_with()

    def test_main_transport_env_selects_http_from_config_env(self):
        # $JIRA_MCP_TRANSPORT=http with $JIRA_MCP_CONFIG serves the bearer-authenticated
        # app via uvicorn on the configured bind address.
        os.environ["JIRA_MCP_TRANSPORT"] = "http"
        os.environ["JIRA_MCP_CONFIG"] = str(self.config_path)
        with mock.patch(
            "restricted_jira_mcp.server.build_http_app", return_value="asgi-app"
        ) as build:
            with mock.patch("uvicorn.run") as run:
                main([])

        self.assertEqual(build.call_args.args[1].client_token, CLIENT_TOKEN)
        run.assert_called_once_with("asgi-app", host="10.0.0.1", port=9000)

    def test_main_fails_closed_on_unusable_startup_input(self):
        # Error cases: no config named, a typo in the transport env, and HTTP requested
        # from a config without an http section must all stop before serving.
        del self.config_data["http"]
        self._write_config()
        cases = {
            "no config path": ([], {}, SystemExit),
            "invalid transport env": (
                ["--config", str(self.config_path)],
                {"JIRA_MCP_TRANSPORT": "bogus"},
                SystemExit,
            ),
            "http without http section": (
                ["--config", str(self.config_path), "--transport", "http"],
                {},
                ValueError,
            ),
        }
        for label, (argv, env, error) in cases.items():
            with self.subTest(label=label):
                with mock.patch.dict(os.environ, env):
                    with mock.patch("uvicorn.run") as run:
                        with mock.patch("mcp.server.fastmcp.FastMCP.run") as stdio_run:
                            with self.assertRaises(error):
                                main(argv)
                run.assert_not_called()
                stdio_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
