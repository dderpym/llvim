"""std/panels/input/view.py: how the bar looks."""

from llvim.std.panels.input import view
from llvim.std.panels.input.complete import Suggestion
from llvim.std.panels.input.editor import Editor
from llvim.std.panels.input.menu import Menu
from llvim.std.panels.logviewer.ansi import strip


def typed(text):
    e = Editor()
    e.insert(text)
    return e


def shown(rows):
    return [strip(r).rstrip() for r in rows]


def test_the_prompt_is_at_the_bottom_with_the_cursor_after_the_text():
    rows, cursor = view.render(typed("hi"), Menu(), "", 20, 3)
    assert shown(rows) == ["› hi", "", ""] and cursor == (4, 0)


def test_a_long_line_wraps_and_a_line_break_is_drawn_as_a_mark():
    rows, _ = view.render(typed("a\nb"), Menu(), "", 20, 3)
    assert shown(rows)[:2] == ["› a", "  b"]
    rows, cursor = view.render(typed("x" * 25), Menu(), "", 12, 3)
    assert shown(rows)[:3] == ["› " + "x" * 10, "  " + "x" * 10, "  " + "x" * 5] and cursor[1] == 2


def test_the_menu_opens_above_the_prompt_and_marks_the_chosen_suggestion():
    m = Menu()
    m.refresh([Suggestion("/quit", 0, 1, "end"), Suggestion("/help", 0, 1, "list")], "/")
    m.move(1)
    rows, cursor = view.render(typed("/"), m, "", 30, 5)
    assert shown(rows)[:3] == ["▸ /quit  end", "  /help  list", "› /"]
    assert shown(rows)[-3] == "› /" and cursor == (3, 2) and view.wanted(m) == 2


def test_the_prompt_takes_the_rows_its_text_needs_and_the_cursor_follows_it():
    e = typed("1\n2\n3\n4\n5")
    rows, cursor = view.render(e, Menu(), "", 20, 8)
    assert shown(rows) == ["", "", "", "› 1", "  2", "  3", "  4", "  5"] and cursor == (3, 7)
    assert view.prompt_height(e, 20) == 5
    rows, cursor = view.render(e, Menu(), "", 20, 3)  # no room: it scrolls to the cursor
    assert shown(rows) == ["  3", "  4", "  5"] and cursor == (3, 2)


def test_a_notice_shows_under_the_text_and_a_shut_menu_wants_no_rows():
    rows, _ = view.render(typed("x"), Menu(), "unknown command", 30, 3)
    assert shown(rows)[1] == "unknown command" and view.wanted(Menu()) == 0
