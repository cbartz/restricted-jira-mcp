from __future__ import annotations

from typing import Any

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode


def adf_to_text(value: Any) -> str | None:
    """Render an ADF doc/node to full-length readable text.
    
    Args:
        value: ADF document or node to render
        
    Returns:
        Rendered text as string, None for falsy input, or bare string passes through unchanged
    """
    if not value:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value.get("type") == "doc":
        return _render_blocks(value.get("content", []))
    elif isinstance(value, dict):
        # For single unknown nodes, render as inline content
        return _render_inline_node(value)
    return ""


_BLOCK_TYPES = frozenset(
    {"paragraph", "heading", "bulletList", "orderedList", "codeBlock", "blockquote", "table"}
)


def _render_blocks(nodes: list[Any]) -> str:
    """Render a list of block nodes with proper separation, in document order."""
    if not nodes:
        return ""
    blocks = []
    for node in nodes:
        if isinstance(node, dict):
            block = _render_block(node)
            if block:
                blocks.append(block)
    return "\n\n".join(blocks)


def _render_block(node: dict[str, Any]) -> str:
    """Render a single block node."""
    node_type = node.get("type")

    if node_type == "paragraph":
        return _render_inline(node.get("content", []))
    elif node_type == "heading":
        level = node.get("attrs", {}).get("level", 1)
        text = _render_inline(node.get("content", []))
        return f"{'#' * level} {text}"
    elif node_type == "bulletList":
        items = node.get("content", [])
        return "\n".join(_render_list_item(item, "- ") for item in items)
    elif node_type == "orderedList":
        items = node.get("content", [])
        order = node.get("attrs", {}).get("order", 1)
        return "\n".join(_render_list_item(item, f"{i + order}. ") for i, item in enumerate(items))
    elif node_type == "codeBlock":
        content = node.get("content", [])
        language = node.get("attrs", {}).get("language")
        text = _render_inline(content).rstrip()
        if language:
            return f"```{language}\n{text}\n```"
        return f"```\n{text}\n```"
    elif node_type == "blockquote":
        return _render_blockquote(node)
    elif node_type == "table":
        return _render_table(node)
    else:
        # Unknown node type: render block children structurally and inline
        # children as text, keeping document order.
        return _render_unknown_block(node)


def _render_unknown_block(node: dict[str, Any]) -> str:
    """Render an unknown block container so its children stay ordered and separated."""
    parts = []
    for child in node.get("content", []):
        if not isinstance(child, dict):
            continue
        part = _render_block(child) if _is_block_node(child) else _render_inline_node(child)
        if part:
            parts.append(part)
    return "\n\n".join(parts)


def _is_block_node(node: dict[str, Any]) -> bool:
    """True for known block types and unknown containers holding block children."""
    if node.get("type") in _BLOCK_TYPES:
        return True
    return any(
        isinstance(child, dict) and _is_block_node(child)
        for child in node.get("content", [])
    )


def _render_blockquote(node: dict[str, Any]) -> str:
    """Render a blockquote with every line carrying the quote prefix."""
    inner = _render_blocks(node.get("content", []))
    if not inner:
        return ""
    return "\n".join(f"> {line}" if line else ">" for line in inner.split("\n"))


def _render_list_item(item: dict[str, Any], prefix: str) -> str:
    """Render a list item: marker on the first line, continuation lines
    indented to the marker's width so nested content stays nested on re-parse."""
    content = item.get("content", [])
    if not content:
        return ""
    indent = " " * len(prefix)
    lines: list[str] = []
    for child in content:
        if not isinstance(child, dict):
            continue
        if child.get("type") in ("bulletList", "orderedList"):
            nested = _render_blocks([child])
            for line in nested.split("\n"):
                if line.strip():
                    lines.append(indent + line)
        else:
            child_text = _render_block(child) if _is_block_node(child) else _render_inline_node(child)
            if not child_text:
                continue
            child_lines = child_text.split("\n")
            if lines:
                lines.extend(indent + line for line in child_lines)
            else:
                lines.extend(child_lines)
    if not lines:
        return ""
    lines[0] = prefix + lines[0]
    return "\n".join(lines)


def _render_table(node: dict[str, Any]) -> str:
    """Render a table keeping every row in document order.

    Markdown pipe tables require a header, so the first row serves as it
    (whether ADF marks it tableHeader or tableCell); any further header rows
    render as body rows. This preserves all cell text across a read→update
    round trip.
    """
    rows = [
        row
        for row in node.get("content", [])
        if isinstance(row, dict) and row.get("type") == "tableRow"
    ]
    if not rows:
        return ""
    rendered = []
    for row in rows:
        cells = [cell for cell in row.get("content", []) if isinstance(cell, dict)]
        texts = [_render_cell(cell) for cell in cells]
        rendered.append("| " + " | ".join(texts) + " |")
    first_row_cells = [cell for cell in rows[0].get("content", []) if isinstance(cell, dict)]
    separator = "| " + " | ".join(["---"] * len(first_row_cells)) + " |"
    return "\n".join([rendered[0], separator] + rendered[1:])


