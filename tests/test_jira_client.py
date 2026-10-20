import unittest
from dataclasses import dataclass
from typing import Any

from restricted_jira_mcp.config import JiraConfig
from restricted_jira_mcp.jira_client import JiraClient, JiraClientError, adf_doc
from restricted_jira_mcp.policy import JiraPolicy, PolicyError
from restricted_jira_mcp.adf import as_adf


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
        self.next_delete = FakeResponse(204)
        self.get_responses = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if self.get_responses:
            return self.get_responses.pop(0)
        return self.next_get

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.next_post

    def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        return self.next_put

    def delete(self, url, **kwargs):
        self.calls.append(("DELETE", url, kwargs))
        return self.next_delete


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


def client(session: FakeSession, projects: tuple[str, ...] = ("ISD",)) -> JiraClient:
    config = JiraConfig(
        base_url="https://example.atlassian.net",
        email="user@example.com",
        api_token="token",
        allowed_projects=projects,
        allowed_custom_fields=("customfield_12345",),
    )
    return JiraClient(config, JiraPolicy.create(projects, ("customfield_12345",)), session)


def link_payload(direction: str, key: str) -> dict[str, Any]:
    return {
        "type": {"name": "Relates", "inward": "relates to", "outward": "relates to"},
        direction: {"key": key, "fields": {"summary": "Linked issue", "status": {"name": "To Do"}}},
    }


