"""std/tools/bash/tool.py: the bash tool: what the model is told of a command's run. The terminal is a stub; the real one is
tested in test_terminal.py."""

import asyncio
import re
from pathlib import Path

import pytest

from llvim.std.conversation import Entry
from llvim.std.tmux import TmuxError
from llvim.std.tools import Context, Registry
from llvim.std.tools.bash import TOOL, terminal
from llvim.std.tools.bash.terminal import Ran

REGISTRY = Registry([TOOL])
CALL = Entry(0, ["tool_call", "bash"], "{}", {"call_id": "c1"})


@pytest.fixture
def say(monkeypatch, tmp_path):
    """`say(ran, **arguments)`: the result the model gets when the terminal reports `ran`, and how the terminal was asked."""

    def run(ran, **arguments):
        asked = []

        async def stub(command, cwd, call_id, timeout, interactive):
            asked.append((command, call_id, timeout, interactive))
            return ran

        monkeypatch.setattr(terminal, "run", stub)
        result = asyncio.run(REGISTRY.run("bash", {"command": "ls", **arguments}, Context(tmp_path, CALL)))
        return result, asked

    return run


def test_the_command_goes_to_the_terminal_with_its_call_its_timeout_and_whether_it_is_interactive(say):
    out, asked = say(Ran("a.txt\n", 0), timeout=9, interactive=True)
    assert out.text == "a.txt\n" and asked == [("ls", "c1", 9.0, True)]
    assert say(Ran("", 0))[1] == [("ls", "c1", 120.0, False)]  # the defaults: two minutes, and nobody types


def test_how_the_command_ended_is_told_to_the_model(say):
    assert re.fullmatch(r"x\n\[exit code 2 after \d+\.\ds\]", say(Ran("x\n", 2))[0].text)
    assert (
        "[exit code 137 (SIGKILL) after" in say(Ran("", 137))[0].text
    )  # 128 + 9: what a shell says of a killed program
    assert say(Ran("", 0))[0].text == "(no output)"
    timed_out = say(Ran("so far\n", None, timed_out=True), timeout=5)[0]
    assert timed_out.error and timed_out.text == "so far\n[timed out after 5s and stopped]"
    cancelled = say(Ran("so far\n", None, cancelled=True))[0]
    assert cancelled.error and re.fullmatch(r"so far\n\[interrupted after \d+\.\ds\]", cancelled.text)


def test_what_the_command_wrote_reaches_the_model_as_it_was_written(say):
    written = "\n  a\tb  \r\nno newline"
    assert say(Ran(written, 0))[0].text == written


def test_output_within_the_limits_is_given_whole_and_a_form_feed_is_not_a_line(say):
    assert say(Ran("".join(f"{n}\n" for n in range(1, 2001)), 0))[0].text.splitlines()[-1] == "2000"
    assert say(Ran("a\fb\fc\n", 0))[0].text == "a\fb\fc\n"  # one line, not cut


def saved(text):
    """The path a too-large output was saved to, from the note the model got."""
    return Path(text.split("Sent to ")[1].splitlines()[0])


def test_too_many_lines_are_saved_to_a_file_and_the_model_gets_a_note_not_the_lines(say, tmp_path):
    out = say(Ran("".join(f"{n}\n" for n in range(1, 5001)), 0))[0].text
    path = saved(out)
    try:
        assert out.startswith("Output too large, please parse in chunks with grep and sed!")
        assert "5000 lines" in out and "\n2500\n" not in out and len(out) < 800
        assert path.name.startswith("llvim-out-") and path.read_text().splitlines()[-1] == "5000"
        assert path.stat().st_mode & 0o077 == 0  # the output may hold secrets: only the owner reads it
    finally:
        path.unlink()


def test_the_note_has_a_short_preview_of_the_start_and_end_and_never_the_middle(say):
    text = "START" + "m" * 20_000 + "\n" + "".join(f"{n}\n" for n in range(3000)) + "END"
    out = say(Ran(text, 0))[0].text
    saved(out).unlink()
    assert "Start:\nSTART" in out and out.endswith("2999\nEND") and "mmmmm" in out and "m" * 300 not in out
    assert len(out) < 800