def _render_cell(cell: dict[str, Any]) -> str:
    """Render a table cell, joining its child blocks' texts with single spaces."""
    parts = []
    for child in cell.get("content", []):
        if isinstance(child, dict):
            part = _render_block(child)
            if part:
                parts.append(part)
    return " ".join(parts)


def _render_inline(nodes: list[Any]) -> str:
    """Render a list of inline nodes with proper formatting."""
    if not nodes:
        return ""
    
    parts = []
    for node in nodes:
        if isinstance(node, dict):
            part = _render_inline_node(node)
            if part:
                parts.append(part)
    
    return "".join(parts)


def _render_inline_node(node: dict[str, Any]) -> str:
    """Render a single inline node."""
    node_type = node.get("type")
    
    if node_type == "text":
        text = node.get("text", "")
        # Apply marks to this text node
        marks = node.get("marks", [])
        for mark in reversed(marks):
            mark_type = mark.get("type")
            if mark_type == "strong":
                text = f"**{text}**"
            elif mark_type == "em":
                text = f"*{text}*"
            elif mark_type == "code":
                text = f"`{text}`"
            elif mark_type == "link":
                href = mark.get("attrs", {}).get("href", "")
                text = f"[{text}]({href})"
            elif mark_type == "strike":
                text = f"~~{text}~~"
        return text
    elif node_type == "hardBreak":
        return "\n"
    elif node_type == "mention":
        # Check for text in attrs first, then in content
        text = node.get("attrs", {}).get("text", "")
        if not text:
            text = _render_inline(node.get("content", []))
        return text
    else:
        # For other unknown inline nodes, try to render their content
        content = node.get("content", [])
        return _render_inline(content)


# Parser for the Markdown → ADF write path: CommonMark plus the table and
# strikethrough rules (no further extensions).
_MARKDOWN_PARSER = MarkdownIt("commonmark").enable(["table", "strikethrough"])

# Inline container node type → ADF mark type.
_MARK_TYPES = {"strong": "strong", "em": "em", "s": "strike"}


def markdown_to_adf(text: str) -> dict:
    """Convert Markdown text to an ADF document.

    Args:
        text: Markdown source (CommonMark plus table/strikethrough rules)

    Returns:
        ADF document dict with type "doc" and one content node per markdown block
    """
    root = SyntaxTreeNode(_MARKDOWN_PARSER.parse(text))
    return {"type": "doc", "version": 1, "content": _convert_blocks(root.children)}


def as_adf(value: str | dict) -> dict:
    """Coerce a value into an ADF document.

    Args:
        value: Markdown string (converted via markdown_to_adf) or an ADF doc
            object (type "doc" with list content), which passes through unchanged

    Returns:
        ADF document dict

    Raises:
        ValueError: if value is neither a Markdown string nor an ADF doc object
    """
    if isinstance(value, str):
        return markdown_to_adf(value)
    if isinstance(value, dict) and value.get("type") == "doc" and isinstance(value.get("content"), list):
        return value
    raise ValueError(f"as_adf() expects a Markdown string or an ADF doc object, got {_describe_rejected(value)}")


def _describe_rejected(value: Any) -> str:
    """Name the rejected value's type for the as_adf error message."""
    if isinstance(value, dict):
        if "type" in value:
            return f"dict with type {value['type']!r}"
        return "dict"
    return type(value).__name__


def _convert_blocks(nodes: list[SyntaxTreeNode]) -> list[dict]:
    """Convert tree nodes to ADF blocks, skipping anything that yields nothing."""
    blocks = []
    for node in nodes:
        block = _convert_block(node)
        if block:
            blocks.append(block)
    return blocks


def _convert_block(node: SyntaxTreeNode) -> dict | None:
    """Convert one block-level tree node to an ADF block node."""
    node_type = node.type
    if node_type == "heading":
        return {"type": "heading", "attrs": {"level": int(node.tag[1])}, "content": _inline_content(node)}
    if node_type == "paragraph":
        return {"type": "paragraph", "content": _inline_content(node)}
    if node_type == "bullet_list":
        return {"type": "bulletList", "content": _convert_blocks(node.children)}
    if node_type == "ordered_list":
        start = node.attrGet("start")
        order = int(start) if start is not None else 1
        return {"type": "orderedList", "attrs": {"order": order}, "content": _convert_blocks(node.children)}
    if node_type == "list_item":
        return {"type": "listItem", "content": _convert_blocks(node.children)}
    if node_type in ("fence", "code_block"):
        return _convert_code_block(node)
    if node_type == "blockquote":
        return {"type": "blockquote", "content": _convert_blocks(node.children)}
    if node_type == "table":
        return _convert_table(node)
    if node_type == "hr":
        return {"type": "rule"}
    # Unknown block: keep its descendant text so nothing is silently dropped.
    text = _descendant_text(node)
    if text:
        return {"type": "paragraph", "content": [_text_node(text, [])]}
    return None


