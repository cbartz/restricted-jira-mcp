# Full-fidelity reads/writes and secure HTTP transport — design

Record of the task brief and the decisions made while planning. The task brief
(fix gaps in the restricted Jira MCP server) is the source; this document adds
the decisions taken when the brief left a choice open.

## Intent

The restricted Jira MCP server is safe to point agents at (project allowlist in
`policy.py`), but real use exposed six gaps: truncated reads that make
read/update round trips lossy, wiki-markup-unfriendly writes, no comment
edit/delete, unreadable allowlisted custom fields, broken `ORDER BY` JQL, and a
Jira API token readable by the very agents the server serves.

## Goals / non-goals

- Goal: lossless read→update round trip for descriptions, comments, and
  allowlisted custom fields; Markdown (not wiki markup) accepted on writes.
- Goal: agent environments contain no Jira credential; the server can run
  outside the agent VMs over authenticated HTTP.
- Non-goal: transitions, attachments, watchers, worklogs, bulk edits, admin
  operations (unchanged v1 limits).
- Anti-goal: weakening the allowlist. Every new code path goes through
  `ensure_issue_allowed` / `ensure_response_issue_allowed` /
  `validate_update_fields` / the custom-field allowlist.

## Decisions

1. **Full text reads** (user chose): `jira_get_issue` and `jira_get_comments`
   always return full text, no flag. `jira_search` stays compact and carries an
   explicit `description_truncated` flag on every issue so an excerpt can never
   masquerade as the full text.
2. **Markdown→ADF**: parse with `markdown-it-py` (MIT, actively maintained,
   pure Python) and map its syntax tree to ADF with a small converter in this
   repo. The purpose-built PyPI packages (`md-to-adf`, `md2adf`) are v0.1.x
   with no adoption; too risky for the write path. Line breaks are preserved
   (soft break → ADF hardBreak). Raw ADF dicts are also accepted for
   `description` and comment `body` after a `type: doc` sanity check, matching
   how allowlisted custom fields already accept ADF.
3. **Comment edit/delete restricted to own comments**: enforced
   unconditionally, no opt-out. One cached `GET /rest/api/3/myself` per client
   instance; the comment is fetched before edit/delete, which both proves the
   comment belongs to the issue (Jira scopes the path) and provides
   `author.accountId`. Rationale: cheapest correct ownership check, and an
   agent should not rewrite other people's words.
4. **HTTP transport**: streamable HTTP, stateless JSON mode, bound to
   127.0.0.1 by default. Every request must carry `Authorization: Bearer`
   whose SHA-256 hash is listed in `JIRA_MCP_CLIENT_TOKENS_FILE`; comparison is
   constant-time; tokens are never logged. stdio stays the default transport
   for local use.
5. **Jira token from file**: `JIRA_API_TOKEN_FILE` (0600, owned by a dedicated
   Unix user) as alternative to `JIRA_API_TOKEN`; setting both is an error.
6. **Verification**: automated tests only; no live smoke test from this VM
   (user chose to smoke-test from their own VM before merging).

## Deployment target (documented in README)

One server outside the agent VMs (host or dedicated VM, dedicated Unix user,
Jira token file mode 0600) serving several `launch-ai-dev.sh` VMs. Each VM's
MCP config holds only the server URL and its own client token. A leaked client
token grants only the allowlisted operations, not full Atlassian access.