def test_the_numbers_can_be_set_and_a_preview_of_zero_turns_it_off(say, monkeypatch):
    monkeypatch.setenv("LLVIM_BASH_MAX_LINES", "3")
    monkeypatch.setenv("LLVIM_BASH_PREVIEW_CHARS", "0")
    out = say(Ran("a\nb\nc\nd\n", 0))[0].text
    saved(out).unlink()
    assert "4 lines" in out and "Start:" not in out
    assert say(Ran("a\nb\nc\n", 0))[0].text == "a\nb\nc\n"  # three lines is not more than three
    monkeypatch.setenv("LLVIM_BASH_MAX_BYTES", "4")
    monkeypatch.delenv("LLVIM_BASH_MAX_LINES")
    out = say(Ran("abcdef", 0))[0].text
    saved(out).unlink()
    assert "6 B, 1 line, ran " in out
    monkeypatch.setenv("LLVIM_BASH_TIMEOUT", "7")
    assert say(Ran("", 0))[1] == [("ls", "c1", 7.0, False)]


def test_the_note_tells_which_lines_are_long_and_the_median_line(say, monkeypatch):
    lines = ["short"] * 3000
    for n in (5, 900, 2000):
        lines[n - 1] = "x" * 12_000
    out = say(Ran("\n".join(lines), 0))[0].text
    saved(out).unlink()
    assert "3 lines >= 10 KB (lines 5, 900, 2000); median line 5 B" in out
    monkeypatch.setenv("LLVIM_BASH_LONG_LINE_COUNT", "2")
    out = say(Ran("\n".join(lines), 0))[0].text
    saved(out).unlink()
    assert "(lines 5, 900, +1 more)" in out
    monkeypatch.setenv("LLVIM_BASH_LONG_LINE_BYTES", "0")
    out = say(Ran("\n".join(lines), 0))[0].text
    saved(out).unlink()
    assert "median line 5 B" in out and "lines >=" not in out


def test_one_long_line_is_not_called_lines(say):
    out = say(Ran("x" * 12_000 + "\n" + "ab\n" * 3000, 0))[0].text
    saved(out).unlink()
    assert "1 line >= 10 KB (line 1);" in out


def test_the_preview_is_whole_lines_and_a_line_too_long_for_it_is_cut_and_says_so(say):
    lines = [f"row{n:05} " + "q" * 30 for n in range(1, 3001)]
    out = say(Ran("\n".join(lines), 0))[0].text
    saved(out).unlink()
    start, end = out.split("Start:\n")[1].split("\n[...]\nEnd:\n")
    assert all(line in lines for line in start.split("\n") + end.split("\n"))  # no fragment of a line
    assert start.startswith("row00001 ") and end.endswith("row03000 " + "q" * 30)
    out = say(Ran("q" * 200_000 + "\n" + "\n".join(lines) + "\n" + "z" * 200_000, 0))[0].text
    saved(out).unlink()
    assert "Start:\n" + "q" * 250 + "…(line 1, 195 KB, excerpt mid-line)…\n[...]" in out
    assert out.endswith("End:\n…(line 3002, 195 KB, excerpt mid-line)…" + "z" * 250)


def test_leading_spaces_at_the_start_of_the_end_preview_are_kept(say):
    out = say(Ran("x\n" * 3000 + "    indented", 0))[0].text
    saved(out).unlink()
    assert out.endswith("\nx\n    indented")


def test_without_long_lines_the_note_says_only_the_median(say):
    out = say(Ran("ab\n" * 3000, 0))[0].text
    saved(out).unlink()
    assert "\nmedian line 2 B\n" in out and "lines >=" not in out


def test_too_many_bytes_in_a_few_lines_are_saved_too_and_the_size_is_told(say):
    out = say(Ran(("y" * 100_000 + "\n") * 12, 0))[0].text
    saved(out).unlink()
    assert "1.1 MB, 12 lines" in out and "y" * 300 not in out


def test_a_too_large_output_is_still_told_how_the_command_ended(say):
    big = "".join(f"{n}\n" for n in range(1, 5001))
    failed = say(Ran(big, 3))[0].text
    timed_out = say(Ran(big, None, timed_out=True), timeout=5)[0]
    for out in (failed, timed_out.text):
        saved(out).unlink()
    assert re.search(r"\n\[exit code 3 after \d+\.\ds\]$", failed)
    assert timed_out.error and timed_out.text.endswith("\n[timed out after 5s and stopped]")


def test_outside_tmux_the_call_fails_and_says_why(monkeypatch):
    async def no_tmux(*args):
        raise TmuxError("not running inside tmux")

    monkeypatch.setattr(terminal, "run", no_tmux)
    result = asyncio.run(REGISTRY.run("bash", {"command": "ls"}, Context(call=CALL)))
    assert result.error and "not running inside tmux" in result.text
