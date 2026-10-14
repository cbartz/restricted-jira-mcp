# Full-fidelity reads/writes and secure HTTP transport — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make restricted-jira-mcp lossless for agent read→update round trips and safe to serve over authenticated streamable HTTP without any Jira credential in the agent environment.

**Architecture:** New `adf.py` owns all ADF conversion (markdown→ADF on writes, ADF→text on reads). `jira_client.py` gains comment edit/delete (own-comment restricted), full-text compaction, and readable custom fields. `policy.wrap_jql` learns to preserve `ORDER BY`. New `http_auth.py` (hash file + ASGI bearer middleware) wraps the MCP streamable-HTTP app; `server.py` gains transport selection. Tests keep faking HTTP at the `requests.Session` level; HTTP-transport tests use Starlette `TestClient`.

**Tech Stack:** Python ≥3.11, `uv`, pytest (unittest-style tests), `markdown-it-py>=3` (new direct dependency, MIT), `mcp` 1.27.1 SDK (already locked), Starlette `TestClient`.

**Spec:** `docs/superpowers/specs/2026-10-14-full-text-and-secure-http-design.md`

## Global Constraints

- Security boundary: every Jira request path keeps `ensure_issue_allowed`/`ensure_response_issue_allowed`/`validate_update_fields`/custom-field allowlist checks **before** any HTTP call. New code paths included.
- TDD: failing test first, announce "Writing failing test..." → "Implementing to make it pass...". One comment block per test; happy path and error cases in separate tests; table-driven for multiple error scenarios.
- Never use a real Jira token or real client token in tests or commits; fake strings only.
- Never log tokens; never include tokens in error messages.
- Conventional commits (`type(scope): description`), lowercase imperative, no AI attribution trailers. Never commit on `main`.
- Run tests with `uv run pytest`. Full suite must stay green at every commit.
- Existing test style is unittest (`unittest.TestCase`) with module-level fakes; extend `FakeSession`, don't invent parallel helpers.

## Review Focus

- ADF containing node types the converter doesn't know (media, mention, panel): rendering must not crash and must not silently drop the issue's content → `tests/test_adf.py::test_unknown_nodes_render_descendant_text_without_raising`.
- JQL whose quoted string contains "order by" must not be split → `tests/test_policy.py::test_wrap_jql_keeps_order_by_inside_quotes`.
- Malformed `comment_id` (path traversal like `10001/../x`, non-numeric) must be rejected before any HTTP call → `tests/test_jira_client.py::test_update_comment_rejects_malformed_comment_id_before_http`.
- A `404` for the comment GET (comment not on that issue) must surface as `JiraClientError`, not be treated as "not own comment" → `tests/test_jira_client.py::test_update_comment_raises_when_jira_cannot_find_comment`.
- An empty client-token file must fail server startup, not disable auth (fail closed) → `tests/test_http_auth.py::test_load_client_token_hashes_rejects_empty_file`.

---

### Task 1: Feature branch and spec commit

**Files:**
- Commit: `docs/superpowers/specs/2026-10-14-full-text-and-secure-http-design.md`, `docs/superpowers/plans/2026-10-14-full-text-and-secure-http.md` (both already written)

- [ ] **Step 1: Create branch from main**

```bash
git checkout -b feat/full-text-and-secure-http
```

- [ ] **Step 2: Commit spec and plan**

```bash
git add docs/superpowers
git commit -m "docs: add design and implementation plan"
```

### Task 2: ADF→text renderer (`adf.py`)

**Files:**
- Create: `src/restricted_jira_mcp/adf.py`
- Test: `tests/test_adf.py`

**Interfaces:**
- Produces: `adf_to_text(value: Any) -> str | None` — renders an ADF doc/node to full-length readable markdown-ish text; returns `None` for falsy input; a bare `str` passes through unchanged. Later tasks (3, 7) and the README rely on this exact rendering.
- Rendering rules (pinned): block nodes separated by `"\n\n"`; `hardBreak` → `"\n"`; `paragraph`/`heading`/`listItem` inline content concatenated with no separator; marks: strong→`**x**`, em→`*x*`, code→`` `x` ``, link→`[text](href)`, strike→`~~x~~`; heading level n → `n × "#"` + space; `bulletList` items → `"- "` prefix, `orderedList` items → `"{n}. "` with `n` starting at the list's `attrs.order` (default 1); list nesting indents two spaces per level; `codeBlock` → fenced ```` ``` ```` block (language from `attrs.language`), content trailing newline stripped; `blockquote` lines prefixed `"> "`; tables → pipe rows `| a | b |` with header row from `tableHeader` cells followed by a `| --- | --- |` separator row, cell paragraphs joined by a space; unknown node types render their descendant text (space-joined) without raising.

