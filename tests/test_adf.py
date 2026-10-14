import unittest
from typing import Any

from restricted_jira_mcp.adf import adf_to_text


class TestAdfToText(unittest.TestCase):
    def test_renders_paragraph_marks_and_lists(self):
        doc = {
            "type": "doc", 
            "version": 1, 
            "content": [
                {
                    "type": "paragraph", 
                    "content": [
                        {"type": "text", "text": "Line one"},
                        {"type": "hardBreak"},
                        {"type": "text", "text": "line two"},
                    ],
                },
                {
                    "type": "paragraph", 
                    "content": [
                        {"type": "text", "text": "bold", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": " and "},
                        {"type": "text", "text": "link", "marks": [{"type": "link", "attrs": {"href": "https://x.y"}}]},
                    ],
                },
                {
                    "type": "bulletList", 
                    "content": [
                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "a"}]}]},
                        {"type": "listItem", "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "b"}]},
                            {"type": "bulletList", "content": [
                                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "b1"}]}]},
                            ]},
                        ]},
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        expected = (
            "Line one\nline two\n\n"
            "**bold** and [link](https://x.y)\n\n"
            "- a\n- b\n  - b1"
        )
        self.assertEqual(result, expected)

    def test_renders_heading_levels(self):
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "Heading 1"}]},
                {"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "Heading 3"}]},
            ],
        }
        result = adf_to_text(doc)
        expected = "# Heading 1\n\n### Heading 3"
        self.assertEqual(result, expected)

    def test_renders_ordered_list_with_order_attr(self):
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "orderedList",
                    "attrs": {"order": 2},
                    "content": [
                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "item 2"}]}]},
                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "item 3"}]}]},
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        expected = "2. item 2\n3. item 3"
        self.assertEqual(result, expected)

    def test_renders_code_block_with_language(self):
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "codeBlock",
                    "attrs": {"language": "python"},
                    "content": [{"type": "text", "text": "print('hello')\n"}],
                },
            ],
        }
        result = adf_to_text(doc)
        expected = "```python\nprint('hello')\n```"
        self.assertEqual(result, expected)

    def test_renders_code_block_without_language(self):
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "codeBlock",
                    "content": [{"type": "text", "text": "plain text\n"}],
                },
            ],
        }
        result = adf_to_text(doc)
        expected = "```\nplain text\n```"
        self.assertEqual(result, expected)

    def test_renders_blockquote(self):
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "blockquote",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "quoted text"}]},
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        expected = "> quoted text"
        self.assertEqual(result, expected)

    def test_renders_table(self):
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "table",
                    "content": [
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableHeader",
                                    "content": [
                                        {"type": "paragraph", "content": [{"type": "text", "text": "Header 1"}]},
                                    ],
                                },
                                {
                                    "type": "tableHeader",
                                    "content": [
                                        {"type": "paragraph", "content": [{"type": "text", "text": "Header 2"}]},
                                    ],
                                },
                            ],
                        },
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableCell",
                                    "content": [
                                        {"type": "paragraph", "content": [{"type": "text", "text": "Cell 1"}]},
                                    ],
                                },
                                {
                                    "type": "tableCell",
                                    "content": [
                                        {"type": "paragraph", "content": [{"type": "text", "text": "Cell 2"}]},
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        expected = "| Header 1 | Header 2 |\n| --- | --- |\n| Cell 1 | Cell 2 |"
        self.assertEqual(result, expected)

    def test_returns_none_for_falsy_input(self):
        self.assertIsNone(adf_to_text(None))
        self.assertIsNone(adf_to_text(""))

    def test_bare_string_passthrough(self):
        result = adf_to_text("hello world")
        self.assertEqual(result, "hello world")

    def test_long_content_returns_full_length(self):
        long_text = "a" * 1000
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": long_text}]}
            ],
        }
        result = adf_to_text(doc)
        self.assertEqual(result, long_text)

    def test_unknown_nodes_render_descendant_text_without_raising(self):
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "panel",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "note"}]
                        }
                    ]
                },
                {
                    "type": "mention",
                    "attrs": {"id": "123"},
                    "content": [{"type": "text", "text": "@user"}]
                }
            ],
        }
        result = adf_to_text(doc)
        self.assertEqual(result, "note @user")

    def test_paragraph_with_em_and_code_marks(self):
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "italic", "marks": [{"type": "em"}]},
                        {"type": "text", "text": " and "},
                        {"type": "text", "text": "code", "marks": [{"type": "code"}]},
                        {"type": "text", "text": " text"},
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        expected = "*italic* and `code` text"
        self.assertEqual(result, expected)

    def test_paragraph_with_strike_mark(self):
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "deleted", "marks": [{"type": "strike"}]},
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        expected = "~~deleted~~"
        self.assertEqual(result, expected)

    def test_nested_lists_with_indentation(self):
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "top level"}]},
                                {
                                    "type": "orderedList",
                                    "content": [
                                        {
                                            "type": "listItem",
                                            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "nested 1"}]}],
                                        },
                                        {
                                            "type": "listItem",
                                            "content": [
                                                {"type": "paragraph", "content": [{"type": "text", "text": "nested 2"}]},
                                                {
                                                    "type": "bulletList",
                                                    "content": [
                                                        {
                                                            "type": "listItem",
                                                            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "deep nested"}]}],
                                                        },
                                                    ],
                                                },
                                            ],
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        expected = "- top level\n  1. nested 1\n  2. nested 2\n    - deep nested"
        self.assertEqual(result, expected)