from __future__ import annotations

from typing import Any

from .jira_client import JiraClient


def create_server() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The MCP SDK is not installed. Install project dependencies before running "
            "the MCP server, for example: python3 -m pip install -e ."
        ) from exc

    mcp = FastMCP("restricted-jira-mcp")
    client = JiraClient.from_env()

    @mcp.tool()
    def jira_get_issue(issue_key: str) -> dict[str, Any]:
        """Read a single allowlisted issue's fields and links, with full description text."""
        return client.get_issue(issue_key)

    @mcp.tool()
    def jira_get_comments(
        issue_key: str,
        max_results: int = 25,
        start_at: int = 0,
    ) -> dict[str, Any]:
        """Read comments on an allowlisted issue, oldest first, paged via start_at."""
        return client.get_comments(issue_key, max_results=max_results, start_at=start_at)

    @mcp.tool()
    def jira_search(jql: str = "", max_results: int = 25) -> dict[str, Any]:
        return client.search(jql, max_results=max_results)

    @mcp.tool()
    def jira_create_issue(
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
        """Create a new issue in an allowlisted project; description accepts Markdown (headings, lists, bold/italic/code, links, tables) or a raw ADF doc dict; wiki markup is not supported."""
        return client.create_issue(
            project_key=project_key,
            issue_type=issue_type,
            summary=summary,
            description=description,
            priority=priority,
            assignee_account_id=assignee_account_id,
            labels=labels,
            parent_epic_key=parent_epic_key,
            custom_fields=custom_fields,
        )

    @mcp.tool()
    def jira_update_issue(issue_key: str, fields: dict[str, Any]) -> dict[str, str]:
        """Update an allowlisted issue's fields; description accepts Markdown (headings, lists, bold/italic/code, links, tables) or a raw ADF doc dict; wiki markup is not supported."""
        return client.update_issue(issue_key, fields)

    @mcp.tool()
    def jira_link_issues(
        from_issue_key: str,
        to_issue_key: str,
        link_type: str = "Relates",
    ) -> dict[str, str]:
        """Link two allowlisted issues, reading as "from_issue_key <link_type outward> to_issue_key"."""
        return client.link_issues(from_issue_key, to_issue_key, link_type=link_type)

    @mcp.tool()
    def jira_link_types() -> dict[str, Any]:
        """List the link type names this Jira site accepts, with their direction wording."""
        return client.link_types()

    @mcp.tool()
    def jira_add_comment(issue_key: str, body: str) -> dict[str, Any]:
        """Add a comment to an allowlisted issue; body accepts Markdown (headings, lists, bold/italic/code, links, tables) or a raw ADF doc dict; wiki markup is not supported."""
        return client.add_comment(issue_key, body)

    return mcp


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()
