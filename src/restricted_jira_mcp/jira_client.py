from __future__ import annotations

from typing import Any, Iterator
import re

import requests

from .adf import adf_to_text, as_adf
from .config import JiraConfig
from .policy import JiraPolicy, PolicyError


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

# Fields holding a list of project-scoped {"name": ...} objects, mapped to
# the key get_issue reports their names under.
NAMED_LIST_FIELDS = {
    "fixVersions": "fix_versions",
    "versions": "affects_versions",
    "components": "components",
}

ISSUE_FIELDS = DEFAULT_FIELDS + ["issuelinks", *NAMED_LIST_FIELDS]

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
    def from_config(cls, config: JiraConfig) -> "JiraClient":
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
            
            # Handle ADF documents: readable text plus the original ADF,
            # because a write-back needs the ADF object — a bare markdown
            # string is rejected by fields that expect ADF.
            if isinstance(value, dict) and value.get("type") == "doc":
                custom_fields[field_id] = {"text": adf_to_text(value), "adf": value}
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
        for field, key in NAMED_LIST_FIELDS.items():
            issue[key] = [item.get("name") for item in payload.get("fields", {}).get(field) or []]

        # Add custom fields view
        custom_fields = self._custom_fields_view(payload.get("fields", {}))
        if custom_fields:
            issue["custom_fields"] = custom_fields

        # The readable description is markdown-shaped; markdown cannot keep
        # every ADF structure (media, some breaks and cell layouts), so the
        # original always travels with the response for lossless updates.
        description = payload.get("fields", {}).get("description")
        if description:
            issue["description_adf"] = description

        return issue

    def get_comments(
        self,
        issue_key: str,
        max_results: int = 25,
        start_at: int = 0,
    ) -> dict[str, Any]:
        resolved_key = self._resolve_issue(issue_key)
        capped = max(1, min(max_results, MAX_COMMENTS_PER_PAGE))
        response = self.session.get(
            self._url(f"/rest/api/3/issue/{resolved_key}/comment"),
            params={
                "startAt": max(0, start_at),
                "maxResults": capped,
                "orderBy": "created",
            },
            timeout=30,
        )
        payload = self._json_response(response)
        return {
            "issue_key": resolved_key,
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
        description: str | dict | None = None,
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
        if description is not None:
            # None means "no description"; anything supplied — including an
            # empty dict — goes through ADF validation.
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
        resolved_key = self._resolve_issue(issue_key)
        response = self.session.put(
            self._url(f"/rest/api/3/issue/{resolved_key}"),
            json={"fields": validated},
            timeout=30,
        )
        self._raise_for_status(response)
        return {"status": "updated", "issue_key": resolved_key}

    def link_issues(
        self,
        from_issue_key: str,
        to_issue_key: str,
        link_type: str = "Relates",
    ) -> dict[str, str]:
        self.policy.ensure_issue_allowed(from_issue_key)
        self.policy.ensure_issue_allowed(to_issue_key)
        inward = self._resolve_issue(from_issue_key)
        outward = self._resolve_issue(to_issue_key)
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

    def transitions(self, issue_key: str) -> dict[str, Any]:
        resolved_key = self._resolve_issue(issue_key)
        return {
            "issue_key": resolved_key,
            "transitions": [
                {
                    "id": transition.get("id"),
                    "name": transition.get("name"),
                    "to_status": (transition.get("to") or {}).get("name"),
                }
                for transition in self._available_transitions(resolved_key)
            ],
        }

    def transition_issue(
        self,
        issue_key: str,
        transition: str,
        resolution: str | None = None,
    ) -> dict[str, str]:
        """Move an issue through the workflow to change its status.

        transition names a transition by id or name, or the status it leads
        to; Jira only offers the transitions valid from the current status.
        """
        resolved_key = self._resolve_issue(issue_key)
        chosen = _match_transition(self._available_transitions(resolved_key), transition)
        body: dict[str, Any] = {"transition": {"id": chosen["id"]}}
        if resolution:
            body["fields"] = {"resolution": {"name": resolution}}
        response = self.session.post(
            self._url(f"/rest/api/3/issue/{resolved_key}/transitions"),
            json=body,
            timeout=30,
        )
        self._raise_for_status(response)
        return {
            "status": "transitioned",
            "issue_key": resolved_key,
            "transition_id": chosen["id"],
            "to_status": (chosen.get("to") or {}).get("name"),
        }

    def sprints(self, project_key: str) -> dict[str, Any]:
        """List active and future sprints on the project's scrum boards.

        Boards are found through their filter, which can span projects, and a
        board also lists other boards' sprints whose issues match that filter,
        so only sprints originating on an allowlisted board are returned.
        """
        project = self.policy.ensure_project_allowed(project_key)
        boards = list(
            self._agile_values("/rest/agile/1.0/board", {"projectKeyOrId": project, "type": "scrum"})
        )
        board_allowed = {board.get("id"): self._board_allowed(board) for board in boards}
        sprints: dict[int, dict[str, Any]] = {}
        for board in boards:
            if not board_allowed[board.get("id")]:
                continue
            for sprint in self._agile_values(
                f"/rest/agile/1.0/board/{int(board['id'])}/sprint", {"state": "active,future"}
            ):
                if sprint.get("id") in sprints or not self._origin_board_allowed(
                    sprint.get("originBoardId"), board_allowed
                ):
                    continue
                sprints[sprint.get("id")] = {
                    "id": sprint.get("id"),
                    "name": sprint.get("name"),
                    "state": sprint.get("state"),
                    "board": board.get("name"),
                }
        return {"project_key": project, "sprints": list(sprints.values())}

    def move_to_sprint(self, issue_key: str, sprint_id: int | None) -> dict[str, Any]:
        """Move an issue into a sprint, or to the backlog when sprint_id is None."""
        resolved_key = self._resolve_issue(issue_key)
        if sprint_id is None:
            path = "/rest/agile/1.0/backlog/issue"
        else:
            # Sprint ids are global; the sprint's own board decides whether
            # it belongs to an allowlisted project.
            response = self.session.get(
                self._url(f"/rest/agile/1.0/sprint/{int(sprint_id)}"), timeout=30
            )
            if not self._origin_board_allowed(self._json_response(response).get("originBoardId"), {}):
                raise PolicyError(f"Sprint {sprint_id} does not belong to an allowlisted project")
            path = f"/rest/agile/1.0/sprint/{int(sprint_id)}/issue"
        response = self.session.post(
            self._url(path),
            json={"issues": [resolved_key]},
            timeout=30,
        )
        self._raise_for_status(response)
        return {
            "status": "moved",
            "issue_key": resolved_key,
            "moved_to": "backlog" if sprint_id is None else "sprint",
            "sprint_id": sprint_id,
        }

    def add_comment(self, issue_key: str, body: str | dict) -> dict[str, Any]:
        resolved_key = self._resolve_issue(issue_key)
        response = self.session.post(
            self._url(f"/rest/api/3/issue/{resolved_key}/comment"),
            json={"body": as_adf(body)},
            timeout=30,
        )
        return self._json_response(response)

    def update_comment(self, issue_key: str, comment_id: str, body: str | dict) -> dict[str, Any]:
        """Update a comment on an allowlisted issue, restricted to own comments."""
        self.policy.ensure_issue_allowed(issue_key)
        self._validate_comment_id(comment_id)
        resolved_key = self._resolve_issue(issue_key)
        own_account_id = self._myself_account_id()

        # Get the comment to verify it exists and belongs to the current user
        comment = self._ensure_own_comment(resolved_key, comment_id, own_account_id)

        # Update the comment
        response = self.session.put(
            self._url(f"/rest/api/3/issue/{resolved_key}/comment/{comment_id}"),
            json={"body": as_adf(body)},
            timeout=30,
        )
        self._raise_for_status(response)

        return {"status": "updated", "issue_key": resolved_key, "comment_id": comment_id}

    def delete_comment(self, issue_key: str, comment_id: str) -> dict[str, Any]:
        """Delete a comment on an allowlisted issue, restricted to own comments."""
        self.policy.ensure_issue_allowed(issue_key)
        self._validate_comment_id(comment_id)
        resolved_key = self._resolve_issue(issue_key)
        own_account_id = self._myself_account_id()

        # Get the comment to verify it exists and belongs to the current user
        self._ensure_own_comment(resolved_key, comment_id, own_account_id)

        # Delete the comment
        response = self.session.delete(
            self._url(f"/rest/api/3/issue/{resolved_key}/comment/{comment_id}"),
            timeout=30,
        )
        self._raise_for_status(response)

        return {"status": "deleted", "issue_key": resolved_key, "comment_id": comment_id}

    def _myself_account_id(self) -> str:
        """Get the current user's account ID, cached per client instance."""
        if not hasattr(self, "_cached_account_id"):
            response = self.session.get(self._url("/rest/api/3/myself"), timeout=30)
            payload = self._json_response(response)
            self._cached_account_id = payload["accountId"]
        return self._cached_account_id

    def _agile_values(self, path: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Yield every value of a paged Agile API listing."""
        start_at = 0
        while True:
            response = self.session.get(
                self._url(path),
                params={**params, "startAt": start_at, "maxResults": 50},
                timeout=30,
            )
            payload = self._json_response(response)
            values = payload.get("values", [])
            yield from values
            if payload.get("isLast", True) or not values:
                return
            start_at += len(values)

    def _origin_board_allowed(self, board_id: int | None, known: dict[Any, bool]) -> bool:
        """Report whether a sprint's origin board is allowlisted, caching lookups in known."""
        if board_id is None:
            return False
        if board_id not in known:
            response = self.session.get(self._url(f"/rest/agile/1.0/board/{int(board_id)}"), timeout=30)
            known[board_id] = self._board_allowed(self._json_response(response))
        return known[board_id]

    def _board_allowed(self, board: dict[str, Any]) -> bool:
        project_key = (board.get("location") or {}).get("projectKey")
        return bool(project_key) and project_key.upper() in self.policy.allowed_projects

    def _available_transitions(self, resolved_key: str) -> list[dict[str, Any]]:
        response = self.session.get(
            self._url(f"/rest/api/3/issue/{resolved_key}/transitions"),
            timeout=30,
        )
        return self._json_response(response).get("transitions", [])

    def _resolve_issue(self, issue_key: str) -> str:
        """Return the canonical key after proving the resolved issue is allowlisted.

        The key prefix alone is not proof: Jira can resolve a historical key
        after an issue moved, so the resolved project decides, exactly like
        get_issue checking its own response.
        """
        self.policy.ensure_issue_allowed(issue_key)
        response = self.session.get(
            self._url(f"/rest/api/3/issue/{issue_key.upper()}"),
            params={"fields": "project"},
            timeout=30,
        )
        payload = self._json_response(response)
        self.policy.ensure_response_issue_allowed(payload)
        return payload.get("key") or issue_key.upper()

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


def _match_transition(transitions: list[dict[str, Any]], wanted: str) -> dict[str, Any]:
    """Pick the transition named by id, by name, or by target status, in that order.

    The first tier with any match decides. Several transitions can share a
    name or lead to the same status (for example "Reject" and "Decline" both
    ending in Rejected); guessing between them, or falling through to a later
    tier, could run a workflow's other side effects, so ambiguity is refused.
    """
    needle = wanted.strip().casefold()
    by_id = [t for t in transitions if t.get("id") == wanted.strip()]
    by_name = [t for t in transitions if (t.get("name") or "").casefold() == needle]
    by_status = [
        t for t in transitions if ((t.get("to") or {}).get("name") or "").casefold() == needle
    ]
    matches = by_id or by_name or by_status
    if len(matches) == 1:
        return matches[0]
    available = "; ".join(
        f"{t.get('id')} {t.get('name')!r} -> {(t.get('to') or {}).get('name')!r}"
        for t in transitions
    )
    if matches:
        raise JiraClientError(
            f"Transition {wanted!r} is ambiguous; pass a transition id instead. Available: {available}"
        )
    raise JiraClientError(
        f"No transition {wanted!r} from the current status. Available: {available or 'none'}"
    )


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
    for field in NAMED_LIST_FIELDS:
        if isinstance(normalized.get(field), str):
            normalized[field] = [normalized[field]]
        if isinstance(normalized.get(field), list):
            normalized[field] = [
                {"name": item} if isinstance(item, str) else item for item in normalized[field]
            ]
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
    body = comment.get("body")
    compacted = {
        "id": comment.get("id"),
        "author": _display_user(comment.get("author")),
        "body": adf_to_text(body),
        "created": comment.get("created"),
        "updated": comment.get("updated"),
        "visibility": _comment_visibility(comment.get("visibility")),
        "public": comment.get("jsdPublic", True),
    }
    # The readable body is markdown-shaped; markdown cannot keep every ADF
    # structure, so the original always travels with the response for
    # lossless updates.
    if body:
        compacted["body_adf"] = body
    return compacted


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
