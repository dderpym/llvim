"""std/panels/input/complete.py: what to suggest for the line being typed."""

from llvim.std.panels.input.commands import Command
from llvim.std.panels.input.complete import command_name, complete

COMMANDS = {
    "quit": Command("quit", "end", None),
    "fork": Command("fork", "branch", None, lambda arg: [(n, "") for n in ("main", "alt") if n.startswith(arg)]),
}


def test_a_slash_and_a_word_is_a_command_and_anything_else_is_a_message():
    assert [command_name(t) for t in ("/quit", "/EXIT", "/quit now", "/help me")] == ["quit", "exit", "quit", "help"]
    assert [command_name(t) for t in ("hello", "/etc/hosts", "/ hello", "//quit", "see /quit", "/")] == [None] * 6


def test_a_bare_slash_suggests_every_command_and_more_letters_narrow_them():
    assert [s.text for s in complete("/", 1, COMMANDS)] == ["/fork", "/quit"]
    (s,) = complete("/qu", 3, COMMANDS)
    assert (s.text, s.start, s.end, s.help) == ("/quit", 0, 3, "end")


def test_a_command_that_takes_an_argument_carries_on_with_a_space():
    assert [s.then for s in complete("/f", 2, COMMANDS)] == [" "]


def test_the_argument_is_completed_by_the_command_and_not_offered_once_complete():
    assert [s.text for s in complete("/fork a", 7, COMMANDS)] == ["alt"]
    assert complete("/fork alt", 9, COMMANDS) == []


def test_messages_get_no_suggestions():
    assert complete("hello", 5, COMMANDS) == [] and complete("//qu", 4, COMMANDS) == []
