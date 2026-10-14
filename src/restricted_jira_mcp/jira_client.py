from __future__ import annotations

from typing import Any
import re

import requests

from .adf import adf_to_text, as_adf
from .config import JiraConfig
from .policy import JiraPolicy


DEFAULT_FIELDS = [
    "summary",
    "project",
    "issuetype",
    "status",
    "assignee",
    "reporter",
    "priority",
    "labels",
    "created",
    "updated",
    "description",
]

ISSUE_FIELDS = DEFAULT_FIELDS + ["issuelinks"]

MAX_COMMENTS_PER_PAGE = 50
DESCRIPTION_EXCERPT_LIMIT = 800


class JiraClientError(RuntimeError):
    pass


class JiraClient:
    def __init__(
        self,
        config: JiraConfig,
        policy: JiraPolicy,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self.policy = policy
        self.session = session or requests.Session()
        self.session.auth = (config.email, config.api_token)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    @classmethod
    def from_env(cls) -> "JiraClient":
        config = JiraConfig.from_env()
        policy = JiraPolicy.create(
            config.allowed_projects,
            config.allowed_custom_fields,
        )
        return cls(config=config, policy=policy)

    def _requested_fields(self, base: list[str]) -> list[str]:
        """Return requested fields with allowlisted custom fields added.
        
        Combines base fields with policy custom fields, preserving order and deduplicating.
        """
        # Start with base fields
        fields = list(base)
        
        # Add allowlisted custom fields not already present
        for field in self.policy.allowed_custom_fields:
            if field not in fields:
                fields.append(field)
        
        return fields

    def _custom_fields_view(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Create a view of allowlisted custom fields with appropriate transformation.
        
        For each allowlisted field:
        - dict with type == "doc" is rendered via adf_to_text (full length)
        - any other dict or list is json.dumps-ed
        - scalars pass through unchanged
        
        Returns a dict with field_id: readable_value.
        """
        custom_fields = {}
        
        for field_id in self.policy.allowed_custom_fields:
            if field_id not in fields:
                # Field not present in the issue - skip it (could alternatively include None)
                continue
                
            value = fields[field_id]
            
            # Handle ADF documents
            if isinstance(value, dict) and value.get("type") == "doc":
                custom_fields[field_id] = adf_to_text(value)
            # Handle other complex types (dict, list) by JSON dumping
            elif isinstance(value, (dict, list)):
                import json
                custom_fields[field_id] = json.dumps(value)
            # Handle scalars (string, number, boolean, etc.)
            else:
                custom_fields[field_id] = value
        
        return custom_fields

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        self.policy.ensure_issue_allowed(issue_key)
        
        # Get requested fields including allowlisted custom fields
        requested_fields = self._requested_fields(ISSUE_FIELDS)
        
        response = self.session.get(
            self._url(f"/rest/api/3/issue/{issue_key.upper()}"),
            params={"fields": ",".join(requested_fields)},
            timeout=30,
        )
        payload = self._json_response(response)
        self.policy.ensure_response_issue_allowed(payload)
        issue = compact_issue(payload, full_description=True)
        issue["links"] = self._visible_links(payload.get("fields", {}).get("issuelinks") or [])
        
        # Add custom fields view
        custom_fields = self._custom_fields_view(payload.get("fields", {}))
        if custom_fields:
            issue["custom_fields"] = custom_fields
        
        return issue

    def get_comments(
        self,
        issue_key: str,
        max_results: int = 25,
        start_at: int = 0,
    ) -> dict[str, Any]:
        self.policy.ensure_issue_allowed(issue_key)
        capped = max(1, min(max_results, MAX_COMMENTS_PER_PAGE))
        response = self.session.get(
            self._url(f"/rest/api/3/issue/{issue_key.upper()}/comment"),
            params={
                "startAt": max(0, start_at),
                "maxResults": capped,
                "orderBy": "created",
            },
            timeout=30,
        )
        payload = self._json_response(response)
        return {
            "issue_key": issue_key.upper(),
            "start_at": payload.get("startAt"),
            "max_results": payload.get("maxResults"),
            "total": payload.get("total"),
            "comments": [compact_comment(comment) for comment in payload.get("comments", [])],
        }

    def search(self, jql: str | None, max_results: int = 25) -> dict[str, Any]:
        capped = max(1, min(max_results, 50))
        wrapped_jql = self.policy.wrap_jql(jql)
        response = self.session.post(
            self._url("/rest/api/3/search/jql"),
            json={
                "jql": wrapped_jql,
                "maxResults": capped,
                "fields": DEFAULT_FIELDS,
            },
            timeout=30,
        )
        if response.status_code == 404:
            response = self.session.post(
                self._url("/rest/api/3/search"),
                json={
                    "jql": wrapped_jql,
                    "maxResults": capped,
                    "fields": DEFAULT_FIELDS,
                },
                timeout=30,
            )
        payload = self._json_response(response)
        issues = payload.get("issues", [])
        for issue in issues:
            self.policy.ensure_response_issue_allowed(issue)
        return {
            "jql": wrapped_jql,
            "total": payload.get("total"),
            "issues": [compact_issue(issue) for issue in issues],
        }

    def create_issue(
        self,
        project_key: str,
        issue_type: str,
        summary: str,
        description: str | None = None,
        priority: str | None = None,
        assignee_account_id: str | None = None,
        labels: list[str] | None = None,
        parent_epic_key: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self.policy.ensure_project_allowed(project_key)
        fields: dict[str, Any] = {
            "project": {"key": project},
            "issuetype": {"name": issue_type},
            "summary": summary,
        }
        if description:
            fields["description"] = as_adf(description)
        if priority:
            fields["priority"] = {"name": priority}
        if assignee_account_id:
            fields["assignee"] = {"accountId": assignee_account_id}
        if labels:
            fields["labels"] = labels
        if parent_epic_key:
            fields["parent"] = {"key": self.policy.normalize_issue_key(parent_epic_key)}
        if custom_fields:
            fields.update(self.policy.validate_update_fields(custom_fields))

        response = self.session.post(
            self._url("/rest/api/3/issue"),
            json={"fields": fields},
            timeout=30,
        )
        return self._json_response(response)

    def update_issue(self, issue_key: str, fields: dict[str, Any]) -> dict[str, str]:
        self.policy.ensure_issue_allowed(issue_key)
        validated = self.policy.validate_update_fields(_normalize_fields(fields))
        response = self.session.put(
            self._url(f"/rest/api/3/issue/{issue_key.upper()}"),
            json={"fields": validated},
            timeout=30,
        )
        self._raise_for_status(response)
        return {"status": "updated", "issue_key": issue_key.upper()}

    def link_issues(
        self,
        from_issue_key: str,
        to_issue_key: str,
        link_type: str = "Relates",
    ) -> dict[str, str]:
        inward = self.policy.normalize_issue_key(from_issue_key)
        outward = self.policy.normalize_issue_key(to_issue_key)
        response = self.session.post(
            self._url("/rest/api/3/issueLink"),
            json={
                "type": {"name": link_type},
                "inwardIssue": {"key": inward},
                "outwardIssue": {"key": outward},
            },
            timeout=30,
        )
        self._raise_for_status(response)
        return {
            "status": "linked",
            "from_issue_key": inward,
            "to_issue_key": outward,
            "link_type": link_type,
        }

    def link_types(self) -> dict[str, Any]:
        response = self.session.get(self._url("/rest/api/3/issueLinkType"), timeout=30)
        payload = self._json_response(response)
        return {
            "link_types": [
                {
                    "name": link_type.get("name"),
                    "inward": link_type.get("inward"),
                    "outward": link_type.get("outward"),
                }
                for link_type in payload.get("issueLinkTypes", [])
            ]
        }

    def add_comment(self, issue_key: str, body: str) -> dict[str, Any]:
        self.policy.ensure_issue_allowed(issue_key)
        response = self.session.post(
            self._url(f"/rest/api/3/issue/{issue_key.upper()}/comment"),
            json={"body": as_adf(body)},
            timeout=30,
        )
        return self._json_response(response)

    def update_comment(self, issue_key: str, comment_id: str, body: str | dict) -> dict[str, Any]:
        """Update a comment on an allowlisted issue, restricted to own comments."""
        self.policy.ensure_issue_allowed(issue_key)
        self._validate_comment_id(comment_id)
        own_account_id = self._myself_account_id()
        
        # Get the comment to verify it exists and belongs to the current user
        comment = self._ensure_own_comment(issue_key, comment_id, own_account_id)
        
        # Update the comment
        response = self.session.put(
            self._url(f"/rest/api/3/issue/{issue_key.upper()}/comment/{comment_id}"),
            json={"body": as_adf(body)},
            timeout=30,
        )
        self._raise_for_status(response)
        
        return {"status": "updated", "issue_key": issue_key.upper(), "comment_id": comment_id}

    def delete_comment(self, issue_key: str, comment_id: str) -> dict[str, Any]:
        """Delete a comment on an allowlisted issue, restricted to own comments."""
        self.policy.ensure_issue_allowed(issue_key)
        self._validate_comment_id(comment_id)
        own_account_id = self._myself_account_id()
        
        # Get the comment to verify it exists and belongs to the current user
        self._ensure_own_comment(issue_key, comment_id, own_account_id)
        
        # Delete the comment
        response = self.session.delete(
            self._url(f"/rest/api/3/issue/{issue_key.upper()}/comment/{comment_id}"),
            timeout=30,
        )
        self._raise_for_status(response)
        
        return {"status": "deleted", "issue_key": issue_key.upper(), "comment_id": comment_id}

    def _myself_account_id(self) -> str:
        """Get the current user's account ID, cached per client instance."""
        if not hasattr(self, "_cached_account_id"):
            response = self.session.get(self._url("/rest/api/3/myself"), timeout=30)
            payload = self._json_response(response)
            self._cached_account_id = payload["accountId"]
        return self._cached_account_id

    def _validate_comment_id(self, comment_id: str) -> None:
        """Validate comment ID format using regex pattern."""
        if not self._COMMENT_ID_RE.match(comment_id):
            raise ValueError(f"Invalid comment ID format: {comment_id}")

    def _ensure_own_comment(self, issue_key: str, comment_id: str, own_account_id: str) -> dict[str, Any]:
        """Ensure the comment exists and belongs to the current user."""
        response = self.session.get(
            self._url(f"/rest/api/3/issue/{issue_key.upper()}/comment/{comment_id}"),
            timeout=30,
        )
        
        # Handle 404 response
        if response.status_code == 404:
            raise JiraClientError(f"Jira request failed: 404 Comment {comment_id} not found")
        
        payload = self._json_response(response)
        comment = payload
        
        # Check if the comment belongs to the current user
        author_account_id = comment.get("author", {}).get("accountId")
        if author_account_id != own_account_id:
            raise JiraClientError(f"Cannot modify comment {comment_id}: only own comments can be modified")
        
        return comment

    # Regex pattern for validating comment IDs
    _COMMENT_ID_RE = re.compile(r"^\d+$")

    def _visible_links(self, links: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return one entry per linked issue, dropping links outside the allowlist.

        A linked issue stub carries no project field, so the key prefix decides
        whether the link may be revealed at all.
        """
        visible = []
        for link in links:
            link_type = link.get("type") or {}
            for direction in ("outwardIssue", "inwardIssue"):
                other = link.get(direction)
                if not other or not self.policy.is_issue_allowed(other.get("key") or ""):
                    continue
                other_fields = other.get("fields") or {}
                visible.append(
                    {
                        "link_type": link_type.get("name"),
                        "relation": link_type.get(
                            "outward" if direction == "outwardIssue" else "inward"
                        ),
                        "issue_key": other.get("key"),
                        "summary": other_fields.get("summary"),
                        "status": (other_fields.get("status") or {}).get("name"),
                    }
                )
        return visible

    def _url(self, path: str) -> str:
        return f"{self.config.base_url}{path}"

    def _json_response(self, response: requests.Response) -> dict[str, Any]:
        self._raise_for_status(response)
        if not response.content:
            return {}
        return response.json()

    def _raise_for_status(self, response: requests.Response) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = _safe_error_detail(response)
            raise JiraClientError(f"Jira request failed: {response.status_code} {detail}") from exc


def _safe_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    messages = payload.get("errorMessages") or []
    errors = payload.get("errors") or {}
    return str({"errorMessages": messages, "errors": errors})[:500]


def _normalize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(fields)
    if isinstance(normalized.get("description"), str):
        normalized["description"] = as_adf(normalized["description"])
    elif isinstance(normalized.get("description"), dict):
        # Validate that the dict is a proper ADF doc
        if normalized["description"].get("type") != "doc" or not isinstance(normalized["description"].get("content"), list):
            raise ValueError(f"description must be a Markdown string or an ADF doc object, got dict with type {normalized['description'].get('type', 'unknown')!r}")
    if isinstance(normalized.get("priority"), str):
        normalized["priority"] = {"name": normalized["priority"]}
    if isinstance(normalized.get("assignee"), str):
        normalized["assignee"] = {"accountId": normalized["assignee"]}
    if isinstance(normalized.get("parent"), str):
        normalized["parent"] = {"key": normalized["parent"].upper()}
    if isinstance(normalized.get("parent"), dict) and isinstance(normalized["parent"].get("key"), str):
        normalized["parent"] = {"key": normalized["parent"]["key"].upper()}
    return normalized


def adf_doc(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def compact_issue(issue: dict[str, Any], full_description: bool = False) -> dict[str, Any]:
    fields = issue.get("fields", {})
    description = adf_to_text(fields.get("description"))
    compacted = {
        "key": issue.get("key"),
        "project": fields.get("project", {}).get("key"),
        "issue_type": fields.get("issuetype", {}).get("name"),
        "status": fields.get("status", {}).get("name"),
        "summary": fields.get("summary"),
        "assignee": _display_user(fields.get("assignee")),
        "reporter": _display_user(fields.get("reporter")),
        "priority": (fields.get("priority") or {}).get("name"),
        "labels": fields.get("labels") or [],
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "description": description,
    }
    if full_description:
        return compacted
    truncated = description is not None and len(description) > DESCRIPTION_EXCERPT_LIMIT
    if truncated:
        compacted["description"] = f"{description[:DESCRIPTION_EXCERPT_LIMIT].rstrip()}..."
    compacted["description_truncated"] = truncated
    return compacted


def compact_comment(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": comment.get("id"),
        "author": _display_user(comment.get("author")),
        "body": adf_to_text(comment.get("body")),
        "created": comment.get("created"),
        "updated": comment.get("updated"),
        "visibility": _comment_visibility(comment.get("visibility")),
        "public": comment.get("jsdPublic", True),
    }


def _display_user(user: dict[str, Any] | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "accountId": user.get("accountId"),
        "displayName": user.get("displayName"),
        "emailAddress": user.get("emailAddress"),
    }


def _comment_visibility(visibility: dict[str, Any] | None) -> str | None:
    """Describe who a restricted comment is limited to, so the reader sees it is not public."""
    if not visibility:
        return None
    return f"{visibility.get('type')}: {visibility.get('value')}"