- [ ] **Step 1: Write the failing tests** — `tests/test_adf.py`, `unittest.TestCase`, covering: paragraph with `hardBreak`; bold/em/code/link/strike marks; heading levels 1 and 3; bullet list with one nested bullet; ordered list with `attrs.order=2`; fenced codeBlock with and without language; blockquote; pipe table with header + one body row; `None` → `None`; bare string passthrough; long content (>800 chars) returned full length; `test_unknown_nodes_render_descendant_text_without_raising` (doc containing `{"type": "panel", "content": [paragraph "note"]}` and a `mention` node).

```python
def test_renders_paragraph_marks_and_lists():
    doc = {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [
            {"type": "text", "text": "Line one"},
            {"type": "hardBreak"},
            {"type": "text", "text": "line two"},
        ]},
        {"type": "paragraph", "content": [
            {"type": "text", "text": "bold", "marks": [{"type": "strong"}]},
            {"type": "text", "text": " and "},
            {"type": "text", "text": "link", "marks": [{"type": "link", "attrs": {"href": "https://x.y"}}]},
        ]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "a"}]}]},
            {"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "b"}]},
                {"type": "bulletList", "content": [
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "b1"}]}]},
                ]},
            ]},
        ]},
    ]}
    assert adf_to_text(doc) == (
        "Line one\nline two\n\n**bold** and [link](https://x.y)\n\n"
        "- a\n- b\n  - b1"
    )
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_adf.py -q` → ImportError (no module `restricted_jira_mcp.adf`).
- [ ] **Step 3: Implement `adf.py`** with `adf_to_text` plus private recursive helpers (`_render_blocks`, `_render_inline`). Reuse the text-extraction idea from `_extract_adf_text` but with structural rendering; do not import from `jira_client` (avoid cycles).
- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_adf.py -q` → all pass.
- [ ] **Step 5: Commit** — `feat(adf): render ADF documents to full-length readable text`

### Task 3: Full-text reads and explicit truncation flag

**Files:**
- Modify: `src/restricted_jira_mcp/jira_client.py` (`compact_issue`, `compact_comment`; drop `_adf_excerpt` and `COMMENT_BODY_LIMIT`, keep `MAX_COMMENTS_PER_PAGE`)
- Test: `tests/test_jira_client.py`

**Interfaces:**
- Consumes: `adf_to_text` from Task 2.
- Produces: `compact_issue(issue: dict, full_description: bool = False) -> dict`. When `full_description=True`: `description` is full text and the output has **no** `description_truncated` key. When `False` (search): `description` is an 800-char excerpt with `"..."` suffix when truncated, plus `description_truncated: bool`. `compact_comment` returns full body always.

- [ ] **Step 1: Write the failing tests**
  - `test_get_issue_returns_full_description`: payload description ADF with a 900-char paragraph → `issue["description"]` is the full 900 chars, no `"..."`, no `description_truncated` key.
  - `test_get_comments_returns_full_body`: comment body 2500 chars → full, no truncation marker.
  - `test_search_flags_truncated_descriptions`: table-driven, two cases — description ≤800 chars → `description_truncated` is `False`; description >800 chars → excerpt of 800 + `"..."` and `description_truncated` is `True`.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_jira_client.py -k full_or_truncated -q` → failures (truncation still at 800, flag missing).
