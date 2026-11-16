"""std/panels/input/editor.py: the line being typed."""

from llvim.std.panels.input.editor import Editor, handle, load_history, save_history


def typed(text, history=None):
    e = Editor(history)
    e.insert(text)
    return e


def test_typing_inserts_at_the_cursor_and_the_cursor_moves_with_it():
    e = typed("hello")
    e.home()
    e.right()
    e.insert("X")
    assert (e.text, e.cursor) == ("hXello", 2)


def test_deleting_by_character_word_and_to_either_end():
    e = typed("one two three")
    e.kill_word()
    assert e.text == "one two "
    e.home()
    e.delete()
    assert e.text == "ne two "
    e.end()
    e.backspace()
    e.kill_to_start()
    assert (e.text, e.cursor) == ("", 0)
    e = typed("abcd")
    e.left()
    e.left()
    e.kill_to_end()
    assert e.text == "ab"


def test_words_are_stepped_over_by_the_cursor():
    e = typed("one two")
    e.word_left()
    assert e.cursor == 4
    e.word_left()
    assert e.cursor == 0
    e.word_right()
    assert e.cursor == 3


def test_history_goes_back_and_forward_and_keeps_what_was_being_typed():
    e = typed("draft", ["a", "b"])
    e.history_prev()
    assert e.text == "b"
    e.history_prev()
    assert e.text == "a"
    e.history_next()
    e.history_next()
    assert e.text == "draft"


def test_submit_returns_the_line_empties_the_editor_and_remembers_it_once():
    e = typed("hi")
    assert e.submit() == "hi" and e.text == ""
    e.insert("hi")
    e.submit()
    assert e.history == ["hi"]


def test_keys_that_edit_are_applied_and_others_are_not():
    e = Editor()
    assert handle(e, b"a") and handle(e, "é".encode()) and handle(e, b"\x1b[D") and handle(e, b"\x1b[27;2;13~")
    assert e.text == "a\né" or e.text == "aé\n" or "\n" in e.text
    assert not handle(e, b"\x1b[5~") and not handle(e, b"\x00")


def test_history_is_saved_as_json_lines_and_plain_lines_are_still_read(tmp_path):
    path = tmp_path / "h"
    save_history(path, ["one\ntwo", "three"])
    assert load_history(path) == ["one\ntwo", "three"]
    path.write_text("plain\n\n")
    assert load_history(path) == ["plain"]
    assert load_history(tmp_path / "missing") == []


def test_shift_enter_inserts_a_line_break_and_alt_enter_does_not():
    for raw in (b"\x1b[13;2u", b"\x1b[27;2;13~"):
        e = typed("ab")
        e.left()
        assert handle(e, raw) and e.text == "a\nb"
    e = typed("ab")
    assert not handle(e, b"\x1b\r") and not handle(e, b"\x1b\n") and e.text == "ab"
