from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from restricted_jira_mcp.jira_client import JiraClient
from restricted_jira_mcp.policy import PolicyError


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch one allowlisted Jira issue.")
    parser.add_argument("issue_key", help="Issue key to fetch, for example ISD-5444")
    args = parser.parse_args()

    try:
        issue = JiraClient.from_env().get_issue(args.issue_key)
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
