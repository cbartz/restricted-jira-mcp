import unittest

from restricted_jira_mcp.policy import JiraPolicy, PolicyError


class JiraPolicyTests(unittest.TestCase):
    def test_extracts_project_from_issue_key(self):
        policy = JiraPolicy.create(("ISD",))

        self.assertEqual(policy.project_from_issue_key("ISD-5444"), "ISD")

    def test_rejects_disallowed_issue_before_http(self):
        policy = JiraPolicy.create(("ISD",))

        with self.assertRaisesRegex(PolicyError, "NDA"):
            policy.ensure_issue_allowed("NDA-123")

    def test_wraps_jql_with_allowlisted_projects(self):
        policy = JiraPolicy.create(("ISD", "ABC"))

        self.assertEqual(
            policy.wrap_jql("status = Done"),
            "project in (ABC, ISD) AND (status = Done)",
        )

    def test_rejects_unsupported_update_fields(self):
        policy = JiraPolicy.create(("ISD",), allowed_custom_fields=("customfield_12345",))

        with self.assertRaisesRegex(PolicyError, "fixVersions"):
            policy.validate_update_fields({"summary": "x", "fixVersions": []})

        self.assertEqual(
            policy.validate_update_fields({"customfield_12345": "ok"}),
            {"customfield_12345": "ok"},
        )

    def test_validates_parent_field_project(self):
        policy = JiraPolicy.create(("ISD",))

        self.assertEqual(
            policy.validate_update_fields({"parent": {"key": "ISD-5444"}}),
            {"parent": {"key": "ISD-5444"}},
        )

        with self.assertRaisesRegex(PolicyError, "NDA"):
            policy.validate_update_fields({"parent": {"key": "NDA-1"}})


if __name__ == "__main__":
    unittest.main()
