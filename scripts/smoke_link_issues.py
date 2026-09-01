from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from restricted_jira_mcp.jira_client import JiraClient
from restricted_jira_mcp.policy import PolicyError


def main() -> int:
    parser = argparse.ArgumentParser(description="Link two allowlisted Jira issues.")
    parser.add_argument("from_issue_key", help="Source issue key, for example ISD-5444")
    parser.add_argument("to_issue_key", help="Target issue key, for example ISREQ-5090")
    parser.add_argument("--link-type", default="Relates", help="Jira link type name")
    args = parser.parse_args()

    try:
        result = JiraClient.from_env().link_issues(
            args.from_issue_key,
            args.to_issue_key,
            link_type=args.link_type,
        )
    except PolicyError as exc:
        print(f"DENIED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        f"OK: linked {result['from_issue_key']} -> {result['to_issue_key']} "
        f"[{result['link_type']}]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
