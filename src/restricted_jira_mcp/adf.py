from __future__ import annotations

from typing import Any


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


def _render_blocks(nodes: list[Any]) -> str:
    """Render a list of block nodes with proper separation."""
    if not nodes:
        return ""
    
    blocks = []
    unknown_texts = []
    
    for node in nodes:
        if isinstance(node, dict):
            node_type = node.get("type")
            if node_type == "paragraph" or node_type in ("heading", "bulletList", "orderedList", "codeBlock", "blockquote", "table"):
                # These are known block types
                block = _render_block(node)
                if block:
                    blocks.append(block)
            else:
                # Unknown node types - collect their text
                inline = _render_inline_node(node)
                if inline:
                    unknown_texts.append(inline)
    
    # Join unknown nodes with spaces
    unknown_content = " ".join(unknown_texts) if unknown_texts else ""
    
    # Combine blocks and unknown content
    if blocks and unknown_content:
        return "\n\n".join(blocks + [unknown_content])
    elif blocks:
        return "\n\n".join(blocks)
    elif unknown_content:
        return unknown_content
    else:
        return ""


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
        content = node.get("content", [])
        text = _render_inline(content)
        return f"> {text}".strip()
    elif node_type == "table":
        return _render_table(node)
    else:
        # Unknown node type - render descendant text
        content = node.get("content", [])
        if content:
            return _render_inline(content)
        return ""


def _render_list_item(item: dict[str, Any], prefix: str) -> str:
    """Render a list item with proper indentation."""
    content = item.get("content", [])
    if not content:
        return ""
    
    # Check if this is a nested list
    has_nested_list = False
    for child in content:
        if isinstance(child, dict) and child.get("type") in ("bulletList", "orderedList"):
            has_nested_list = True
            break
    
    if has_nested_list:
        # For nested lists, render each block separately with proper indentation
        lines = []
        for child in content:
            if isinstance(child, dict):
                if child.get("type") in ("bulletList", "orderedList"):
                    # Render nested list with indentation
                    nested_text = _render_blocks([child])
                    nested_lines = nested_text.split("\n")
                    for line in nested_lines:
                        if line.strip():  # Skip empty lines
                            lines.append(f"  {line}")
                        else:
                            lines.append(line)
                else:
                    # Render other content with indentation
                    child_text = _render_block(child)
                    if child_text:
                        lines.append(f"  {child_text}")
        # Add the prefix to the first line
        if lines:
            lines[0] = f"{prefix}{lines[0].lstrip()}"
        return "\n".join(lines)
    else:
        # For simple list items, render content as inline
        text = _render_inline(content)
        return f"{prefix}{text}"


def _render_table(node: dict[str, Any]) -> str:
    """Render a table node."""
    content = node.get("content", [])
    if not content:
        return ""
    
    # Find header and body rows
    header_row = None
    body_rows = []
    
    for row in content:
        if isinstance(row, dict) and row.get("type") == "tableRow":
            # Check if this row contains headers
            has_header = any(cell.get("type") == "tableHeader" for cell in row.get("content", []))
            if has_header:
                header_row = row
            else:
                body_rows.append(row)
    
    if not header_row:
        return ""
    
    # Render header row
    header_cells = header_row.get("content", [])
    header_texts = []
    for cell in header_cells:
        if isinstance(cell, dict):
            text = _render_inline(cell.get("content", []))
            header_texts.append(text)
    
    # Render separator row
    separator = "| " + " | ".join(["---"] * len(header_texts)) + " |"
    
    # Render body rows
    body_texts = []
    for row in body_rows:
        cells = row.get("content", [])
        row_texts = []
        for cell in cells:
            if isinstance(cell, dict):
                text = _render_inline(cell.get("content", []))
                row_texts.append(text)
        if row_texts:
            body_texts.append("| " + " | ".join(row_texts) + " |")
    
    # Combine all parts
    table_parts = [
        "| " + " | ".join(header_texts) + " |",
        separator,
    ] + body_texts
    
    return "\n".join(table_parts)


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