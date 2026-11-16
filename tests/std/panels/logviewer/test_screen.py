"""std/panels/logviewer/screen.py: input parsed into keys and mouse events, and drawing only the rows that changed."""

import base64
import io

from llvim.std.panels.logviewer.screen import Screen


def screen():
    out = io.StringIO()
    return Screen(fd_in=0, out=out), out


def test_only_the_rows_that_changed_are_drawn():
    s, out = screen()
    s.draw(["one", "two", "three"])
    assert all(w in out.getvalue() for w in ("one", "two", "three"))
    out.truncate(0), out.seek(0)
    s.draw(["one", "TWO", "three"])
    assert "TWO" in out.getvalue() and "one" not in out.getvalue() and "three" not in out.getvalue()
    out.truncate(0), out.seek(0)
    s.draw(["one", "TWO", "three"])
    assert out.getvalue() == ""  # nothing changed: nothing written


def test_copy_sends_the_text_as_an_osc_52_clipboard_escape():
    s, out = screen()
    s.copy("héllo\nworld")
    sent = out.getvalue()
    assert sent.startswith("\x1b]52;c;") and sent.endswith("\x07")
    assert base64.b64decode(sent[7:-1]).decode() == "héllo\nworld"
