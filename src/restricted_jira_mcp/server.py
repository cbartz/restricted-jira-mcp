from __future__ import annotations

import argparse
import os
from typing import Any

from .http_auth import ASGIApp, BearerAuthMiddleware, load_client_token_hashes
from .jira_client import JiraClient


def create_server(client: JiraClient | None = None) -> Any:
    """Build the FastMCP server with every tool registered over the given JiraClient.

    When no client is injected, one is built from the environment (existing behaviour).
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The MCP SDK is not installed. Install project dependencies before running "
            "the MCP server, for example: python3 -m pip install -e ."
        ) from exc

    mcp = FastMCP("restricted-jira-mcp")
    _register_tools(mcp, JiraClient.from_env() if client is None else client)
    return mcp


def build_http_app(client: JiraClient, host: str, port: int) -> ASGIApp:
    """Wrap the stateless streamable-HTTP MCP app behind per-client bearer-token auth.

    Token hashes come from the file named by $JIRA_MCP_CLIENT_TOKENS_FILE; an
    unusable value fails closed with ValueError before anything is served.
    """
    token_hashes = _load_client_token_hashes()

    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The MCP SDK is not installed. Install project dependencies before running "
            "the MCP server, for example: python3 -m pip install -e ."
        ) from exc

    mcp = FastMCP(
        "restricted-jira-mcp",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )
    _register_tools(mcp, client)
    return BearerAuthMiddleware(mcp.streamable_http_app(), token_hashes)


def _register_tools(mcp: Any, client: JiraClient) -> None:
    """Register every Jira tool on the FastMCP instance, closed over one client."""
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
        description: str | dict | None = None,
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
    def jira_add_comment(issue_key: str, body: str | dict) -> dict[str, Any]:
        """Add a comment to an allowlisted issue; body accepts Markdown (headings, lists, bold/italic/code, links, tables) or a raw ADF doc dict; wiki markup is not supported."""
        return client.add_comment(issue_key, body)

    @mcp.tool()
    def jira_update_comment(issue_key: str, comment_id: str, body: str | dict) -> dict[str, Any]:
        """Update your own comment on an allowlisted issue; body accepts Markdown or a raw ADF doc dict; only comments authored by the configured user can be edited."""
        return client.update_comment(issue_key, comment_id, body)

    @mcp.tool()
    def jira_delete_comment(issue_key: str, comment_id: str) -> dict[str, Any]:
        """Delete your own comment on an allowlisted issue; only comments authored by the configured user can be deleted."""
        return client.delete_comment(issue_key, comment_id)


def _load_client_token_hashes() -> tuple[str, ...]:
    """Read the per-client bearer token hashes named by $JIRA_MCP_CLIENT_TOKENS_FILE."""
    path = os.environ.get("JIRA_MCP_CLIENT_TOKENS_FILE")
    if not path:
        raise ValueError(
            "JIRA_MCP_CLIENT_TOKENS_FILE is not set; serving HTTP requires a client-token hash file"
        )
    try:
        return load_client_token_hashes(path)
    except OSError as exc:
        raise ValueError(f"Could not read client-token hash file {path}: {exc}") from exc


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI flags; the transport default comes from $JIRA_MCP_TRANSPORT or stdio.

    Environment variables are read only after parsing, so --help always exits 0
    before any config or token loading can happen.
    """
    parser = argparse.ArgumentParser(
        prog="restricted-jira-mcp",
        description="Restricted Jira MCP server over stdio or bearer-authenticated streamable HTTP.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        help="Transport to serve on (default: $JIRA_MCP_TRANSPORT or stdio).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (default: 8000).")
    args = parser.parse_args(argv)
    if args.transport is None:
        args.transport = _transport_from_env(parser)
    return args


def _transport_from_env(parser: argparse.ArgumentParser) -> str:
    """Resolve the transport default from $JIRA_MCP_TRANSPORT, failing closed on typos."""
    env_transport = os.environ.get("JIRA_MCP_TRANSPORT", "").strip().lower()
    if not env_transport:
        return "stdio"
    if env_transport not in ("stdio", "http"):
        parser.error(f"invalid JIRA_MCP_TRANSPORT {env_transport!r}: expected 'stdio' or 'http'")
    return env_transport


def main(argv: list[str] | None = None) -> None:
    """Entry point: serve the MCP server over stdio (default) or streamable HTTP."""
    args = _parse_args(argv)
    if args.transport == "http":
        import uvicorn

        client = JiraClient.from_env()
        uvicorn.run(build_http_app(client, args.host, args.port), host=args.host, port=args.port)
    else:
        create_server().run()


if __name__ == "__main__":
    main()
