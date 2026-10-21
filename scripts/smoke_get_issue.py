from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from restricted_jira_mcp.config import load_config
from restricted_jira_mcp.jira_client import JiraClient
from restricted_jira_mcp.policy import PolicyError


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch one allowlisted Jira issue.")
    parser.add_argument("issue_key", help="Issue key to fetch, for example ISD-5444")
    parser.add_argument(
        "--config",
        default=os.environ.get("JIRA_MCP_CONFIG"),
        help="Path to the JSON config file (default: $JIRA_MCP_CONFIG).",
    )
    args = parser.parse_args()
    if not args.config:
        parser.error("no config file: pass --config or set JIRA_MCP_CONFIG")

    try:
        issue = JiraClient.from_config(load_config(args.config).jira).get_issue(args.issue_key)
    except PolicyError as exc:
        print(f"DENIED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        f"OK: fetched {issue['key']} from project {issue['project']} "
        f"[{issue.get('issue_type')}: {issue.get('status')}]"
    )
    if issue.get("summary"):
        print(f"Summary: {issue['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
