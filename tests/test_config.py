import json
import tempfile
import unittest
from pathlib import Path

from restricted_jira_mcp.config import HTTPConfig, JiraConfig, ServerConfig, load_config


def _jira_section(**overrides):
    section = {
        "base_url": "https://example.atlassian.net/",
        "email": "test@example.com",
        "api_token": "secret",
        "allowed_projects": ["PROJ1", "PROJ2"],
    }
    section.update(overrides)
    return section


def _http_section(**overrides):
    section = {
        "bind_address": "10.0.0.1:8000",
        "client_token": "token-a",
    }
    section.update(overrides)
    return section


class TestLoadConfig(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "config.json"

    def _load(self, data):
        self.path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
        return load_config(self.path)

    def test_loads_full_config(self):
        # Happy path: both sections parse, the base URL loses its trailing slash, and an
        # omitted http section means stdio-only (http is None).
        config = self._load({
            "jira": _jira_section(allowed_custom_fields=["customfield_1"]),
            "http": _http_section(allowed_hosts=["jira-mcp.lan:8000"]),
        })

        self.assertEqual(
            config,
            ServerConfig(
                jira=JiraConfig(
                    base_url="https://example.atlassian.net",
                    email="test@example.com",
                    api_token="secret",
                    allowed_projects=("PROJ1", "PROJ2"),
                    allowed_custom_fields=("customfield_1",),
                ),
                http=HTTPConfig(
                    host="10.0.0.1",
                    port=8000,
                    allowed_hosts=("jira-mcp.lan:8000",),
                    client_token="token-a",
                ),
            ),
        )
        self.assertIsNone(self._load({"jira": _jira_section()}).http)

    def test_parses_ipv6_bind_address(self):
        # A bracketed IPv6 bind address yields the bare address uvicorn binds to.
        config = self._load({"jira": _jira_section(), "http": _http_section(bind_address="[::1]:9000")})

        self.assertEqual((config.http.host, config.http.port), ("::1", 9000))

    def test_rejects_invalid_config(self):
        # Every unusable config must fail closed at load time with a ValueError naming the problem.
        cases = {
            "malformed json": ("{not json", "config.json"),
            "top level not an object": ([], "object"),
            "missing jira section": ({}, "jira"),
            "unknown top-level key": ({"jira": _jira_section(), "htpp": {}}, "htpp"),
            "unknown jira key": ({"jira": _jira_section(allowed_project=["X"])}, "allowed_project"),
            "missing api token": (
                {"jira": {k: v for k, v in _jira_section().items() if k != "api_token"}},
                "api_token",
            ),
            "placeholder api token": ({"jira": _jira_section(api_token="CHANGE_ME")}, "api_token"),
            "empty email": ({"jira": _jira_section(email="")}, "email"),
            "projects not a list": ({"jira": _jira_section(allowed_projects="ISD,ISREQ")}, "allowed_projects"),
            "empty projects": ({"jira": _jira_section(allowed_projects=[])}, "allowed_projects"),
            "unknown http key": ({"jira": _jira_section(), "http": _http_section(port=1)}, "port"),
            "bind address without port": (
                {"jira": _jira_section(), "http": _http_section(bind_address="10.0.0.1")},
                "bind_address",
            ),
            "empty bracketed host": (
                {"jira": _jira_section(), "http": _http_section(bind_address="[]:8000")},
                "bind_address",
            ),
            "non-numeric port": (
                {"jira": _jira_section(), "http": _http_section(bind_address="10.0.0.1:http")},
                "bind_address",
            ),
            "wildcard bind without allowed hosts": (
                {"jira": _jira_section(), "http": _http_section(bind_address="0.0.0.0:8000")},
                "allowed_hosts",
            ),
            "long-form ipv6 wildcard bind without allowed hosts": (
                {"jira": _jira_section(), "http": _http_section(bind_address="[0:0:0:0:0:0:0:0]:8000")},
                "allowed_hosts",
            ),
            "port out of range": (
                {"jira": _jira_section(), "http": _http_section(bind_address="10.0.0.1:65536")},
                "bind_address",
            ),
            "port zero": (
                {"jira": _jira_section(), "http": _http_section(bind_address="10.0.0.1:0")},
                "bind_address",
            ),
            "blank project entry": (
                {"jira": _jira_section(allowed_projects=["ISD", " "])},
                "allowed_projects",
            ),
            "placeholder allowed host": (
                {
                    "jira": _jira_section(),
                    "http": _http_section(bind_address="0.0.0.0:8000", allowed_hosts=["CHANGE_ME"]),
                },
                "allowed_hosts",
            ),
            "missing client token": (
                {"jira": _jira_section(), "http": {"bind_address": "10.0.0.1:8000"}},
                "client_token",
            ),
            "placeholder client token": (
                {"jira": _jira_section(), "http": _http_section(client_token="CHANGE_ME")},
                "client_token",
            ),
            "empty client token": ({"jira": _jira_section(), "http": _http_section(client_token="")}, "client_token"),
        }
        for label, (data, expected_in_message) in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(ValueError) as ctx:
                    self._load(data)
                self.assertIn(expected_in_message, str(ctx.exception))

    def test_missing_file_raises_value_error_naming_the_path(self):
        # An unreadable path is a config error, not a bare OSError traceback.
        missing = self.path.parent / "nope.json"
        with self.assertRaises(ValueError) as ctx:
            load_config(missing)
        self.assertIn(str(missing), str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