def _convert_code_block(node: SyntaxTreeNode) -> dict:
    """Convert a fence or indented code_block node to a codeBlock node."""
    text = node.content
    if text.endswith("\n"):
        text = text[:-1]
    # ADF rejects empty text nodes, so an empty code block carries no content.
    content: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    block: dict[str, Any] = {"type": "codeBlock", "content": content}
    language = node.info.split()[0] if node.info.strip() else ""
    if language:
        block["attrs"] = {"language": language}
    return block


def _convert_table(node: SyntaxTreeNode) -> dict:
    """Convert a table node, flattening thead/tbody/tr wrappers into tableRows."""
    rows = []
    for section in node.children:
        if section.type in ("thead", "tbody"):
            tr_nodes = section.children
        elif section.type == "tr":
            tr_nodes = [section]
        else:
            continue
        for tr in tr_nodes:
            cells = []
            for cell in tr.children:
                if cell.type == "th":
                    cells.append({"type": "tableHeader", "content": _cell_content(cell)})
                elif cell.type == "td":
                    cells.append({"type": "tableCell", "content": _cell_content(cell)})
            rows.append({"type": "tableRow", "content": cells})
    return {"type": "table", "content": rows}


def _cell_content(cell: SyntaxTreeNode) -> list[dict]:
    """Convert a th/td node's children into the paragraphs it contains."""
    paragraphs = []
    for child in cell.children:
        if child.type == "inline":
            paragraphs.append({"type": "paragraph", "content": _inline_content(child)})
        else:
            block = _convert_block(child)
            if block:
                paragraphs.append(block)
    return paragraphs


def _inline_content(node: SyntaxTreeNode) -> list[dict]:
    """Convert a block node's inline children to ADF inline nodes."""
    inline_nodes = []
    for child in node.children:
        inline_nodes.extend(_convert_inline_node(child, []))
    return inline_nodes


def _convert_inline_nodes(node: SyntaxTreeNode, marks: list[dict]) -> list[dict]:
    """Convert an inline node's children, applying the accumulated marks."""
    inline_nodes = []
    for child in node.children:
        inline_nodes.extend(_convert_inline_node(child, marks))
    return inline_nodes


def _convert_inline_node(node: SyntaxTreeNode, marks: list[dict]) -> list[dict]:
    """Convert one inline tree node to zero or more ADF inline nodes."""
    node_type = node.type
    if node_type == "inline":
        return _convert_inline_nodes(node, marks)
    if node_type in ("text", "text_special"):
        # markdown-it emits empty text tokens around emphasis boundaries; skip them
        if not node.content:
            return []
        return [_text_node(node.content, marks)]
    if node_type == "code_inline":
        return [_text_node(node.content, marks + [{"type": "code"}])]
    if node_type in ("hardbreak", "softbreak"):
        return [{"type": "hardBreak"}]
    if node_type == "image":
        # ADF media needs upload; images degrade to their alt text as a link to
        # src. An empty alt falls back to the URL so the node stays nonempty.
        src = node.attrGet("src")
        label = node.content or src or ""
        if not label:
            return []
        link_mark = {"type": "link", "attrs": {"href": src}}
        return [_text_node(label, marks + [link_mark])]
    if node_type == "link":
        attrs: dict[str, Any] = {"href": node.attrGet("href")}
        title = node.attrGet("title")
        if title is not None:
            attrs["title"] = title
        nodes = _convert_inline_nodes(node, marks + [{"type": "link", "attrs": attrs}])
        if not nodes:
            # Empty link text: keep the target as the label so the URL survives.
            href = attrs["href"]
            if href:
                nodes = [_text_node(href, marks + [{"type": "link", "attrs": attrs}])]
        return nodes
    if node_type in _MARK_TYPES:
        return _convert_inline_nodes(node, marks + [{"type": _MARK_TYPES[node_type]}])
    # Unknown inline node: recurse into children, or keep its text so nothing
    # is silently dropped.
    if node.children:
        return _convert_inline_nodes(node, marks)
    if node.content:
        return [_text_node(node.content, marks)]
    return []


def _text_node(text: str, marks: list[dict]) -> dict:
    """Build an ADF text node, omitting the marks key when there are none."""
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


def _descendant_text(node: SyntaxTreeNode) -> str:
    """Collect the plain text content of a subtree of tree nodes."""
    if node.children:
        return "".join(_descendant_text(child) for child in node.children)
    return node.content or ""