"""std/void/box.py: a voided message shows nothing in the viewer, whatever it was."""

from llvim.std.panels.logviewer.box import Renderer, group, make
from llvim.std.panels.logviewer.boxes import Fallback
from llvim.std.void import BOX

EVERYTHING = Renderer(lambda m: "all", Fallback, "everything")


def test_a_voided_message_is_claimed_ahead_of_a_renderer_listed_after_it_and_draws_no_rows(entry, stub_host):
    messages = [entry(["user"], "hi"), entry(["assistant", "void"], "gone"), entry(["tool_call", "bash", "void"], "{}")]
    groups = list(group(messages, [BOX, EVERYTHING]).values())
    voided = [make(renderer, stub_host, claimed) for renderer, claimed in groups if renderer is BOX]
    rest = [m.content for renderer, claimed in groups if renderer is EVERYTHING for m in claimed]
    assert len(voided) == 2 and all(box.lines == [] and box.text() == "" for box in voided)
    assert rest == ["hi"]
