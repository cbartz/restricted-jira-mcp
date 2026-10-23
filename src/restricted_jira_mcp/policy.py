from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def _split_order_by(jql: str) -> tuple[str, str | None]:
    """
    Split JQL at the last top-level ORDER BY clause (outside quotes).

    Backslash escapes are tracked so a quote inside a string literal
    (``text ~ "a\\"b"``) cannot desynchronise the quote state, and the clause
    itself may contain quoted field names (``ORDER BY "Order By Date"``).

    Args:
        jql: The JQL string to split

    Returns:
        tuple: (body, order_clause) where order_clause is None if no ORDER BY found
    """
    if not jql:
        return "", None

    jql = jql.strip()
    if not jql:
        return "", None

    positions = []
    in_single_quote = False
    in_double_quote = False
    escaped = False
    i = 0
    while i < len(jql):
        char = jql[i]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif in_double_quote:
            if char == '"':
                in_double_quote = False
        elif in_single_quote:
            if char == "'":
                in_single_quote = False
        elif char == '"':
            in_double_quote = True
        elif char == "'":
            in_single_quote = True
        else:
            match = _ORDER_BY_RE.match(jql, i)
            if (
                match
                and (i == 0 or jql[i - 1].isspace())
                and (match.end() == len(jql) or jql[match.end()].isspace())
            ):
                positions.append(i)
                i = match.end() - 1
        i += 1

    if not positions:
        return jql, None

    order_by_pos = positions[-1]
    body = jql[:order_by_pos].rstrip()
    order_clause = jql[order_by_pos:]
    
    return body, order_clause


ISSUE_KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*)-\d+$")

# The ORDER BY keyword, tolerating arbitrary whitespace between the words.
_ORDER_BY_RE = re.compile(r"order\s+by", re.IGNORECASE)
PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class PolicyError(ValueError):
    """Raised when a requested Jira operation violates the allowlist policy."""


@dataclass(frozen=True)
class JiraPolicy:
    allowed_projects: frozenset[str]
    allowed_custom_fields: frozenset[str] = frozenset()

    @classmethod
    def create(
        cls,
        allowed_projects: tuple[str, ...],
        allowed_custom_fields: tuple[str, ...] = (),
    ) -> "JiraPolicy":
        normalized_projects = frozenset(project.upper() for project in allowed_projects)
        invalid_projects = sorted(
            project for project in normalized_projects if not PROJECT_KEY_RE.match(project)
        )
        if not normalized_projects:
            raise PolicyError("At least one allowed Jira project is required")
        if invalid_projects:
            raise PolicyError(f"Invalid Jira project keys: {', '.join(invalid_projects)}")
        return cls(
            allowed_projects=normalized_projects,
            allowed_custom_fields=frozenset(allowed_custom_fields),
        )

    def project_from_issue_key(self, issue_key: str) -> str:
        match = ISSUE_KEY_RE.match(issue_key.upper())
        if not match:
            raise PolicyError(f"Invalid Jira issue key: {issue_key}")
        return match.group(1)

    def normalize_issue_key(self, issue_key: str) -> str:
        normalized = issue_key.upper()
        self.ensure_issue_allowed(normalized)
        return normalized

    def ensure_project_allowed(self, project_key: str) -> str:
        normalized = project_key.upper()
        if normalized not in self.allowed_projects:
            raise PolicyError(f"Project {normalized} is not allowlisted")
        return normalized

    def ensure_issue_allowed(self, issue_key: str) -> str:
        return self.ensure_project_allowed(self.project_from_issue_key(issue_key))

    def is_issue_allowed(self, issue_key: str) -> bool:
        try:
            self.ensure_issue_allowed(issue_key)
        except PolicyError:
            return False
        return True

    def ensure_response_issue_allowed(self, issue: dict[str, Any]) -> None:
        project_key = (
            issue.get("fields", {})
            .get("project", {})
            .get("key")
        )
        if not project_key:
            raise PolicyError("Jira response did not include a project key")
        self.ensure_project_allowed(project_key)

    def project_jql_clause(self) -> str:
        projects = ", ".join(sorted(self.allowed_projects))
        return f"project in ({projects})"

    def wrap_jql(self, jql: str | None) -> str:
        base = self.project_jql_clause()
        if not jql or not jql.strip():
            return base
        
        body, order_clause = _split_order_by(jql)
        
        if order_clause is None:
            # No ORDER BY clause, use current behavior
            if not body:
                return base
            return f"{base} AND ({body})"
        else:
            # Has ORDER BY clause
            if not body:
                # Empty body, just return base + ORDER BY (with space)
                return f"{base} {order_clause}"
            else:
                # Has both body and ORDER BY (with space before ORDER BY)
                return f"{base} AND ({body}) {order_clause}"

    def validate_update_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "summary",
            "description",
            "priority",
            "assignee",
            "labels",
            "issuetype",
            "parent",
            "fixVersions",
        }
        if "issuelinks" in fields:
            raise PolicyError(
                "Issue links cannot be set through fields; use the jira_link_issues tool"
            )
        if "status" in fields:
            raise PolicyError(
                "Status cannot be set through fields; use the jira_transition_issue tool"
            )
        rejected = sorted(
            field
            for field in fields
            if field not in allowed and field not in self.allowed_custom_fields
        )
        if rejected:
            raise PolicyError(f"Unsupported Jira fields: {', '.join(rejected)}")
        if "parent" in fields:
            self._validate_parent_field(fields["parent"])
        return dict(fields)

    def _validate_parent_field(self, parent: Any) -> None:
        if not isinstance(parent, dict) or not isinstance(parent.get("key"), str):
            raise PolicyError("Jira parent field must be an object with a key")
        self.ensure_issue_allowed(parent["key"])
