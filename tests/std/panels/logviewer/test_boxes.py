"""std/panels/logviewer/boxes.py: the built-in boxes. Each is a function of its messages."""

from llvim.std.panels.logviewer import boxes
from llvim.std.panels.logviewer.ansi import strip
from llvim.std.panels.logviewer.box import chain, claimed


def test_the_fallback_shows_the_tags_then_the_content_of_any_message(entry, stub_host):
    b = boxes.Fallback(stub_host, [entry(["note"], "hi")])
    assert b.lines == ["\x1b[1;36mnote\x1b[0m", "hi", "", ""] and b.text() == "\x1b[1;36mnote\x1b[0m\nhi\n\n"


def test_the_fallback_leaves_a_streaming_message_open(entry, stub_host):
    assert boxes.Fallback(stub_host, [entry(["note"], "hal", streaming=True)]).lines == ["\x1b[1;36mnote\x1b[0m", "hal"]


def test_thinking_streams_in_full_with_its_markdown_all_in_grey(entry, stub_host):
    b = boxes.Thinking(stub_host, [entry(["thinking"], "one **two**\n\n`three` [x](http://a.b)", streaming=True)])
    rows = b.hooks.layout(40)
    assert [strip(r) for r in rows][0] == "thinking" and len(rows) == 4
    assert all(r.startswith("\x1b[38;5;245m") for r in rows[1:]) and "\x1b[38;5;75m" not in "".join(rows)
    assert "\x1b[1m" in rows[1]
    b.toggle()
    assert len(b.hooks.layout(40)) == 4  # a trace still arriving does not fold


def test_a_finished_thinking_folds_to_one_line_and_a_click_opens_and_folds_it(entry, stub_host):
    b = boxes.Thinking(stub_host, [entry(["thinking"], "one\n\ntwo three")])
    assert len(b.hooks.layout(40)) == 1 and "[thinking]" in b.hooks.layout(40)[0] and "3 words" in b.hooks.layout(40)[0]
    b.toggle()
    assert [strip(r) for r in b.hooks.layout(40)] == ["▾ [thinking]", "one", "", "two three"]
    b.toggle()
    assert len(b.hooks.layout(40)) == 1
    assert "one\n\ntwo three" in b.text()  # plain output and copying are not folded


def test_an_assistant_message_draws_its_markdown_at_the_width_and_prints_as_written(entry, stub_host):
    b = boxes.Markdown(stub_host, [entry(["assistant"], "**hi** there")])
    rows = b.hooks.layout(40)
    assert "hi there" in strip(rows[1]) and rows[0].startswith("\x1b[1;36m") and rows[-2:] == ["", ""]
    assert b.text() == "\x1b[1;36massistant\x1b[0m\n**hi** there\n\n" and not b.framed
    streaming = boxes.Markdown(stub_host, [entry(["assistant"], "par", streaming=True)])
    assert streaming.hooks.layout(40)[-1] != ""  # no blank rows under what is still arriving


def test_a_cue_shows_nothing(entry, stub_host):
    cue = entry(["cue", "generate"])
    i, _ = claimed(chain(), cue)
    box = chain()[i].make(stub_host, [cue])
    assert chain()[i].name == "hidden" and box.lines == [] and box.text() == ""
