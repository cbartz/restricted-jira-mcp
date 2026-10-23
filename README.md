# Restricted Jira MCP

A local Jira MCP server that enforces a project allowlist before Jira data is requested or returned.

## Why this exists

Atlassian's hosted MCP follows the signed-in user's Jira permissions. If your user can see NDA projects in Jira, prompt instructions are not a security boundary. This server talks to Jira REST directly and only exposes projects listed in `jira.allowed_projects` of its config file. Several projects can be trusted at once (for example `["ISD", "ISREQ"]`).

## Configuration

All settings live in one JSON file. Start from the example and lock it down — it holds the Jira API token and the client token:

```bash
sudo mkdir -p /etc/restricted-jira-mcp
sudo cp config.example.json /etc/restricted-jira-mcp/config.json
sudo chmod 600 /etc/restricted-jira-mcp/config.json
sudo chown "$USER" /etc/restricted-jira-mcp/config.json   # the user that runs the server
```

```json
{
  "jira": {
    "base_url": "https://your-company.atlassian.net",
    "email": "you@example.com",
    "api_token": "…",
    "allowed_projects": ["ISD", "ISREQ"],
    "allowed_custom_fields": []
  },
  "http": {
    "bind_address": "10.81.99.1:8000",
    "allowed_hosts": [],
    "client_token": "…"
  }
}
```

- `jira.allowed_projects` is the security boundary: only these projects are ever requested or returned. `allowed_custom_fields` is optional.
- The `http` section is only needed for the HTTP transport; a stdio-only setup can leave it out.
- `client_token` is the bearer token every agent VM sends as `Authorization: Bearer <token>` — the same value, not a hash of it. Generate it with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. Rotating it means updating every VM's MCP config.
- Unknown keys, empty values and the example's `CHANGE_ME` placeholders are rejected at startup, so a typo never silently drops a restriction.

The server reads the file named by `--config`, or by `$JIRA_MCP_CONFIG` when the flag is absent. It reads it once at startup; restart after editing.

## Smoke validation

From the repo root:

```bash
uv run python scripts/smoke_get_issue.py --config /etc/restricted-jira-mcp/config.json ISD-5444
```

Expected success shape:

```text
OK: fetched ISD-5444 from project ISD [Epic: ...]
Summary: ...
```

A non-allowlisted project should fail before any Jira HTTP request:

```bash
uv run python scripts/smoke_get_issue.py --config /etc/restricted-jira-mcp/config.json NDA-123
```

## Running over HTTP

```bash
uv sync
PYTHONPATH=src uv run python -m restricted_jira_mcp.server --transport http --config /etc/restricted-jira-mcp/config.json
```

The MCP endpoint is `http://<bind_address>/mcp`.

**Bind address.** Bind to an address only the agent VMs can reach — for LXD VMs, the host's bridge address (`lxc network list`) — rather than `0.0.0.0`. The bearer token is the second layer, not the first. The server speaks plain HTTP; terminate TLS in a reverse proxy if traffic crosses a network you do not trust. Binding a wildcard address (`0.0.0.0`, `::`) requires `allowed_hosts`.

**Allowed Host headers.** Requests whose `Host` header is not on an allow-list get `421 Invalid Host header` (DNS-rebinding protection), and a foreign `Origin` header gets `403`. The allow-list always contains the bind host and the loopback names, with or without a port. If clients reach the server under another name (a DNS name, a NAT or proxied address), add those `Host` values to `allowed_hosts`, for example `["jira-mcp.lan:8000"]`; a trailing `:*` matches any port.

To reach a server bound to 127.0.0.1 from a remote host instead, use an SSH tunnel:

```bash
ssh -N -L 8000:127.0.0.1:8000 <host>
```

### GitHub Copilot over HTTP

Put the entry in the VM's `~/.copilot/mcp-config.json`. Prefer editing that file over Copilot's setup form, and keep exactly one `restricted-jira` entry across it and any workspace `.mcp.json` / `.github/mcp.json`:

```json
{
  "mcpServers": {
    "restricted-jira": {
      "type": "http",
      "url": "http://<bind_address>/mcp",
      "headers": {"Authorization": "Bearer <client_token>"},
      "tools": ["*"]
    }
  }
}
```