- [ ] **Step 3: Implement** — `compact_issue` gains `full_description` param; `get_issue` calls `compact_issue(payload, full_description=True)`; `search` keeps `compact_issue(issue)`; excerpt logic uses `adf_to_text` then slices at 800. Delete `_adf_excerpt` and `COMMENT_BODY_LIMIT`.
- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_jira_client.py tests/test_adf.py -q`.
- [ ] **Step 5: Commit** — `feat(reads): return full descriptions and comment bodies with truncation flags`

### Task 4: Preserve `ORDER BY` when wrapping JQL

**Files:**
- Modify: `src/restricted_jira_mcp/policy.py` (`wrap_jql`, new module-level `_split_order_by`)
- Test: `tests/test_policy.py`

**Interfaces:**
- Produces: `_split_order_by(jql: str) -> tuple[str, str | None]` — splits a trailing `ORDER BY` clause (case-insensitive, only outside quotes) returning `(body, order_clause)` where `order_clause` is `None` when absent; `wrap_jql` then emits `project in (...) AND (body) ORDER BY ...` (or `project in (...) ORDER BY ...` when body is empty).

- [ ] **Step 1: Write the failing tests** (table-driven):
  - `("status = Done ORDER BY created ASC", "project in (ISD) AND (status = Done) ORDER BY created ASC")`
  - `("summary ~ \"please order by date\"", "project in (ISD) AND (summary ~ \"please order by date\")")` — quoted, no split
  - `('text = "order by x" ORDER BY created', "project in (ISD) AND (text = \"order by x\") ORDER BY created")` — real trailing split after quoted occurrence
  - `("order by created", "project in (ISD) ORDER BY created")` — body empty, no `AND`
  - `("status = 'open' order by key desc", "... AND (status = 'open') order by key desc")` — single quotes, lowercase
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_policy.py -q` → the new tests fail.
- [ ] **Step 3: Implement** `_split_order_by`: scan char-by-char tracking single/double-quote state; find each top-level (outside-quotes) case-insensitive `order\s+by` occurrence with whitespace on both sides; take the **last** one whose remainder contains no quote characters; split there. `wrap_jql` composes as in Interfaces.
- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_policy.py tests/test_jira_client.py -q` (client search tests must stay green).
- [ ] **Step 5: Commit** — `fix(search): preserve trailing ORDER BY when wrapping JQL`

### Task 5: Markdown→ADF converter

**Files:**
- Modify: `pyproject.toml` (add `markdown-it-py>=3`), `uv.lock` (via `uv add`)
- Modify: `src/restricted_jira_mcp/adf.py`
- Test: `tests/test_adf.py`

**Interfaces:**
- Produces: `markdown_to_adf(text: str) -> dict` — CommonMark (+ table, strikethrough rules) via `MarkdownIt("commonmark").enable(["table", "strikethrough"])`, walked as `SyntaxTreeNode`; and `as_adf(value: str | dict) -> dict` — markdown string → `markdown_to_adf`; dict with `type == "doc"` and a list `content` → returned unchanged; anything else → `ValueError("... must be a Markdown string or an ADF doc object")`.
- Node mapping (pinned): root → `{"type": "doc", "version": 1, "content": [...]}`; `heading` → `heading` with `attrs.level` = int(tag[1]); `paragraph` → `paragraph`; `bullet_list` → `bulletList`; `ordered_list` → `orderedList` with `attrs.order` = token `start` (default 1); `list_item` → `listItem` wrapping child blocks; `fence`/`code_block` → `codeBlock` with `attrs.language` from fence info (omitted when empty), content minus trailing newline; `blockquote` → `blockquote`; `table` → `table` > `tableRow` > `tableHeader` (th) / `tableCell` (td), each cell containing its child paragraphs (flatten `thead`/`tbody`/`tr` wrappers); `hr` → `rule`; inline: `text` → text node, `strong`→strong mark, `em`→em mark, `code_inline`→code mark, `s`→strike mark, `link`→link mark with `attrs.href`, `hardbreak`→`hardBreak` node, `softbreak`→`hardBreak` node (line breaks are preserved, not merged), `image` → text node with alt text plus link mark to `src` (ADF media needs upload; images degrade to links).

- [ ] **Step 1: Write the failing tests** (separate test per structure, one comment block each): headings + paragraphs split on blank lines; bullet and ordered lists (incl. `start` attr); fenced code with language; bold/italic/inline-code/strikethrough marks; `[text](url)` link mark; hard break via two trailing spaces AND soft break via single newline both produce `hardBreak`; simple pipe table → table/tableRow/tableHeader/tableCell; `as_adf` passthrough of a valid ADF dict; `as_adf` rejects `{"type": "paragraph"}` (ValueError), a list, an int; `as_adf("")` → `{"type": "doc", "version": 1, "content": []}`.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_adf.py -k markdown -q` → failures.
- [ ] **Step 3: Add dependency** — `uv add "markdown-it-py>=3"` then implement `markdown_to_adf` + `as_adf` in `adf.py`.
- [ ] **Step 4: Run to verify pass** — `uv run pytest -q` (full suite; the lock change must not disturb anything).
- [ ] **Step 5: Commit** — `feat(adf): convert markdown to ADF documents`

