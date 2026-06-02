from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


ISSUE_KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*)-\d+$")
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
        return f"{base} AND ({jql.strip()})"

    def validate_update_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "summary",
            "description",
            "priority",
            "assignee",
            "labels",
            "issuetype",
            "parent",
        }
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
