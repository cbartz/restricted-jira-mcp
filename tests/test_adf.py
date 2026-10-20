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
            "- a\n- b\n\n  - b1"
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
        expected = "```python\nprint('hello')\n\n```"
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
        expected = "```\nplain text\n\n```"
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

    def test_renders_list_item_with_multiple_paragraphs(self):
        # Each paragraph in a list item becomes its own indented line, so a
        # read→update round trip keeps them as separate paragraphs.
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
                                {"type": "paragraph", "content": [{"type": "text", "text": "first"}]},
                                {"type": "paragraph", "content": [{"type": "text", "text": "second"}]},
                            ],
                        },
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        self.assertEqual(result, "- first\n\n  second")

    def test_renders_code_block_inside_list_item(self):
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
                                {"type": "paragraph", "content": [{"type": "text", "text": "item with code"}]},
                                {"type": "codeBlock", "content": [{"type": "text", "text": "x = 1"}]},
                            ],
                        },
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        self.assertEqual(result, "- item with code\n\n  ```\n  x = 1\n  ```")

    def test_renders_nested_list_under_wide_ordered_marker(self):
        # Continuation and nested lines indent by the marker's width, so a
        # "10. " item nests its children deeper than a "1. " item would.
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "orderedList",
                    "attrs": {"order": 10},
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "first"}]},
                                {
                                    "type": "bulletList",
                                    "content": [
                                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "nested"}]}]},
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        self.assertEqual(result, "10. first\n\n    - nested")

    def test_renders_headerless_table_with_all_rows(self):
        # A table without a header row keeps every row: the first row serves
        # as the markdown header, because pipe tables require one.
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
                                {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "a"}]}]},
                                {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "b"}]}]},
                            ],
                        },
                        {
                            "type": "tableRow",
                            "content": [
                                {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "c"}]}]},
                                {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "d"}]}]},
                            ],
                        },
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        self.assertEqual(result, "| a | b |\n| --- | --- |\n| c | d |")

    def test_renders_table_with_multiple_header_rows(self):
        # Rows marked as headers beyond the first are still rendered, as body
        # rows, so no cell text is dropped.
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
                                {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "r1"}]}]},
                            ],
                        },
                        {
                            "type": "tableRow",
                            "content": [
                                {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "r2"}]}]},
                            ],
                        },
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        self.assertEqual(result, "| r1 |\n| --- |\n| r2 |")

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
        self.assertEqual(result, "note\n\n@user")

    def test_unknown_container_keeps_block_order_and_separation(self):
        # A panel (unknown block container) between two paragraphs must render its
        # child blocks structurally, in document order, joined like sibling blocks.
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Intro"}]},
                {
                    "type": "panel",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "panel-first"}]},
                        {"type": "paragraph", "content": [{"type": "text", "text": "panel-second"}]},
                        {
                            "type": "bulletList",
                            "content": [
                                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "step one"}]}]},
                                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "step two"}]}]},
                            ],
                        },
                    ],
                },
                {"type": "paragraph", "content": [{"type": "text", "text": "Outro"}]},
            ],
        }
        result = adf_to_text(doc)
        expected = "Intro\n\npanel-first\n\npanel-second\n\n- step one\n- step two\n\nOutro"
        self.assertEqual(result, expected)

    def test_unknown_container_nested_in_unknown_container_stays_structural(self):
        # An expand inside a panel must also render block-aware: nested unknown
        # containers may not fall back to jamming their paragraphs together.
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Intro"}]},
                {
                    "type": "panel",
                    "content": [
                        {
                            "type": "expand",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "e1"}]},
                                {"type": "paragraph", "content": [{"type": "text", "text": "e2"}]},
                            ],
                        },
                    ],
                },
                {"type": "paragraph", "content": [{"type": "text", "text": "Outro"}]},
            ],
        }
        result = adf_to_text(doc)
        expected = "Intro\n\ne1\n\ne2\n\nOutro"
        self.assertEqual(result, expected)

    def test_renders_multi_paragraph_blockquote_with_prefix_on_every_line(self):
        # Each line of a blockquote keeps the "> " prefix; blank separators read ">".
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "blockquote",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "first"}]},
                        {"type": "paragraph", "content": [{"type": "text", "text": "second"}]},
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        expected = "> first\n>\n> second"
        self.assertEqual(result, expected)

    def test_renders_table_cell_with_multiple_paragraphs_space_joined(self):
        # A cell holding two paragraphs must not jam their texts together.
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
                                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Header"}]}],
                                },
                            ],
                        },
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableCell",
                                    "content": [
                                        {"type": "paragraph", "content": [{"type": "text", "text": "a"}]},
                                        {"type": "paragraph", "content": [{"type": "text", "text": "b"}]},
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        expected = "| Header |\n| --- |\n| a b |"
        self.assertEqual(result, expected)

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
        # Continuation and nested lines indent by their marker's width: the
        # outer "- " adds two spaces, the inner "2. " adds three.
        expected = "- top level\n\n  1. nested 1\n  2. nested 2\n\n     - deep nested"
        self.assertEqual(result, expected)


    def test_escapes_markdown_metacharacters_in_plain_text(self):
        # Literal ADF text must survive a read→update round trip: characters
        # that markdown would treat as structure get backslash-escaped.
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "*literal*"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "# not a heading"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "- not a list"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "1. not numbered"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "a | b"}]},
            ],
        }
        result = adf_to_text(doc)
        self.assertEqual(
            result,
            "\\*literal\\*\n\n\\# not a heading\n\n\\- not a list\n\n1\\. not numbered\n\na \\| b",
        )

    def test_leaves_intraword_underscores_readable(self):
        # CommonMark leaves intraword underscores literal, so snake_case need
        # no escaping; a boundary underscore does.
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "snake_case and _emphasized_"}]},
            ],
        }
        result = adf_to_text(doc)
        self.assertEqual(result, "snake_case and \\_emphasized\\_")

    def test_escapes_after_hard_break(self):
        # A line after a hard break starts a new markdown line, so its leading
        # "-" would become a list item on write-back.
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "first"},
                        {"type": "hardBreak"},
                        {"type": "text", "text": "- second"},
                    ],
                },
            ],
        }
        result = adf_to_text(doc)
        self.assertEqual(result, "first\n\\- second")

    def test_code_mark_with_backticks_round_trips(self):
        # Inline code containing backticks needs a longer code span; its
        # content stays literal (backslash escapes do not exist inside spans).
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "run `cmd`", "marks": [{"type": "code"}]}]},
            ],
        }
        result = adf_to_text(doc)
        self.assertEqual(result, "`` run `cmd` ``")

    def test_round_trips_through_markdown_conversion(self):
        # The lossless contract: adf → markdown text → adf reproduces the
        # original document exactly for the supported structures.
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Plan"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Do it "},
                        {"type": "text", "text": "bold", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": ", see "},
                        {"type": "text", "text": "docs", "marks": [{"type": "link", "attrs": {"href": "https://x.y"}}]},
                        {"type": "text", "text": "*carefully*"},
                        {"type": "hardBreak"},
                        {"type": "text", "text": "- not a list"},
                    ],
                },
                {
                    "type": "bulletList",
                    "content": [
                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "step"}]}]},
                    ],
                },
                {"type": "blockquote", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "quoted"}]}]},
                {"type": "codeBlock", "attrs": {"language": "python"}, "content": [{"type": "text", "text": "if x:\n    run()"}]},
                {
                    "type": "table",
                    "content": [
                        {
                            "type": "tableRow",
                            "content": [
                                {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "H"}]}]},
                            ],
                        },
                        {
                            "type": "tableRow",
                            "content": [
                                {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "a | b"}]}]},
                            ],
                        },
                    ],
                },
            ],
        }
        self.assertEqual(markdown_to_adf(adf_to_text(doc)), doc)


    def test_code_block_content_stays_literal(self):
        # Fenced markdown keeps code literal: punctuation inside a code block
        # must not be backslash-escaped, or a read→update round trip corrupts it.
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "codeBlock", "content": [{"type": "text", "text": "values[0] < 3 && f(*args)"}]},
            ],
        }
        text = adf_to_text(doc)
        self.assertEqual(text, "```\nvalues[0] < 3 && f(*args)\n```")
        self.assertEqual(markdown_to_adf(text), doc)

    def test_code_block_round_trips_trailing_newline(self):
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "codeBlock", "content": [{"type": "text", "text": "x = 1\n"}]},
            ],
        }
        text = adf_to_text(doc)
        # The blank line keeps the trailing newline: the write path strips
        # exactly one fence-content newline.
        self.assertEqual(text, "```\nx = 1\n\n```")
        self.assertEqual(markdown_to_adf(text), doc)

    def test_code_block_with_embedded_backticks_round_trips(self):
        # A fence must outlive the longest backtick run in the content, or the
        # content itself would close it early.
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "codeBlock", "content": [{"type": "text", "text": "has ```` run and `tick`"}]},
            ],
        }
        text = adf_to_text(doc)
        self.assertEqual(text, "`````\nhas ```` run and `tick`\n`````")
        self.assertEqual(markdown_to_adf(text), doc)


    def test_list_item_paragraphs_round_trip(self):
        # Sibling blocks inside a list item need a blank separator; without it
        # CommonMark reads the continuation as the same paragraph (lazy
        # continuation) and a write-back turns the boundary into a hard break.
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
                                {"type": "paragraph", "content": [{"type": "text", "text": "first"}]},
                                {"type": "paragraph", "content": [{"type": "text", "text": "second"}]},
                            ],
                        },
                    ],
                },
            ],
        }
        text = adf_to_text(doc)
        self.assertEqual(text, "- first\n\n  second")
        self.assertEqual(markdown_to_adf(text), doc)

    def test_nested_list_round_trips(self):
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
                                {"type": "paragraph", "content": [{"type": "text", "text": "top"}]},
                                {
                                    "type": "orderedList",
                                    "attrs": {"order": 1},
                                    "content": [
                                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "nested"}]}]},
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        }
        text = adf_to_text(doc)
        self.assertEqual(text, "- top\n\n  1. nested")
        self.assertEqual(markdown_to_adf(text), doc)

    def test_renders_rule_as_horizontal_rule(self):
        # `---` converts to an ADF rule on write; the read side must render it
        # back, or a created rule silently disappears on the next update.
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "above"}]},
                {"type": "rule"},
                {"type": "paragraph", "content": [{"type": "text", "text": "below"}]},
            ],
        }
        text = adf_to_text(doc)
        self.assertEqual(text, "above\n\n---\n\nbelow")
        self.assertEqual(markdown_to_adf(text), doc)

    def test_renders_rule_inside_blockquote(self):
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "blockquote",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "quoted"}]},
                        {"type": "rule"},
                    ],
                },
            ],
        }
        text = adf_to_text(doc)
        self.assertEqual(text, "> quoted\n>\n> ---")
        self.assertEqual(markdown_to_adf(text), doc)


    def test_flattens_cell_line_breaks_to_spaces(self):
        # Pipe-table rows cannot contain newlines, so a hard break inside a
        # cell flattens to a space — the row itself must stay intact.
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
                                {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "H"}]}]},
                            ],
                        },
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableCell",
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": [
                                                {"type": "text", "text": "a"},
                                                {"type": "hardBreak"},
                                                {"type": "text", "text": "b"},
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
        text = adf_to_text(doc)
        self.assertEqual(text, "| H |\n| --- |\n| a b |")
        reparsed = markdown_to_adf(text)
        cell = reparsed["content"][0]["content"][1]["content"][0]
        self.assertEqual(cell["type"], "tableCell")
        self.assertEqual(cell["content"][0]["content"][0]["text"], "a b")

    def test_escapes_indented_list_markers(self):
        # CommonMark recognizes list markers after up to three leading spaces,
        # so indentation alone does not make a "- " literal.
        doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "  - not a list"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": " 1. not numbered"}]},
            ],
        }
        text = adf_to_text(doc)
        self.assertEqual(text, "  \\- not a list\n\n 1\\. not numbered")
        self.assertEqual(markdown_to_adf(text), doc)


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

    # An empty fenced code block yields a codeBlock with an empty content list,
    # because ADF rejects empty text nodes.
    def test_empty_fence_yields_code_block_without_text_node(self):
        adf = markdown_to_adf("```\n```")
        code_block = adf["content"][0]
        self.assertEqual(code_block["type"], "codeBlock")
        self.assertEqual(code_block["content"], [])

    # An image with empty alt text degrades to a link labelled with the URL,
    # because an empty text node would be invalid ADF.
    def test_image_with_empty_alt_uses_url_as_label(self):
        adf = markdown_to_adf("![](https://img/x.png)")
        paragraph = adf["content"][0]
        self.assertEqual(len(paragraph["content"]), 1)
        text_node = paragraph["content"][0]
        self.assertEqual(text_node["text"], "https://img/x.png")
        self.assertEqual(text_node["marks"], [{"type": "link", "attrs": {"href": "https://img/x.png"}}])

    # A link with empty text keeps its target as the link's text.
    def test_link_with_empty_text_uses_url_as_label(self):
        adf = markdown_to_adf("see [](https://x.y) now")
        paragraph = adf["content"][0]
        texts = [node["text"] for node in paragraph["content"]]
        self.assertEqual(texts, ["see ", "https://x.y", " now"])
        self.assertEqual(
            paragraph["content"][1]["marks"],
            [{"type": "link", "attrs": {"href": "https://x.y"}}],
        )