### Task 6: Accept Markdown or raw ADF on writes

**Files:**
- Modify: `src/restricted_jira_mcp/jira_client.py` (`_normalize_fields`, `create_issue`, `add_comment`)
- Modify: `src/restricted_jira_mcp/server.py` (docstrings only for `jira_get_issue`, `jira_create_issue`, `jira_update_issue`, `jira_add_comment`)
- Test: `tests/test_jira_client.py`

**Interfaces:**
- Consumes: `as_adf` from Task 5.
- Produces: `description` (create + update) and comment `body` accept `str` (Markdown) or ADF `dict`; invalid dict raises `ValueError`. Docstrings say: "body accepts Markdown (headings, lists, bold/italic/code, links, tables) or a raw ADF doc dict; wiki markup is not supported".

- [ ] **Step 1: Write the failing tests**
  - `test_update_issue_converts_markdown_description`: `update_issue("ISD-5444", {"description": "## Plan\n\n- do it"})` → PUT body `fields["description"]` is an ADF doc with `heading(level=2)` and `bulletList`.
  - `test_update_issue_passes_raw_adf_description`: `{"description": adf_doc("raw")}` → PUT body contains the same dict unchanged.
  - `test_update_issue_rejects_invalid_adf_description`: `{"description": {"type": "paragraph"}}` → `ValueError`, zero session calls.
  - `test_create_issue_converts_markdown_description` and `test_add_comment_converts_markdown_body`: same pattern for POST paths.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_jira_client.py -k "markdown or adf" -q` → failures (old `adf_doc` puts everything in one paragraph).
- [ ] **Step 3: Implement** — `create_issue` and `_normalize_fields` route `description` through `as_adf`; `add_comment` routes `body` through `as_adf`. Keep `adf_doc` exported (still used by comment fixtures) but only as the single-paragraph primitive it already is.
- [ ] **Step 4: Run to verify pass** — `uv run pytest -q`.
- [ ] **Step 5: Commit** — `feat(writes): accept markdown or raw ADF for descriptions and comment bodies`

### Task 7: Readable allowlisted custom fields

**Files:**
- Modify: `src/restricted_jira_mcp/jira_client.py` (`get_issue`, new `_requested_fields`, `compact_issue` stays as-is)
- Test: `tests/test_jira_client.py`

**Interfaces:**
- Consumes: `adf_to_text` (Task 2), `policy.allowed_custom_fields`.
- Produces: `get_issue` requests `ISSUE_FIELDS + allowed_custom_fields` (dedup, stable order) and returns `"custom_fields": {field_id: readable_value}` where a dict with `type == "doc"` renders via `adf_to_text` (full length); any other dict or list is `json.dumps`-ed (a select option is not ADF — agents must see the raw value, not mangled text); scalars pass through unchanged. Search does **not** request custom fields (stays compact).

- [ ] **Step 1: Write the failing tests**
  - `test_get_issue_requests_and_returns_custom_fields`: payload `fields["customfield_12345"] = {"type": "doc", ..., paragraph "Acceptance: it works"}` → GET `params["fields"]` contains `customfield_12345`; result `custom_fields == {"customfield_12345": "Acceptance: it works"}`.
  - `test_get_issue_passes_through_scalar_custom_field`: payload value `"42"` → `custom_fields == {"customfield_12345": "42"}`.
  - `test_get_issue_dumps_non_adf_dict_custom_field`: payload value `{"value": "Blocked", "id": "1"}` → `json.dumps`-ed, not run through `adf_to_text`.
  - `test_search_does_not_request_custom_fields`: search request `fields` list excludes `customfield_12345`.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_jira_client.py -k custom_field -q` → failures.
