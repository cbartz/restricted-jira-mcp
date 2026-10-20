# Restricted Jira MCP

A local Jira MCP server that enforces a project allowlist before Jira data is requested or returned.

## Why this exists

Atlassian's hosted MCP follows the signed-in user's Jira permissions. If your user can see NDA projects in Jira, prompt instructions are not a security boundary. This server talks to Jira REST directly and only exposes projects listed in `JIRA_ALLOWED_PROJECTS`. The allowlist is a comma-separated list, so several projects can be trusted at once (for example `ISD,ISREQ`).

## Configuration

Set these environment variables locally:

```bash
export JIRA_BASE_URL="https://your-company.atlassian.net"
export JIRA_EMAIL="you@example.com"
export JIRA_API_TOKEN="your-token"
# OR use JIRA_API_TOKEN_FILE to load token from a file (set only one of these)
export JIRA_API_TOKEN_FILE="/path/to/token/file"
export JIRA_ALLOWED_PROJECTS="ISD,ISREQ"
```

Optional:

```bash
export JIRA_ALLOWED_CUSTOM_FIELDS="customfield_12345,customfield_67890"
```

Never commit real tokens. `.env` is ignored; `.env.example` contains placeholders only. If using JIRA_API_TOKEN_FILE, ensure the file is readable only by the Unix user running the server (mode 0600).

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

## Running over HTTP

Serve over HTTP with bearer token authentication:

```bash
python3 -m restricted_jira_mcp.server --transport http --host 127.0.0.1 --port 8000
```

Client tokens are stored in `JIRA_MCP_CLIENT_TOKENS_FILE` as SHA-256 hex digests, one per line. Create a token hash with (the `cut` drops the trailing `-` filename that `sha256sum` prints, which the server would reject):

```bash
printf '%s' 'your-client-token' | sha256sum | cut -d' ' -f1
```

The hash file is read once at startup, so adding or removing a client token requires a server restart to take effect.

For GitHub Copilot's MCP server setup form, use these values:

```text
Server Name:
restricted-jira

Server Type:
HTTP

URL:
http://127.0.0.1:8000/mcp

Headers:
{"Authorization": "Bearer <this-VMs-client-token>"}

Tools:
*
```

To reach a server bound to 127.0.0.1 from a remote host, use an SSH tunnel (the default way to reach a 127.0.0.1-bound server):

```bash
ssh -N -L 8000:127.0.0.1:8000 <host>
```

This keeps the Host header the MCP SDK expects. For a TLS reverse proxy, note that the SDK performs a Host-header/DNS-rebinding check.

If the first connect fails due to Copilot's OAuth-discovery quirk (github/copilot-cli#3100), run:

```bash
copilot mcp enable restricted-jira
```

## Target deployment

Deploy one server outside the agent VMs (host or dedicated VM, dedicated Unix user, token file 0600) serving several agent VMs. Each VM's MCP config holds only the URL and its own client token. A leaked client token grants only the allowlisted operations, not full Atlassian access.

## GitHub Copilot MCP configuration

For GitHub Copilot's MCP server setup form, use these values:

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
JIRA_ALLOWED_PROJECTS=ISD,ISREQ

Tools:
*
```

If Copilot is not launched from the repository root, use an absolute command that changes into the repo first:

```bash
bash -lc 'cd /absolute/path/to/restricted-jira-mcp && PYTHONPATH=src python3 -m restricted_jira_mcp.server'
```

For HTTP deployment, see the "Running over HTTP" section above. With HTTP, agent VMs hold no Jira token at all.

## Tools exposed

- `jira_get_issue(issue_key)`
  - Returns full description text (no truncation)
  - Includes allowlisted custom fields under "custom_fields": ADF-valued fields carry both `text` (readable, full length) and `adf` (the original object — pass it back unchanged when updating, since those fields reject bare strings); non-ADF values JSON-dump; scalars pass through
- `jira_get_comments(issue_key, max_results=25, start_at=0)`
  - Returns full comment text (no truncation)
- `jira_search(jql, max_results=25)`
  - Descriptions are 800-character excerpts with explicit "description_truncated" flag
  - Supports trailing ORDER BY clause (split out of the wrapped JQL)
- `jira_create_issue(project_key, issue_type, summary, ..., parent_epic_key=None)`
- `jira_update_issue(issue_key, fields)`
- `jira_link_issues(from_issue_key, to_issue_key, link_type="Relates")`
- `jira_link_types()`
- `jira_add_comment(issue_key, body)`
- `jira_update_comment(issue_key, comment_id, body)`
  - Restricted to comments authored by the configured user (an agent should not rewrite other people's words)
- `jira_delete_comment(issue_key, comment_id)`
  - Restricted to comments authored by the configured user (an agent should not rewrite other people's words)

Writes are deliberately limited to create, update, comment, and link. This v1 does not support transitions, attachments, deletes (including removing an existing link), bulk edits, watchers, worklogs, sprint/version changes, or admin operations.

## Body formats

Descriptions and comment bodies accept:
- Markdown (headings, lists, bold/italic/code, links, tables; line breaks preserved)
- Raw ADF doc dict
- Wiki markup is NOT supported

For example:

```text
jira_create_issue(
  project_key="ISD",
  issue_type="Story",
  summary="Add the requested workflow",
  description="# Task Description\n\n## Requirements\n- Must support **bold** text\n- *Italic* text should work\n- Code formatting: `inline code` and code blocks\n\n[Link to documentation](https://example.com)"
)
```

For modern Jira Cloud projects, create a story under an epic by passing `parent_epic_key`:

```text
jira_create_issue(
  project_key="ISD",
  issue_type="Story",
  summary="Add the requested workflow",
  parent_epic_key="ISD-5444"
)
```

`jira_search` now supports a trailing ORDER BY clause (it is split out of the wrapped JQL):

```text
jira_search("project = ISD ORDER BY created DESC", max_results=25)
```

Descriptions are 800-character excerpts with an explicit "description_truncated" flag.

## Reading comments

`jira_get_comments` returns an issue's comments oldest first, with the author, the
timestamps, and the body flattened from ADF to plain text and returned in full (no
truncation). The issue key is checked against the allowlist before any Jira
request, exactly like `jira_get_issue`.

```text
jira_get_comments(issue_key="ISD-5444", max_results=25, start_at=0)
```

Long comment threads are paged: `max_results` is capped at 50 per call, and the
response echoes `start_at`, `max_results`, and `total` so the next page can be
requested with `start_at` advanced.

Each comment carries two fields worth reading before quoting it elsewhere:
`visibility` is `null` for a normal comment and otherwise names the role or group
the comment is restricted to (for example `role: Administrators`), and `public` is
`false` for a Jira Service Management internal comment that customers cannot see.

## Linking issues

Cross-project references use `jira_link_issues`, not `jira_update_issue`. Jira does not accept `issuelinks` as a plain field write, so that field is rejected with a pointer to this tool.

```text
jira_link_issues(
  from_issue_key="ISD-5444",
  to_issue_key="ISREQ-5090",
  link_type="Relates"
)
```

The link reads in the direction `from_issue_key <link type outward wording> to_issue_key`, so the example above records "ISD-5444 relates to ISREQ-5090". Both keys must belong to allowlisted projects, and both are checked before any Jira request. Link type names are site-specific; `jira_link_types()` lists the names this site accepts along with their inward and outward wording.

`jira_get_issue` now returns a `links` list. Links pointing at a non-allowlisted project are removed from the response, so an ISD issue linked to an NDA issue reveals neither its key nor its summary.

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
