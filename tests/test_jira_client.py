import unittest
from dataclasses import dataclass
from typing import Any

from restricted_jira_mcp.config import JiraConfig
from restricted_jira_mcp.jira_client import JiraClient, adf_doc
from restricted_jira_mcp.policy import JiraPolicy, PolicyError


@dataclass
class FakeResponse:
    status_code: int
    payload: dict[str, Any] | None = None

    @property
    def content(self):
        return b"{}" if self.payload is not None else b""

    @property
    def text(self):
        return str(self.payload or "")

    def json(self):
        return self.payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")


class FakeSession:
    def __init__(self):
        self.auth = None
        self.headers = {}
        self.calls = []
        self.next_get = FakeResponse(200, issue_payload("ISD-5444", "ISD"))
        self.next_post = FakeResponse(200, {"issues": []})
        self.next_put = FakeResponse(204)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.next_get

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.next_post

    def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        return self.next_put


def issue_payload(key: str, project: str) -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "project": {"key": project},
            "issuetype": {"name": "Epic"},
            "status": {"name": "To Do"},
            "summary": "Example issue",
            "labels": [],
        },
    }


def client(session: FakeSession) -> JiraClient:
    config = JiraConfig(
        base_url="https://example.atlassian.net",
        email="user@example.com",
        api_token="token",
        allowed_projects=("ISD",),
        allowed_custom_fields=("customfield_12345",),
    )
    return JiraClient(config, JiraPolicy.create(("ISD",), ("customfield_12345",)), session)


class JiraClientTests(unittest.TestCase):
    def test_get_issue_rejects_disallowed_key_before_http(self):
        session = FakeSession()

        with self.assertRaises(PolicyError):
            client(session).get_issue("NDA-123")

        self.assertEqual(session.calls, [])

    def test_get_issue_compacts_allowed_response(self):
        session = FakeSession()

        issue = client(session).get_issue("ISD-5444")

        self.assertEqual(issue["key"], "ISD-5444")
        self.assertEqual(issue["project"], "ISD")
        self.assertEqual(session.calls[0][0], "GET")

    def test_search_wraps_jql_and_validates_results(self):
        session = FakeSession()
        session.next_post = FakeResponse(200, {"total": 1, "issues": [issue_payload("ISD-5444", "ISD")]})

        result = client(session).search("status = Done")

        request_json = session.calls[0][2]["json"]
        self.assertEqual(request_json["jql"], "project in (ISD) AND (status = Done)")
        self.assertEqual(result["issues"][0]["key"], "ISD-5444")

    def test_search_rejects_unexpected_response_project(self):
        session = FakeSession()
        session.next_post = FakeResponse(200, {"total": 1, "issues": [issue_payload("NDA-1", "NDA")]})

        with self.assertRaises(PolicyError):
            client(session).search("")

    def test_update_normalizes_description_and_rejects_unsupported_fields(self):
        session = FakeSession()

        client(session).update_issue("ISD-5444", {"description": "hello"})

        request_json = session.calls[0][2]["json"]
        self.assertEqual(request_json["fields"]["description"], adf_doc("hello"))

        with self.assertRaises(PolicyError):
            client(session).update_issue("ISD-5444", {"fixVersions": []})


if __name__ == "__main__":
    unittest.main()