- [ ] **Step 3: Implement** — `_requested_fields(self, base: list[str]) -> list[str]`; `get_issue` uses it and appends `custom_fields` from `payload["fields"]` via `_custom_fields_view(...)`.
- [ ] **Step 4: Run to verify pass** — `uv run pytest -q`.
- [ ] **Step 5: Commit** — `feat(reads): return allowlisted custom fields on jira_get_issue`

### Task 8: Comment edit/delete, restricted to own comments

**Files:**
- Modify: `src/restricted_jira_mcp/jira_client.py` (`update_comment`, `delete_comment`, `_myself_account_id`, `_ensure_own_comment`, `_COMMENT_ID_RE`)
- Modify: `src/restricted_jira_mcp/server.py` (new tools `jira_update_comment`, `jira_delete_comment` with docstrings stating the own-comment restriction)
- Test: `tests/test_jira_client.py`

**Interfaces:**
- Consumes: `as_adf` (Task 5).
- Produces:
  - `update_comment(issue_key: str, comment_id: str, body: str | dict) -> dict` → `{"status": "updated", "issue_key": KEY, "comment_id": ID}`
  - `delete_comment(issue_key: str, comment_id: str) -> dict` → `{"status": "deleted", "issue_key": KEY, "comment_id": ID}`
  - Flow for both: `ensure_issue_allowed` → `_COMMENT_ID_RE` (`^\d+$`, else `ValueError`) → `_myself_account_id()` (cached `GET /rest/api/3/myself`) → `GET /rest/api/3/issue/{KEY}/comment/{ID}` (raises `JiraClientError` on 404 — proves the comment belongs to the issue) → compare `author.accountId` with own account id (`JiraClientError` on mismatch) → `PUT`/`DELETE` the same path. REST path scoping means a comment id from another issue can never match.
  - Test-helper change: `FakeSession` gains a `delete` method and an optional `get_responses` queue (list popped per GET call) so multi-GET flows are deterministic; existing tests keep using `next_get`.

- [ ] **Step 1: Write the failing tests**
  - `test_update_comment_puts_adf_body_to_scoped_path`: fake myself `{"accountId": "acc-1"}`, comment payload `comment_payload("10001", "old")` → calls `GET /rest/api/3/myself`, `GET /rest/api/3/issue/ISD-5444/comment/10001`, `PUT .../comment/10001` with `json={"body": as_adf("new text")}`; result `{"status": "updated", "issue_key": "ISD-5444", "comment_id": "10001"}`.
  - `test_update_comment_rejects_foreign_author`: comment author `acc-2` → `JiraClientError` mentioning "own comments", only the two GETs happened.
  - `test_delete_comment_deletes_scoped_path`: same flow, `DELETE`, `{"status": "deleted", ...}`.
  - Error table (`subTest`): disallowed issue key → `PolicyError` with zero calls; malformed comment id `"10001/../x"` and `"abc"` → `ValueError` with zero calls; comment GET returns 404 → `JiraClientError` mentioning the comment id.
  - `test_myself_called_once_across_operations`: two updates on the same client → exactly one `/myself` call.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_jira_client.py -k comment -q` → AttributeError (no `update_comment`).
- [ ] **Step 3: Implement** the four client methods + `_COMMENT_ID_RE`; register the two tools in `server.py` with docstrings documenting Markdown/ADF body and the own-comment rule.
- [ ] **Step 4: Run to verify pass** — `uv run pytest -q`.
- [ ] **Step 5: Commit** — `feat(comments): add comment edit and delete restricted to own comments`

### Task 9: Load the Jira API token from a file

**Files:**
- Modify: `src/restricted_jira_mcp/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `JiraConfig.from_env()` accepts `JIRA_API_TOKEN_FILE` (path, UTF-8, stripped of surrounding whitespace); `JIRA_API_TOKEN` still works; setting both → `ValueError("Set only one of JIRA_API_TOKEN and JIRA_API_TOKEN_FILE")`; neither → the existing missing-required error listing `JIRA_API_TOKEN`; empty file → `ValueError` naming the path.