def comment_payload(comment_id: str, text: str) -> dict[str, Any]:
    return {
        "id": comment_id,
        "author": {
            "accountId": "acc-1",
            "displayName": "Alice",
            "emailAddress": "alice@example.com",
        },
        "body": adf_doc(text),
        "created": "2026-01-01T10:00:00.000+0000",
        "updated": "2026-01-02T10:00:00.000+0000",
    }


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

    def test_get_issue_returns_full_description(self):
        # get_issue returns the whole rendered description: no "..." and no truncation flag.
        session = FakeSession()
        description_text = "x" * 900
        payload = issue_payload("ISD-5444", "ISD")
        payload["fields"]["description"] = adf_doc(description_text)
        session.next_get = FakeResponse(200, payload)

        issue = client(session).get_issue("ISD-5444")

        self.assertEqual(issue["description"], description_text)
        self.assertNotIn("...", issue["description"])
        self.assertNotIn("description_truncated", issue)

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

    def test_search_flags_truncated_descriptions(self):
        # Search results excerpt descriptions at 800 chars and flag whether truncation happened.
        cases = [
            ("within_limit", "x" * 800, "x" * 800, False),
            ("over_limit", "x" * 810, "x" * 800 + "...", True),
        ]
        for label, description_text, expected_description, expected_truncated in cases:
            with self.subTest(label):
                session = FakeSession()
                payload = issue_payload("ISD-5444", "ISD")
                payload["fields"]["description"] = adf_doc(description_text)
                session.next_post = FakeResponse(200, {"total": 1, "issues": [payload]})

                result = client(session).search("status = Done")

                issue = result["issues"][0]
                self.assertEqual(issue["description"], expected_description)
                self.assertEqual(issue["description_truncated"], expected_truncated)

    def test_update_normalizes_description_and_rejects_unsupported_fields(self):
        session = FakeSession()

        client(session).update_issue("ISD-5444", {"description": "hello"})

        request_json = session.calls[0][2]["json"]
        self.assertEqual(request_json["fields"]["description"], adf_doc("hello"))

        with self.assertRaises(PolicyError):
            client(session).update_issue("ISD-5444", {"fixVersions": []})

    def test_create_issue_sets_parent_epic(self):
        session = FakeSession()
        session.next_post = FakeResponse(201, {"key": "ISD-5445"})

        result = client(session).create_issue(
            project_key="ISD",
            issue_type="Story",
            summary="Example story",
            parent_epic_key="isd-5444",
        )

        request_json = session.calls[0][2]["json"]
        self.assertEqual(result["key"], "ISD-5445")
        self.assertEqual(request_json["fields"]["parent"], {"key": "ISD-5444"})

    def test_create_issue_rejects_disallowed_parent_epic_before_http(self):
        session = FakeSession()

        with self.assertRaises(PolicyError):
            client(session).create_issue(
                project_key="ISD",
                issue_type="Story",
                summary="Example story",
                parent_epic_key="NDA-1",
            )

        self.assertEqual(session.calls, [])

    def test_link_issues_posts_normalized_keys(self):
        session = FakeSession()
        session.next_post = FakeResponse(201)

        result = client(session, ("ISD", "ISREQ")).link_issues("isd-5444", "isreq-5090")

        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/rest/api/3/issueLink"))
        self.assertEqual(
            kwargs["json"],
            {
                "type": {"name": "Relates"},
                "inwardIssue": {"key": "ISD-5444"},
                "outwardIssue": {"key": "ISREQ-5090"},
            },
        )
        self.assertEqual(result["status"], "linked")

    def test_link_issues_rejects_disallowed_projects_before_http(self):
        session = FakeSession()

        with self.assertRaises(PolicyError):
            client(session).link_issues("ISD-5444", "ISREQ-5090")
        with self.assertRaises(PolicyError):
            client(session).link_issues("NDA-1", "ISD-5444")

        self.assertEqual(session.calls, [])

    def test_get_issue_hides_links_to_disallowed_projects(self):
        session = FakeSession()
        payload = issue_payload("ISD-5444", "ISD")
        payload["fields"]["issuelinks"] = [
            link_payload("outwardIssue", "ISREQ-5090"),
            link_payload("inwardIssue", "NDA-1"),
        ]
        session.next_get = FakeResponse(200, payload)

        issue = client(session, ("ISD", "ISREQ")).get_issue("ISD-5444")

        self.assertEqual(
            issue["links"],
            [
                {
                    "link_type": "Relates",
                    "relation": "relates to",
                    "issue_key": "ISREQ-5090",
                    "summary": "Linked issue",
                    "status": "To Do",
                }
            ],
        )

    def test_get_comments_rejects_disallowed_key_before_http(self):
        session = FakeSession()

        with self.assertRaises(PolicyError):
            client(session).get_comments("NDA-123")

        self.assertEqual(session.calls, [])

    def test_get_comments_rejects_issue_resolved_to_disallowed_project(self):
        # A historical key can resolve after an issue moved; the resolved
        # project decides, not the key prefix.
        session = FakeSession()
        session.get_responses = [FakeResponse(200, issue_payload("ISD-5444", "NDA"))]

        with self.assertRaises(PolicyError):
            client(session).get_comments("ISD-5444")

        self.assertEqual(len(session.calls), 1)
        self.assertTrue(session.calls[0][1].endswith("/rest/api/3/issue/ISD-5444"))

    def test_add_comment_rejects_issue_resolved_to_disallowed_project(self):
        session = FakeSession()
        session.get_responses = [FakeResponse(200, issue_payload("ISD-5444", "NDA"))]

        with self.assertRaises(PolicyError):
            client(session).add_comment("ISD-5444", "hi")

        self.assertEqual(len(session.calls), 1)
        self.assertTrue(session.calls[0][1].endswith("/rest/api/3/issue/ISD-5444"))

    def test_update_comment_rejects_issue_resolved_to_disallowed_project(self):
        session = FakeSession()
        session.get_responses = [FakeResponse(200, issue_payload("ISD-5444", "NDA"))]

        with self.assertRaises(PolicyError):
            client(session).update_comment("ISD-5444", "10001", "new text")

        self.assertEqual(len(session.calls), 1)
        self.assertTrue(session.calls[0][1].endswith("/rest/api/3/issue/ISD-5444"))

    def test_get_comments_uses_resolved_canonical_key(self):
        # When Jira answers a historical key with the moved issue's current
        # key, later comment requests target the canonical key.
        session = FakeSession()
        session.get_responses = [
            FakeResponse(200, issue_payload("ISD-9999", "ISD")),
            FakeResponse(200, {"startAt": 0, "maxResults": 50, "total": 0, "comments": []}),
        ]

        result = client(session).get_comments("isd-5444")

        self.assertEqual(result["issue_key"], "ISD-9999")
        self.assertTrue(session.calls[1][1].endswith("/rest/api/3/issue/ISD-9999/comment"))

    def test_get_comments_returns_paged_flattened_comments(self):
        session = FakeSession()
        session.get_responses = [
            FakeResponse(200, issue_payload("ISD-5444", "ISD")),
            FakeResponse(
                200,
                {
                    "startAt": 0,
                    "maxResults": 50,
                    "total": 1,
                    "comments": [comment_payload("10001", "Looks good to me")],
                },
            ),
        ]

        result = client(session).get_comments("isd-5444", max_results=200, start_at=5)

        method, url, kwargs = session.calls[1]
        self.assertEqual(method, "GET")
        self.assertTrue(url.endswith("/rest/api/3/issue/ISD-5444/comment"))
        self.assertEqual(
            kwargs["params"],
            {"startAt": 5, "maxResults": 50, "orderBy": "created"},
        )
        self.assertEqual(result["issue_key"], "ISD-5444")
        self.assertEqual(result["total"], 1)
        self.assertEqual(
            result["comments"],
            [
                {
                    "id": "10001",
                    "author": {
                        "accountId": "acc-1",
                        "displayName": "Alice",
                        "emailAddress": "alice@example.com",
                    },
                    "body": "Looks good to me",
                    "created": "2026-01-01T10:00:00.000+0000",
                    "updated": "2026-01-02T10:00:00.000+0000",
                    "visibility": None,
                    "public": True,
                }
            ],
        )

    def test_get_comments_reports_restricted_visibility(self):
        session = FakeSession()
        restricted = comment_payload("10002", "Internal note")
        restricted["visibility"] = {"type": "role", "value": "Administrators"}
        restricted["jsdPublic"] = False
        session.get_responses = [
            FakeResponse(200, issue_payload("ISD-5444", "ISD")),
            FakeResponse(200, {"total": 1, "comments": [restricted]}),
        ]

        result = client(session).get_comments("ISD-5444")

        comment = result["comments"][0]
        self.assertEqual(comment["visibility"], "role: Administrators")
        self.assertFalse(comment["public"])

    def test_get_comments_returns_full_body(self):
        # get_comments returns comment bodies in full, without any truncation marker.
        session = FakeSession()
        body_text = "y" * 2500
        session.get_responses = [
            FakeResponse(200, issue_payload("ISD-5444", "ISD")),
            FakeResponse(
                200,
                {
                    "startAt": 0,
                    "maxResults": 50,
                    "total": 1,
                    "comments": [comment_payload("10001", body_text)],
                },
            ),
        ]

        result = client(session).get_comments("ISD-5444")

        comment = result["comments"][0]
        self.assertEqual(comment["body"], body_text)
        self.assertNotIn("...", comment["body"])

    def test_update_normalizes_and_validates_parent(self):
        session = FakeSession()

        client(session).update_issue("ISD-5445", {"parent": "isd-5444"})

        request_json = session.calls[0][2]["json"]
        self.assertEqual(request_json["fields"]["parent"], {"key": "ISD-5444"})

        with self.assertRaises(PolicyError):
            client(session).update_issue("ISD-5445", {"parent": {"key": "NDA-1"}})

    def test_update_issue_converts_markdown_description(self):
        """Test that update_issue converts Markdown description to ADF."""
        session = FakeSession()
        
        client(session).update_issue("ISD-5444", {"description": "## Plan\n\n- do it"})
        
        request_json = session.calls[0][2]["json"]
        description = request_json["fields"]["description"]
        self.assertEqual(description["type"], "doc")
        self.assertEqual(description["version"], 1)
        
        # Check for heading with level 2
        heading = next((node for node in description["content"] if node.get("type") == "heading"), None)
        self.assertIsNotNone(heading)
        self.assertEqual(heading["attrs"]["level"], 2)
        
        # Check for bullet list
        bullet_list = next((node for node in description["content"] if node.get("type") == "bulletList"), None)
        self.assertIsNotNone(bullet_list)
        self.assertEqual(len(bullet_list["content"]), 1)

    def test_update_issue_passes_raw_adf_description(self):
        """Test that update_issue passes through raw ADF description unchanged."""
        session = FakeSession()
        raw_adf = adf_doc("raw")
        
        client(session).update_issue("ISD-5444", {"description": raw_adf})
        
        request_json = session.calls[0][2]["json"]
        self.assertEqual(request_json["fields"]["description"], raw_adf)

    def test_update_issue_rejects_invalid_adf_description(self):
        """Test that update_issue rejects invalid ADF description with ValueError."""
        session = FakeSession()
        
        with self.assertRaises(ValueError) as cm:
            client(session).update_issue("ISD-5444", {"description": {"type": "paragraph"}})
        
        self.assertIn("must be a Markdown string or an ADF doc object", str(cm.exception))
        self.assertEqual(session.calls, [])  # No session calls should be made

    def test_create_issue_converts_markdown_description(self):
        """Test that create_issue converts Markdown description to ADF."""
        session = FakeSession()
        session.next_post = FakeResponse(201, {"key": "ISD-5445"})
        
        client(session).create_issue(
            project_key="ISD",
            issue_type="Story",
            summary="Example story",
            description="## Plan\n\n- do it"
        )
        
        request_json = session.calls[0][2]["json"]
        description = request_json["fields"]["description"]
        self.assertEqual(description["type"], "doc")
        self.assertEqual(description["version"], 1)
        
        # Check for heading with level 2
        heading = next((node for node in description["content"] if node.get("type") == "heading"), None)
        self.assertIsNotNone(heading)
        self.assertEqual(heading["attrs"]["level"], 2)
        
        # Check for bullet list
        bullet_list = next((node for node in description["content"] if node.get("type") == "bulletList"), None)
        self.assertIsNotNone(bullet_list)
        self.assertEqual(len(bullet_list["content"]), 1)

    def test_add_comment_converts_markdown_body(self):
        """Test that add_comment converts Markdown body to ADF."""
        session = FakeSession()
        session.get_responses = [FakeResponse(200, issue_payload("ISD-5444", "ISD"))]
        session.next_post = FakeResponse(201, {"id": "10001"})

        client(session).add_comment("ISD-5444", "Hello **world**")

        request_json = session.calls[1][2]["json"]
        body = request_json["body"]
        self.assertEqual(body["type"], "doc")
        self.assertEqual(body["version"], 1)
        
        # Check for strong mark in the text
        paragraph = next((node for node in body["content"] if node.get("type") == "paragraph"), None)
        self.assertIsNotNone(paragraph)
        
        # The first text node is "Hello " with no marks
        text_node1 = paragraph["content"][0]
        self.assertEqual(text_node1["text"], "Hello ")
        self.assertNotIn("marks", text_node1)
        
        # The second text node is "world" with strong marks
        text_node2 = paragraph["content"][1]
        self.assertEqual(text_node2["text"], "world")
        self.assertEqual(text_node2["marks"][0]["type"], "strong")

    def test_get_issue_requests_and_returns_custom_fields(self):
        """Test that get_issue requests and returns allowlisted custom fields."""
        # Create a payload with an ADF custom field
        session = FakeSession()
        payload = issue_payload("ISD-5444", "ISD")
        payload["fields"]["customfield_12345"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Acceptance: it works"}],
                }
            ],
        }
        session.next_get = FakeResponse(200, payload)

        issue = client(session).get_issue("ISD-5444")

        # Check that the custom field was requested
        request_params = session.calls[0][2]["params"]
        self.assertIn("customfield_12345", request_params["fields"])
        
        # Check that the custom field is returned in the response
        self.assertIn("custom_fields", issue)
        self.assertEqual(issue["custom_fields"], {"customfield_12345": "Acceptance: it works"})

    def test_get_issue_passes_through_scalar_custom_field(self):
        """Test that get_issue passes through scalar custom fields unchanged."""
        session = FakeSession()
        payload = issue_payload("ISD-5444", "ISD")
        payload["fields"]["customfield_12345"] = "42"
        session.next_get = FakeResponse(200, payload)

        issue = client(session).get_issue("ISD-5444")

        # Check that the scalar custom field is returned unchanged
        self.assertIn("custom_fields", issue)
        self.assertEqual(issue["custom_fields"], {"customfield_12345": "42"})

    def test_get_issue_dumps_non_adf_dict_custom_field(self):
        """Test that get_issue dumps non-ADF dict custom fields as JSON."""
        import json
        session = FakeSession()
        payload = issue_payload("ISD-5444", "ISD")
        payload["fields"]["customfield_12345"] = {"value": "Blocked", "id": "1"}
        session.next_get = FakeResponse(200, payload)

        issue = client(session).get_issue("ISD-5444")

        # Check that the non-ADF dict custom field is JSON dumped
        self.assertIn("custom_fields", issue)
        expected_value = json.dumps({"value": "Blocked", "id": "1"})
        self.assertEqual(issue["custom_fields"], {"customfield_12345": expected_value})

    def test_search_does_not_request_custom_fields(self):
        """Test that search does not request custom fields."""
        session = FakeSession()
        session.next_post = FakeResponse(200, {"total": 1, "issues": [issue_payload("ISD-5444", "ISD")]})

        client(session).search("status = Done")

        # Check that the search request does not include custom fields
        request_json = session.calls[0][2]["json"]
        fields = request_json["fields"]
        self.assertNotIn("customfield_12345", fields)

    def test_update_comment_puts_adf_body_to_scoped_path(self):
        """Test that update_comment puts ADF body to the scoped path."""
        from restricted_jira_mcp.adf import as_adf

        session = FakeSession()
        # Set up get_responses queue for issue resolution, myself and comment
        session.get_responses = [
            FakeResponse(200, issue_payload("ISD-5444", "ISD")),
            FakeResponse(200, {"accountId": "acc-1"}),
            FakeResponse(200, comment_payload("10001", "old")),
        ]

        result = client(session).update_comment("ISD-5444", "10001", "new text")

        # Check call sequence: resolve issue, myself, comment, then PUT
        self.assertEqual(len(session.calls), 4)
        self.assertEqual(session.calls[1], ("GET", "https://example.atlassian.net/rest/api/3/myself", {"timeout": 30}))
        self.assertEqual(session.calls[2], ("GET", "https://example.atlassian.net/rest/api/3/issue/ISD-5444/comment/10001", {"timeout": 30}))
        self.assertEqual(session.calls[3][0], "PUT")
        self.assertTrue(session.calls[3][1].endswith("/rest/api/3/issue/ISD-5444/comment/10001"))
        self.assertEqual(session.calls[3][2]["json"], {"body": as_adf("new text")})

        # Check result
        self.assertEqual(result, {"status": "updated", "issue_key": "ISD-5444", "comment_id": "10001"})

    def test_update_comment_rejects_foreign_author(self):
        """Test that update_comment rejects comments authored by foreign users."""
        session = FakeSession()
        # Set up get_responses queue for issue resolution, myself and comment
        foreign_comment_payload = comment_payload("10001", "old")
        foreign_comment_payload["author"]["accountId"] = "acc-2"  # Foreign author
        session.get_responses = [
            FakeResponse(200, issue_payload("ISD-5444", "ISD")),
            FakeResponse(200, {"accountId": "acc-1"}),
            FakeResponse(200, foreign_comment_payload),
        ]

        with self.assertRaises(JiraClientError) as cm:
            client(session).update_comment("ISD-5444", "10001", "new text")

        self.assertIn("own comments", str(cm.exception))
        self.assertIn("10001", str(cm.exception))

        # Check that only GET calls were made
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(session.calls[1], ("GET", "https://example.atlassian.net/rest/api/3/myself", {"timeout": 30}))
        self.assertEqual(session.calls[2], ("GET", "https://example.atlassian.net/rest/api/3/issue/ISD-5444/comment/10001", {"timeout": 30}))

    def test_delete_comment_deletes_scoped_path(self):
        """Test that delete_comment deletes the scoped path."""
        session = FakeSession()
        # Set up get_responses queue for issue resolution, myself and comment
        session.get_responses = [
            FakeResponse(200, issue_payload("ISD-5444", "ISD")),
            FakeResponse(200, {"accountId": "acc-1"}),
            FakeResponse(200, comment_payload("10001", "old")),
        ]

        result = client(session).delete_comment("ISD-5444", "10001")

        # Check call sequence: resolve issue, myself, comment, then DELETE
        self.assertEqual(len(session.calls), 4)
        self.assertEqual(session.calls[1], ("GET", "https://example.atlassian.net/rest/api/3/myself", {"timeout": 30}))
        self.assertEqual(session.calls[2], ("GET", "https://example.atlassian.net/rest/api/3/issue/ISD-5444/comment/10001", {"timeout": 30}))
        self.assertEqual(session.calls[3], ("DELETE", "https://example.atlassian.net/rest/api/3/issue/ISD-5444/comment/10001", {"timeout": 30}))

        # Check result
        self.assertEqual(result, {"status": "deleted", "issue_key": "ISD-5444", "comment_id": "10001"})

    def test_myself_called_once_across_operations(self):
        """Test that /myself endpoint is called only once across multiple operations."""
        session = FakeSession()
        comment_payload_data = comment_payload("10001", "old")
        session.get_responses = [
            FakeResponse(200, issue_payload("ISD-5444", "ISD")),
            FakeResponse(200, {"accountId": "acc-1"}),
            FakeResponse(200, comment_payload_data),
            FakeResponse(200, issue_payload("ISD-5444", "ISD")),
            FakeResponse(200, comment_payload_data),
        ]

        # Make two update_comment calls on the same client instance
        client_instance = client(session)
        client_instance.update_comment("ISD-5444", "10001", "new text 1")
        client_instance.update_comment("ISD-5444", "10001", "new text 2")

        # Check that /myself was called only once
        myself_calls = [call for call in session.calls if call[1].endswith("/rest/api/3/myself")]
        self.assertEqual(len(myself_calls), 1)

        # Verify the total number of calls (2 issue GETs + myself + 2 comment GETs + 2 PUTs)
        self.assertEqual(len(session.calls), 7)

    def test_comment_edit_delete_error_cases(self):
        """Test error cases for comment edit/delete operations."""
        # Test disallowed issue key
        with self.subTest("disallowed issue key"):
            session = FakeSession()
            with self.assertRaises(PolicyError):
                client(session).update_comment("NDA-123", "10001", "new text")
            self.assertEqual(session.calls, [])
        
        with self.subTest("disallowed issue key - delete"):
            session = FakeSession()
            with self.assertRaises(PolicyError):
                client(session).delete_comment("NDA-123", "10001")
            self.assertEqual(session.calls, [])
        
        # Test malformed comment IDs
        with self.subTest("malformed comment ID - update"):
            session = FakeSession()
            with self.assertRaises(ValueError):
                client(session).update_comment("ISD-5444", "10001/../x", "new text")
            self.assertEqual(session.calls, [])
        
        with self.subTest("malformed comment ID - delete"):
            session = FakeSession()
            with self.assertRaises(ValueError):
                client(session).delete_comment("ISD-5444", "abc")
            self.assertEqual(session.calls, [])
        
        # Test 404 comment
        with self.subTest("404 comment"):
            session = FakeSession()
            session.get_responses = [
                FakeResponse(200, issue_payload("ISD-5444", "ISD")),
                FakeResponse(200, {"accountId": "acc-1"}),
                FakeResponse(404),
            ]
            with self.assertRaises(JiraClientError) as cm:
                client(session).update_comment("ISD-5444", "99999", "new text")
            self.assertIn("99999", str(cm.exception))
            self.assertEqual(len(session.calls), 3)  # Only GET calls


if __name__ == "__main__":
    unittest.main()
