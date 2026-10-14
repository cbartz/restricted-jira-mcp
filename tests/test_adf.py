import unittest
from typing import Any

from restricted_jira_mcp.adf import adf_to_text, as_adf, markdown_to_adf


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


class TestMarkdownToAdf(unittest.TestCase):
    # Pinned mapping: root → doc shell {"type": "doc", "version": 1, "content": [...]},
    # heading → heading with attrs.level taken from the h-tag, paragraph → paragraph,
    # and blank lines separating markdown blocks become separate ADF blocks.
    def test_converts_headings_and_paragraphs_split_on_blank_lines(self):
        result = markdown_to_adf("# Title\n\nBody paragraph.\n\n### Details\n")
        expected = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "Title"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Body paragraph."}]},
                {"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "Details"}]},
            ],
        }
        self.assertEqual(result, expected)

    # Pinned mapping: bullet_list → bulletList, list_item → listItem wrapping its
    # child blocks (each item's text becomes a paragraph).
    def test_converts_bullet_list(self):
        result = markdown_to_adf("- a\n- b\n")
        expected = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "a"}]}]},
                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "b"}]}]},
                    ],
                },
            ],
        }
        self.assertEqual(result, expected)

    # Pinned mapping: ordered_list → orderedList with attrs.order = the token's
    # start value (default 1); list_item → listItem wrapping child blocks.
    def test_converts_ordered_list_with_start_attr(self):
        result = markdown_to_adf("5. a\n6. b\n")
        expected = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "orderedList",
                    "attrs": {"order": 5},
                    "content": [
                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "a"}]}]},
                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "b"}]}]},
                    ],
                },
            ],
        }
        self.assertEqual(result, expected)
        default = markdown_to_adf("1. a\n2. b\n")
        self.assertEqual(default["content"][0]["attrs"], {"order": 1})

    # Pinned mapping: fence → codeBlock with attrs.language from the fence info
    # string and the code text minus its trailing newline.
    def test_converts_fenced_code_block_with_language(self):
        result = markdown_to_adf("```python\nprint('hi')\n```\n")
        expected = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "codeBlock",
                    "attrs": {"language": "python"},
                    "content": [{"type": "text", "text": "print('hi')"}],
                },
            ],
        }
        self.assertEqual(result, expected)

    # Pinned mapping: fence without an info string and indented code_block both
    # become codeBlock with the language attrs omitted entirely.
    def test_converts_code_block_without_language(self):
        result = markdown_to_adf("```\nplain text\n```\n")
        expected = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "codeBlock", "content": [{"type": "text", "text": "plain text"}]},
            ],
        }
        self.assertEqual(result, expected)
        indented = markdown_to_adf("    indented code\n")
        self.assertEqual(
            indented["content"],
            [{"type": "codeBlock", "content": [{"type": "text", "text": "indented code"}]}],
        )

    # Pinned mapping: em/strong/code_inline/s inline nodes become em/strong/code/
    # strike marks on text nodes.
    def test_converts_inline_marks(self):
        result = markdown_to_adf("*em* **strong** `code` ~~gone~~\n")
        expected = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "em", "marks": [{"type": "em"}]},
                        {"type": "text", "text": " "},
                        {"type": "text", "text": "strong", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": " "},
                        {"type": "text", "text": "code", "marks": [{"type": "code"}]},
                        {"type": "text", "text": " "},
                        {"type": "text", "text": "gone", "marks": [{"type": "strike"}]},
                    ],
                },
            ],
        }
        self.assertEqual(result, expected)

    # Pinned mapping: [text](url) → text node carrying a link mark with
    # attrs.href (plus attrs.title when the markdown link has a title).
    def test_converts_link_mark(self):
        result = markdown_to_adf("[Jira](https://x.y)\n")
        expected = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Jira", "marks": [{"type": "link", "attrs": {"href": "https://x.y"}}]}
                    ],
                },
            ],
        }
        self.assertEqual(result, expected)
        titled = markdown_to_adf('[a](x "T")\n')
        self.assertEqual(
            titled["content"][0]["content"],
            [{"type": "text", "text": "a", "marks": [{"type": "link", "attrs": {"href": "x", "title": "T"}}]}],
        )

    # Pinned mapping: hardbreak (two trailing spaces) AND softbreak (single
    # newline) both become hardBreak nodes — line breaks are preserved, not merged.
    def test_converts_hard_break_and_soft_break(self):
        result = markdown_to_adf("one  \ntwo\nthree\n")
        expected = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "one"},
                        {"type": "hardBreak"},
                        {"type": "text", "text": "two"},
                        {"type": "hardBreak"},
                        {"type": "text", "text": "three"},
                    ],
                },
            ],
        }
        self.assertEqual(result, expected)

    # Pinned mapping: table → table of tableRows; thead/tbody/tr wrappers are
    # flattened; th → tableHeader and td → tableCell, each holding its paragraphs.
    def test_converts_pipe_table(self):
        result = markdown_to_adf("| Name | Value |\n| --- | --- |\n| a | 1 |\n")
        expected = {
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
                                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Name"}]}],
                                },
                                {
                                    "type": "tableHeader",
                                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Value"}]}],
                                },
                            ],
                        },
                        {
                            "type": "tableRow",
                            "content": [
                                {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "a"}]}]},
                                {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "1"}]}]},
                            ],
                        },
                    ],
                },
            ],
        }
        self.assertEqual(result, expected)

    # Pinned mapping: blockquote → blockquote wrapping its child blocks.
    def test_converts_blockquote(self):
        result = markdown_to_adf("> quoted text\n")
        expected = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "blockquote",
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "quoted text"}]}],
                },
            ],
        }
        self.assertEqual(result, expected)

    # Pinned mapping: hr → rule node.
    def test_converts_horizontal_rule(self):
        result = markdown_to_adf("---\n")
        expected = {"type": "doc", "version": 1, "content": [{"type": "rule"}]}
        self.assertEqual(result, expected)

    # Pinned mapping: image → text node with the alt text plus a link mark to
    # src (ADF media needs upload; images degrade to links).
    def test_converts_image_to_linked_alt_text(self):
        result = markdown_to_adf("![alt](https://img/x.png)\n")
        expected = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "alt", "marks": [{"type": "link", "attrs": {"href": "https://img/x.png"}}]}
                    ],
                },
            ],
        }
        self.assertEqual(result, expected)

    # Marks accumulate down nested inline containers: emphasized text inside
    # bold text carries both the strong and em marks on one text node.
    def test_nested_emphasis_accumulates_marks(self):
        result = markdown_to_adf("**bold *deep***\n")
        expected = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "bold ", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": "deep", "marks": [{"type": "strong"}, {"type": "em"}]},
                    ],
                },
            ],
        }
        self.assertEqual(result, expected)


class TestAsAdf(unittest.TestCase):
    # as_adf passes a valid ADF doc (type "doc" with list content) through
    # unchanged.
    def test_passes_through_valid_adf_doc(self):
        doc = {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": []}]}
        self.assertIs(as_adf(doc), doc)

    # as_adf converts a markdown string via markdown_to_adf.
    def test_converts_markdown_string(self):
        self.assertEqual(as_adf("## Hi\n"), markdown_to_adf("## Hi\n"))

    # as_adf rejects anything that is neither a markdown string nor an ADF doc
    # (non-doc dicts, lists, ints) with a ValueError naming both accepted shapes.
    def test_rejects_non_markdown_non_doc_values(self):
        for value in ({"type": "paragraph"}, [], 42):
            with self.assertRaises(ValueError) as ctx:
                as_adf(value)
            self.assertIn("Markdown string or an ADF doc object", str(ctx.exception))

    # as_adf of an empty markdown string yields an empty ADF doc.
    def test_empty_string_returns_empty_doc(self):
        self.assertEqual(as_adf(""), {"type": "doc", "version": 1, "content": []})