- [ ] **Step 1: Write the failing tests** — `tests/test_config.py` (`unittest.TestCase`, `unittest.mock.patch.dict(os.environ)`): token from env (existing); token from file via `tempfile` (content `"secret\n"` → `"secret"`); both set → `ValueError`; file missing → `ValueError` naming the path; empty file → `ValueError`; neither set → missing-required `ValueError` mentioning `JIRA_API_TOKEN`.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_config.py -q`.
- [ ] **Step 3: Implement** `_load_api_token()` in `config.py`; `from_env` drops `JIRA_API_TOKEN` from the hard-required list and calls `_load_api_token()`.
- [ ] **Step 4: Run to verify pass** — `uv run pytest -q`.
- [ ] **Step 5: Commit** — `feat(config): load the Jira API token from a file`

### Task 10: Client-token hash file and bearer auth middleware

**Files:**
- Create: `src/restricted_jira_mcp/http_auth.py`
- Create: `tests/test_http_auth.py`

**Interfaces:**
- Produces:
  - `load_client_token_hashes(path: str | Path) -> tuple[str, ...]` — lowercase SHA-256 hex digests (64 hex chars per line, normalized to lowercase); `#` comments and blank lines skipped; any other line → `ValueError`; empty result → `ValueError` (fail closed).
  - `BearerAuthMiddleware` — pure ASGI wrapper; `__init__(self, app, token_hashes: Iterable[str])`; passes `lifespan` scopes through; for `http` scopes requires `Authorization: Bearer <token>` where `sha256(token).hexdigest()` matches any stored hash via `hmac.compare_digest`; on failure responds `401` with JSON `{"error": "unauthorized"}` and `WWW-Authenticate: Bearer`; on success calls the wrapped app. Never logs tokens.

- [ ] **Step 1: Write the failing tests** — hash-file loading table (valid mixed-case hex + comments + blank lines; invalid short line → `ValueError`; empty file → `ValueError`); middleware over a dummy app returning 200 via Starlette `TestClient`: missing header → 401; wrong token → 401; `Basic xyz` scheme → 401; bare `Bearer` with no token → 401; valid token → 200; valid token from a file-loaded hash → 200.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_http_auth.py -q` → ImportError.
- [ ] **Step 3: Implement** `http_auth.py`.
- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_http_auth.py -q`.
- [ ] **Step 5: Commit** — `feat(http): bearer-token auth against a client-token hash file`

### Task 11: Streamable HTTP transport wiring

**Files:**
- Modify: `src/restricted_jira_mcp/server.py` (`create_server(client=None)`, `build_http_app(client)`, `main()` argparse)
- Create: `tests/test_http_server.py`

**Interfaces:**
- Consumes: `BearerAuthMiddleware`, `load_client_token_hashes` (Task 10).
- Produces:
  - `create_server(client: JiraClient | None = None)` — builds `JiraClient.from_env()` when no client is given (existing behaviour unchanged); registers all tools.
  - `build_http_app(client: JiraClient) -> ASGI app` — `FastMCP("restricted-jira-mcp", host=host, port=port, stateless_http=True, json_response=True).streamable_http_app()` wrapped in `BearerAuthMiddleware`; token hashes from `JIRA_MCP_CLIENT_TOKENS_FILE` (missing/empty → `ValueError` at startup, fail closed).
  - `main()` argparse: `--transport {stdio,http}` (default: `$JIRA_MCP_TRANSPORT` or `"stdio"`), `--host` (default `127.0.0.1`), `--port` (default `8000`). stdio → `create_server().run()`; http → `uvicorn.run(build_http_app(client), host=..., port=...)`.

