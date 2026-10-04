from weeek_mcp.session.prosemirror import ImageRef, collect_images, to_markdown


def doc(*content):
    return {"type": "doc", "content": list(content)}


def para(*content):
    return {"type": "paragraph", "content": list(content)}


def text(value, *marks):
    node = {"type": "text", "text": value}
    if marks:
        node["marks"] = [{"type": m} for m in marks]
    return node


def test_paragraph_and_inline_marks():
    body = doc(para(text("plain "), text("bold", "bold"), text(" and "), text("code", "code")))

    assert to_markdown(body) == "plain **bold** and `code`"


def test_link_mark_uses_href_or_link_attr():
    node = {"type": "text", "text": "docs", "marks": [{"type": "link", "attrs": {"link": "https://x"}}]}

    assert to_markdown(doc(para(node))) == "[docs](https://x)"


def test_code_block_after_a_paragraph_survives():
    """The exact failure of the other open-source converter.

    Its walker only emitted text for paragraphs and headings, so a comment made of
    a paragraph plus a code block silently lost the code entirely.
    """
    body = doc(
        para(text("here is the fix")),
        {"type": "code", "attrs": {"language": "python"}, "content": [text("print(1)")]},
    )

    assert to_markdown(body) == "here is the fix\n\n```python\nprint(1)\n```"


def test_soft_break_is_line_break_not_hardbreak():
    """Weeek names the soft break 'line-break'; converters expecting TipTap's
    'hardBreak' drop it and silently glue two lines together."""
    body = doc(para(text("first"), {"type": "line-break"}, text("second")))

    assert to_markdown(body) == "first  \nsecond"


def test_flat_sibling_list_nodes_form_one_list():
    """Weeek emits sibling `list` nodes with a `kind` attr rather than a wrapper."""
    body = doc(
        {"type": "list", "attrs": {"kind": "bullet"}, "content": [para(text("one"))]},
        {"type": "list", "attrs": {"kind": "bullet"}, "content": [para(text("two"))]},
    )

    assert to_markdown(body) == "- one\n- two"


def test_nested_and_checkbox_lists():
    body = doc(
        {
            "type": "list",
            "attrs": {"kind": "check", "checked": True},
            "content": [
                para(text("done")),
                {"type": "list", "attrs": {"kind": "number"}, "content": [para(text("sub"))]},
            ],
        }
    )

    assert to_markdown(body) == "- [x] done\n  1. sub"


def test_quote_and_horizontal_rule():
    body = doc(
        {"type": "quote", "content": [para(text("cited"))]},
        {"type": "horizontal-line"},
    )

    assert to_markdown(body) == "> cited\n\n---"


def test_table_renders_with_a_header_separator():
    def cell(value):
        return {"type": "table_cell", "content": [para(text(value))]}

    body = doc(
        {
            "type": "table",
            "content": [
                {
                    "type": "table_body",
                    "content": [
                        {"type": "table_row", "content": [cell("a"), cell("b")]},
                        {"type": "table_row", "content": [cell("1"), cell("2")]},
                    ],
                }
            ],
        }
    )

    assert to_markdown(body) == "| a | b |\n| --- | --- |\n| 1 | 2 |"


def test_unknown_block_keeps_its_text():
    body = doc({"type": "something-new", "content": [para(text("still here"))]})

    assert to_markdown(body) == "still here"


def test_collect_images_finds_nested_nodes():
    image = {
        "type": "image",
        "attrs": {
            "id": "u1",
            "link": "https://api.weeek.net/ws/424242/files/abc",
            "name": "screen.png",
            "size": 4096,
        },
    }
    body = doc(para(text("see:")), {"type": "quote", "content": [para(image)]})

    assert collect_images(body) == [
        ImageRef("https://api.weeek.net/ws/424242/files/abc", "screen.png", 4096)
    ]


def test_images_can_be_rewritten_to_local_paths():
    image = {"type": "image", "attrs": {"link": "https://api.weeek.net/x", "name": "shot.png"}}
    body = doc(para(image))

    rendered = to_markdown(body, image_text=lambda ref: f"[{ref.name} -> /tmp/shot.png]")

    assert rendered == "[shot.png -> /tmp/shot.png]"


def test_empty_and_malformed_input_is_survivable():
    assert to_markdown(None) == ""
    assert to_markdown({}) == ""
    assert to_markdown({"type": "doc", "content": [None, "junk"]}) == ""
