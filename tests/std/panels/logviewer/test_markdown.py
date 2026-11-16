"""std/panels/logviewer/markdown.py: markdown as rows of coloured text for a width."""

from llvim.std.panels.logviewer import markdown
from llvim.std.panels.logviewer.ansi import strip, width


def plain(text, cols=40):
    return [strip(r).rstrip() for r in markdown.render(text, cols)]


def test_a_paragraph_is_wrapped_at_words_and_its_lines_are_one_paragraph():
    rows = plain("one two three\nfour five six seven eight nine", 20)
    assert rows == ["one two three four", "five six seven eight", "nine"]


def test_a_word_longer_than_the_row_is_broken_and_wide_characters_count_two_cells():
    assert plain("x" * 25, 10) == ["x" * 10, "x" * 10, "x" * 5]
    assert all(width(r) <= 10 for r in markdown.render("中文字符很长很长很长", 10))


def test_inline_styles_show_their_text_and_leave_what_is_not_closed_as_written():
    rows = markdown.render("**bold** *it* ~~gone~~ `code` snake_case 2 * 3 **open", 80)
    assert strip(rows[0]) == "bold it gone code snake_case 2 * 3 **open"
    assert "\x1b[1m" in rows[0] and "\x1b[3m" in rows[0] and "\x1b[9m" in rows[0] and "\x1b[48;5;236m" in rows[0]


def test_a_link_shows_its_text_and_where_it_goes_and_a_bare_url_is_kept():
    assert plain("[docs](http://a.io/x) and http://b.io.") == ["docs (http://a.io/x) and http://b.io."]


def test_headings_rules_and_quotes():
    assert plain("# Title\n\ntext\n\n---\n\n> a quote", 12) == ["Title", "", "text", "", "─" * 12, "", "▎ a quote"]


def test_lists_nest_wrap_under_their_marker_and_tasks_get_boxes():
    rows = plain("- one that is long enough to wrap\n  - inner\n1. first\n2. second\n- [x] done\n- [ ] todo", 20)
    assert rows == ["• one that is long", "  enough to wrap", "  • inner", "1. first", "2. second", "☑ done", "☐ todo"]


def test_a_fenced_block_is_kept_as_written_on_a_ground_the_width_of_the_screen_and_an_unclosed_one_runs_on():
    done = markdown.render("```py\nx = 1\n    y\n```\nafter", 20)
    assert [strip(r).rstrip() for r in done] == [" py", " x = 1", "     y", "", "after"] and all(width(r) == 20 for r in done[:3])
    assert plain("```\nstill coming", 20) == [" still coming"]


def test_a_table_has_borders_aligned_columns_and_narrows_to_the_width():
    rows = plain("| a | b |\n|---|--:|\n| 1 | 22 |", 40)
    assert rows == ["┌───┬────┐", "│ a │  b │", "├───┼────┤", "│ 1 │ 22 │", "└───┴────┘"]
    narrow = plain("| name | note |\n|---|---|\n| x | a long note that must wrap inside its cell |", 24)
    assert all(width(r) <= 24 for r in narrow) and len(narrow) > 5


def test_what_is_still_arriving_never_fails_and_never_overflows():
    text = "# T\n\n- a **b\n\n| x | y |\n|--|--\n| 1 |\n\n```\ncode"
    for n in range(len(text) + 1):
        assert all(width(r) <= 16 for r in markdown.render(text[:n], 16)), text[:n]