- [ ] **Step 1: Write the failing tests** — `tests/test_http_server.py` builds a real `JiraClient` over `FakeSession` (allowlist `("ISD",)`, custom field `customfield_12345`), wraps with hashes of `"client-token-1"`, and uses `TestClient(app, base_url="http://127.0.0.1:8000")` inside `with` (lifespan):
  - `test_http_rejects_missing_token`: POST `/mcp` `tools/call` → 401, JSON body `{"error": "unauthorized"}`, no session calls.
  - `test_http_rejects_wrong_token`: `Bearer nope` → 401, no session calls.
  - `test_http_enforces_allowlist_for_authenticated_call`: valid bearer, `tools/call jira_get_issue {"issue_key": "NDA-1"}` → 200 with JSON-RPC result `isError` true and the policy message in the text content; `FakeSession.calls == []`.
  - `test_http_returns_issue_for_authenticated_call`: valid bearer, `jira_get_issue ISD-5444` → 200, content text parses as JSON with `key == "ISD-5444"`.
  - Request headers: `Accept: application/json, text/event-stream`; body `{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": ..., "arguments": {...}}}` (verified working against the SDK in stateless JSON mode).
  - Also `test_create_server_uses_injected_client`: `create_server(client)` returns the FastMCP instance listing the two new comment tools (via `mcp._tool_manager` or a `list_tools()` call — pick whatever the SDK exposes).
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_http_server.py -q` → failures (no `build_http_app`, 401 never happens).
- [ ] **Step 3: Implement** the server.py changes (argparse + `build_http_app`; move tool registration onto the injected client; add docstrings).
- [ ] **Step 4: Run to verify pass** — `uv run pytest -q`.
- [ ] **Step 5: Commit** — `feat(server): streamable HTTP transport with per-client bearer tokens`

### Task 12: README, full suite, draft PR

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**
  - Configuration: `JIRA_API_TOKEN_FILE` (dedicated Unix user, mode 0600), "set only one" rule.
  - Tools list: add `jira_update_comment(issue_key, comment_id, body)` and `jira_delete_comment(issue_key, comment_id)`; note both are restricted to comments authored by the configured user (why, one line).
  - New/changed behaviour: `jira_get_issue`/`jira_get_comments` return full text; `jira_search` descriptions stay compact with `description_truncated`; allowlisted custom fields returned on `jira_get_issue` as `custom_fields`.
  - Accepted body formats: Markdown (headings, lists, bold/italic/code, links, tables; line breaks preserved) or raw ADF doc dict; wiki markup is not supported.
  - `jira_search` supports trailing `ORDER BY`.
  - New section "Running over HTTP": `--transport http --host 127.0.0.1 --port 8000`, `JIRA_MCP_CLIENT_TOKENS_FILE` format (one SHA-256 hex per line; `printf '%s' 'token' | sha256sum` to make one), per-VM client tokens, and the target deployment: one server outside the agent VMs, VM configs hold only URL + client token.
  - Include the exact Copilot CLI HTTP config block for `~/.copilot/mcp-config.json` (`"type": "http"`, `"url"`, `"headers": {"Authorization": "Bearer <client-token>"}`, `"tools": ["*"]`), the SSH tunnel as the default way to reach a 127.0.0.1-bound server (`ssh -N -L 8000:127.0.0.1:8000 <host>` keeps the Host header the SDK expects), the TLS reverse-proxy alternative with a note about the SDK host-header/DNS-rebinding check, and a troubleshooting line for Copilot's OAuth-discovery quirk (github/copilot-cli#3100): run `copilot mcp enable restricted-jira` once if the first connect fails.
  - Replace the stale "Keep the Jira token only in Copilot's local MCP configuration" guidance: with the HTTP deployment the agent VMs hold no Jira token at all.
- [ ] **Step 2: Full suite and CLI check** — `uv run pytest -q` → all green; `uv run python -m restricted_jira_mcp.server --help` prints the transport/host/port flags and exits 0 without any env vars set (argparse runs before config loading).
- [ ] **Step 3: Draft PR** — push branch, `gh pr create --draft` (no template exists in the repo); concise summary sections per problem; PR body ends with `_AI-generated message._`; title `feat: full-fidelity reads/writes and secure HTTP transport`.

### Verification (done-when checklist)

- [ ] `uv run pytest` green, including new `test_adf.py`, `test_config.py`, `test_http_auth.py`, `test_http_server.py` and extended `test_policy.py` / `test_jira_client.py`.
- [ ] All six problems demonstrably fixed by a named test each (problem 1 → Task 3; 2 → Tasks 5+6; 3 → Task 8; 4 → Task 7; 5 → Task 4; 6 → Tasks 9–11).
- [ ] README documents new/changed tools and accepted body formats.
- [ ] No live Jira calls made from this VM; draft PR open.
