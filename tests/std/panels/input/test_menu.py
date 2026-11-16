"""std/panels/input/menu.py: which suggestions are shown and which is chosen."""

from llvim.std.panels.input.complete import Suggestion
from llvim.std.panels.input.menu import Menu

A, B, C = (Suggestion(t, 0, 1) for t in "abc")


def test_it_is_shut_without_suggestions_and_after_esc_until_the_line_changes():
    m = Menu()
    assert not m.shown
    m.refresh([A, B], "/")
    assert m.shown
    m.dismiss("/")
    m.refresh([A, B], "/")
    assert not m.shown
    m.refresh([A], "/a")
    assert m.shown


def test_moving_chooses_from_either_end_and_wraps():
    m = Menu()
    m.refresh([A, B, C], "/")
    m.move(1)
    assert m.current() == A
    m.move(-1)
    assert m.current() == C
    m.move(1)
    assert m.current() == A


def test_a_choice_stays_while_its_suggestion_is_still_offered():
    m = Menu()
    m.refresh([A, B], "/")
    m.move(1)
    m.move(1)
    m.refresh([B, C], "/")
    assert m.current() == B
    m.refresh([C], "/")
    assert m.current() is None
