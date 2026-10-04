import pytest

from weeek_mcp.url import TaskRef, TaskRefError, parse_task_ref

# Verbatim from the address bar, the shape that actually gets pasted.
REAL = (
    "https://app.weeek.net/ws/424242/project/1/board/1"
    "?modals=m_task&m_task_workspace-id=424242&m_task_id=154"
)


def test_board_url_with_open_task_modal():
    assert parse_task_ref(REAL) == TaskRef(task_id=154, workspace_id=424242)


def test_board_ids_in_path_are_not_mistaken_for_the_task():
    # /project/1/board/1 sits in the path; a looser pattern would return 1.
    assert parse_task_ref(REAL).task_id == 154


def test_canonical_permalink():
    assert parse_task_ref("https://app.weeek.net/ws/424242/task/154") == TaskRef(154, 424242)


def test_permalink_with_web_view_tail():
    ref = parse_task_ref("https://app.weeek.net/ws/424242/task/154/description/web-view")
    assert ref == TaskRef(154, 424242)


@pytest.mark.parametrize("raw", ["154", "#154", "  154  "])
def test_bare_id_has_no_workspace(raw):
    assert parse_task_ref(raw) == TaskRef(task_id=154, workspace_id=None)


def test_modal_workspace_wins_over_the_path():
    # A task opened from another workspace while sitting on this board.
    ref = parse_task_ref(
        "https://app.weeek.net/ws/111/project/1/board/1"
        "?modals=m_task&m_task_workspace-id=999&m_task_id=154"
    )
    assert ref == TaskRef(task_id=154, workspace_id=999)


def test_workspace_falls_back_to_the_path():
    ref = parse_task_ref("https://app.weeek.net/ws/424242/project/1/board/1?m_task_id=154")
    assert ref == TaskRef(task_id=154, workspace_id=424242)


def test_trailing_slash_fragment_and_extra_query_are_tolerated():
    ref = parse_task_ref(f"{REAL}&utm_source=slack#comment-7")
    assert ref == TaskRef(154, 424242)


def test_scheme_may_be_missing():
    assert parse_task_ref("app.weeek.net/ws/424242/task/154") == TaskRef(154, 424242)


def test_board_url_without_an_open_task_is_rejected():
    with pytest.raises(TaskRefError, match="does not point at a task"):
        parse_task_ref("https://app.weeek.net/ws/424242/project/1/board/1")


def test_foreign_host_is_rejected():
    with pytest.raises(TaskRefError, match="not a Weeek link"):
        parse_task_ref("https://app.weeek.net.evil.com/ws/1/task/2")


def test_empty_input_is_rejected():
    with pytest.raises(TaskRefError, match="Empty input"):
        parse_task_ref("   ")


def test_non_numeric_modal_id_is_ignored_and_reported():
    with pytest.raises(TaskRefError, match="does not point at a task"):
        parse_task_ref("https://app.weeek.net/ws/424242/project/1?m_task_id=abc")
