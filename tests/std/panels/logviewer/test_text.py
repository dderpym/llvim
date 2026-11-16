"""std/panels/logviewer/text.py: how a message looks as plain terminal text."""

from llvim.std.panels.logviewer import text


def test_control_characters_are_removed_but_newlines_and_tabs_stay():
    assert text.clean("a\x1b]52;c;ZXZpbA==\x07b\x1b[2J\x9bc\nd\te\r") == "a]52;c;ZXZpbA==b[2Jc\nd\te"


def test_a_streaming_message_is_the_start_of_how_it_looks_once_finished():
    for tags in (["assistant"], ["thinking"]):
        finished = text.thinking(tags, "hello") if tags == ["thinking"] else text.default(tags, "hello")
        assert finished.startswith(text.partial(tags, "hello")), tags


def test_tags_that_are_not_text_show_as_json():
    assert text.tags_text(["call", {"n": 1}]) == 'call {"n": 1}'
