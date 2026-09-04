from __future__ import annotations

from typing import Any

import requests

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
COMMENT_BODY_LIMIT = 2000


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

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        self.policy.ensure_issue_allowed(issue_key)
        response = self.session.get(
            self._url(f"/rest/api/3/issue/{issue_key.upper()}"),
            params={"fields": ",".join(ISSUE_FIELDS)},
            timeout=30,
        )
        payload = self._json_response(response)
        self.policy.ensure_response_issue_allowed(payload)
        issue = compact_issue(payload)
        issue["links"] = self._visible_links(payload.get("fields", {}).get("issuelinks") or [])
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
            fields["description"] = adf_doc(description)
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
            json={"body": adf_doc(body)},
            timeout=30,
        )
        return self._json_response(response)

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
        normalized["description"] = adf_doc(normalized["description"])
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


def compact_issue(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields", {})
    description = fields.get("description")
    return {
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
        "description": _adf_excerpt(description),
    }


def compact_comment(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": comment.get("id"),
        "author": _display_user(comment.get("author")),
        "body": _adf_excerpt(comment.get("body"), limit=COMMENT_BODY_LIMIT),
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


def _adf_excerpt(value: Any, limit: int = 800) -> str | None:
    if not value:
        return None
    text = _extract_adf_text(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _extract_adf_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        pieces = []
        if value.get("type") == "text":
            pieces.append(value.get("text", ""))
        for child in value.get("content", []):
            pieces.append(_extract_adf_text(child))
        return " ".join(part for part in pieces if part)
    if isinstance(value, list):
        return " ".join(_extract_adf_text(item) for item in value)
    return ""