Restart Copilot after changing it. If the server log shows `POST /mcp` answered 401 followed by `/.well-known/oauth-*` probes, Copilot is not sending the configured header (github/copilot-cli#3100); fix the entry as above, or run `copilot mcp enable restricted-jira` once.

## Target deployment

Deploy one server outside the agent VMs (host or dedicated VM, dedicated Unix user, config file 0600) serving several agent VMs. Each VM's MCP config holds only the URL and the client token. A leaked client token grants only the allowlisted operations, not full Atlassian access; anyone who can read the config file on the host has the Jira API token itself.

## Running over stdio

```text
Server Name:
restricted-jira

Server Type:
STDIO

Command:
bash -lc 'cd /absolute/path/to/restricted-jira-mcp && PYTHONPATH=src uv run python -m restricted_jira_mcp.server --config /etc/restricted-jira-mcp/config.json'

Tools:
*
```

Over stdio the agent's machine holds the Jira API token; prefer HTTP when the agent runs in a VM you do not fully trust.

## Tools exposed

- `jira_get_issue(issue_key)`
  - Returns full description text (no truncation)
  - Includes allowlisted custom fields under "custom_fields": ADF-valued fields carry both `text` (readable, full length) and `adf` (the original object — pass it back unchanged when updating, since those fields reject bare strings); non-ADF values JSON-dump; scalars pass through
  - Every description and comment body also carries its original object as `description_adf` / `body_adf` — markdown cannot keep every ADF structure (uploaded media, some break and cell layouts), so pass the ADF back unchanged in an update when you need a lossless write
- `jira_get_comments(issue_key, max_results=25, start_at=0)`
  - Returns full comment text (no truncation)
- `jira_search(jql, max_results=25)`
  - Descriptions are 800-character excerpts with explicit "description_truncated" flag
  - Supports trailing ORDER BY clause (split out of the wrapped JQL)
- `jira_create_issue(project_key, issue_type, summary, ..., parent_epic_key=None)`
- `jira_update_issue(issue_key, fields)`
  - `fixVersions`, `versions` (affects versions) and `components` each accept a name or a list of names (`{"fixVersions": ["27.04"]}`). A write replaces the whole list, so read the current `fix_versions` / `affects_versions` / `components` from `jira_get_issue` first to add one. Jira resolves the names within the issue's own project.
- `jira_link_issues(from_issue_key, to_issue_key, link_type="Relates")`
- `jira_link_types()`
- `jira_transitions(issue_key)`
- `jira_transition_issue(issue_key, transition, resolution=None)`
- `jira_sprints(project_key)`
  - Active and future sprints on the project's scrum boards; boards located in a non-allowlisted project, and sprints originating on such boards, are left out
- `jira_move_to_sprint(issue_key, sprint_id=None)`
  - Moves the issue into the sprint, or to the backlog when `sprint_id` is omitted. Sprint ids are global, so the sprint's board must belong to an allowlisted project
- `jira_add_comment(issue_key, body)`
- `jira_update_comment(issue_key, comment_id, body)`
  - Restricted to comments authored by the configured user (an agent should not rewrite other people's words)
- `jira_delete_comment(issue_key, comment_id)`
  - Restricted to comments authored by the configured user (an agent should not rewrite other people's words)

Writes are deliberately limited to create, update, transition, comment, and link. This v1 does not support attachments, deletes (including removing an existing link), bulk edits, watchers, worklogs, or admin operations.

## Body formats

Descriptions and comment bodies accept:
- Markdown (headings, lists, bold/italic/code, links, tables; line breaks preserved)
- Raw ADF doc dict
- Wiki markup is NOT supported

Reads render ADF to Markdown-shaped text losslessly for the structures above. Content markdown cannot express (embedded media, Jira widgets like status lozenges, dates, and smart links) degrades to readable text — a `status` becomes its label, a `date` becomes its ISO date, a smart link becomes a plain link. For a fully lossless update of anything markdown can't represent, pass the original ADF back (every read carries it as `description_adf` / `body_adf`, see above).

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

## Changing status

Jira changes status only through workflow transitions, so `status` is rejected by `jira_update_issue` with a pointer to `jira_transition_issue`.

```text
jira_transitions(issue_key="ISD-5872")
jira_transition_issue(issue_key="ISD-5872", transition="Rejected", resolution="Won't Do")
```

`transition` may be a transition id, a transition name, or the target status name. The first of these that matches decides; if it matches several transitions (two sharing a name, or two leading to the same status), the call is refused and lists them with their ids. Only the transitions valid from the issue's current status are offered. Pass `resolution` when the transition's screen requires one; resolution names are site-specific.

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
