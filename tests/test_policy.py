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

        with self.assertRaisesRegex(PolicyError, "components"):
            policy.validate_update_fields({"summary": "x", "components": []})

        self.assertEqual(
            policy.validate_update_fields({"customfield_12345": "ok"}),
            {"customfield_12345": "ok"},
        )

    def test_rejects_issuelinks_update_field_with_tool_hint(self):
        policy = JiraPolicy.create(("ISD",))

        with self.assertRaisesRegex(PolicyError, "jira_link_issues"):
            policy.validate_update_fields({"issuelinks": []})

    def test_rejects_status_update_field_with_tool_hint(self):
        policy = JiraPolicy.create(("ISD",))

        with self.assertRaisesRegex(PolicyError, "jira_transition_issue"):
            policy.validate_update_fields({"status": {"name": "Rejected"}})

    def test_reports_issue_allowlist_membership(self):
        policy = JiraPolicy.create(("ISD", "ISREQ"))

        self.assertTrue(policy.is_issue_allowed("isreq-5090"))
        self.assertFalse(policy.is_issue_allowed("NDA-1"))
        self.assertFalse(policy.is_issue_allowed("not-a-key"))

    def test_validates_parent_field_project(self):
        policy = JiraPolicy.create(("ISD",))

        self.assertEqual(
            policy.validate_update_fields({"parent": {"key": "ISD-5444"}}),
            {"parent": {"key": "ISD-5444"}},
        )

        with self.assertRaisesRegex(PolicyError, "NDA"):
            policy.validate_update_fields({"parent": {"key": "NDA-1"}})

    # Test Task 4: Preserve ORDER BY when wrapping JQL
    def test_wrap_jql_preserves_order_by(self):
        """Test that ORDER BY clauses are preserved when wrapping JQL"""
        policy = JiraPolicy.create(("ISD", "ABC"))
        
        with self.subTest("ORDER BY at end"):
            self.assertEqual(
                policy.wrap_jql("status = Done ORDER BY created ASC"),
                "project in (ABC, ISD) AND (status = Done) ORDER BY created ASC",
            )
            
        with self.subTest("ORDER BY inside quotes, no split"):
            self.assertEqual(
                policy.wrap_jql('summary ~ "please order by date"'),
                "project in (ABC, ISD) AND (summary ~ \"please order by date\")",
            )
            
        with self.subTest("ORDER BY after quoted occurrence"):
            self.assertEqual(
                policy.wrap_jql('text = "order by x" ORDER BY created'),
                "project in (ABC, ISD) AND (text = \"order by x\") ORDER BY created",
            )
            
        with self.subTest("Only ORDER BY, no body"):
            self.assertEqual(
                policy.wrap_jql("order by created"),
                "project in (ABC, ISD) order by created",
            )
            
        with self.subTest("ORDER BY with single quotes, lowercase"):
            self.assertEqual(
                policy.wrap_jql("status = 'open' order by key desc"),
                "project in (ABC, ISD) AND (status = 'open') order by key desc",
            )

        with self.subTest("ORDER BY with double space"):
            self.assertEqual(
                policy.wrap_jql("status = Done ORDER  BY created"),
                "project in (ABC, ISD) AND (status = Done) ORDER  BY created",
            )

        with self.subTest("escaped quote inside string, real ORDER BY after"):
            self.assertEqual(
                policy.wrap_jql('text ~ "a\\"b" ORDER BY created'),
                'project in (ABC, ISD) AND (text ~ "a\\"b") ORDER BY created',
            )

        with self.subTest("quoted field name in ORDER BY clause"):
            self.assertEqual(
                policy.wrap_jql('status = Done ORDER BY "Order By Date"'),
                'project in (ABC, ISD) AND (status = Done) ORDER BY "Order By Date"',
            )


if __name__ == "__main__":
    unittest.main()
