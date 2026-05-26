# Restricted Jira MCP

A local Jira MCP server that enforces a project allowlist before Jira data is requested or returned.

## Why this exists

Atlassian's hosted MCP follows the signed-in user's Jira permissions. If your user can see NDA projects in Jira, prompt instructions are not a security boundary. This server talks to Jira REST directly and only exposes projects listed in `JIRA_ALLOWED_PROJECTS`.

## Configuration

Set these environment variables locally:

```bash
export JIRA_BASE_URL="https://your-company.atlassian.net"
export JIRA_EMAIL="you@example.com"
export JIRA_API_TOKEN="your-token"
export JIRA_ALLOWED_PROJECTS="ISD"
```

Optional:

```bash
export JIRA_ALLOWED_CUSTOM_FIELDS="customfield_12345,customfield_67890"
```

Never commit real tokens. `.env` is ignored; `.env.example` contains placeholders only.

## Smoke validation

From the repo root:

```bash
python3 scripts/smoke_get_issue.py ISD-5444
```

Expected success shape:

```text
OK: fetched ISD-5444 from project ISD [Epic: ...]
Summary: ...
```

A non-allowlisted project should fail before any Jira HTTP request:

```bash
python3 scripts/smoke_get_issue.py NDA-123
```

## MCP server

Install the MCP SDK before running the MCP server:

```bash
python3 -m pip install -e .
python3 -m restricted_jira_mcp.server
```

This environment currently has `requests` installed but no `pip`, so the smoke test can run without installing anything. The MCP server itself requires the `mcp` Python package.

## GitHub Copilot MCP configuration

In GitHub Copilot's MCP server setup form, use these values:

```text
Server Name:
restricted-jira

Server Type:
STDIO

Command:
python3 -m restricted_jira_mcp.server

Environment Variables:
PYTHONPATH=/absolute/path/to/restricted-jira-mcp/src
JIRA_BASE_URL=https://your-company.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=your-token
JIRA_ALLOWED_PROJECTS=ISD

Tools:
*
```

If Copilot is not launched from the repository root, use an absolute command that changes into the repo first:

```bash
bash -lc 'cd /absolute/path/to/restricted-jira-mcp && PYTHONPATH=src python3 -m restricted_jira_mcp.server'
```

Keep the Jira token only in Copilot's local MCP configuration. Do not commit it to this repository.

## Tools exposed

- `jira_get_issue(issue_key)`
- `jira_search(jql, max_results=25)`
- `jira_create_issue(project_key, issue_type, summary, ...)`
- `jira_update_issue(issue_key, fields)`
- `jira_add_comment(issue_key, body)`

Writes are deliberately limited to create, update, and comment. This v1 does not support transitions, attachments, deletes, bulk edits, issue links, watchers, worklogs, sprint/version changes, or admin operations.

## GitHub

This workspace has a read-only placeholder `.git`, so this repo uses an explicit Git directory at `.git-data`.

Use:

```bash
git --git-dir=.git-data --work-tree=. status
```

When ready to push:

```bash
git --git-dir=.git-data --work-tree=. remote add origin git@github.com:cbartz/jira-mcp-poc.git
git --git-dir=.git-data --work-tree=. push -u origin main
```
