"""std/panels/logviewer/box.py: what a renderer makes, how messages are claimed and grouped, and what a host gives a box."""

import threading
import time

from llvim.std.panels.logviewer import boxes
from llvim.std.panels.logviewer.box import Box, Host, Renderer, alone, box, chain, group, make


def names(messages, renderers=()):
    return [(r.name, [m.content for m in ms]) for r, ms in group(messages, chain(renderers)).values()]


def test_messages_that_get_the_same_key_go_to_one_box_in_the_order_of_the_first_of_them(entry):
    pair = box(lambda m: m.extra.get("pair"))(type("Pair", (Box,), {}))
    messages = [entry(["a"], "1", pair=1), entry(["x"], "plain"), entry(["b"], "2", pair=1), entry(["c"], "3", pair=2)]
    assert names(messages, [pair]) == [("Pair", ["1", "2"]), ("fallback", ["plain"]), ("Pair", ["3"])]


def test_box_makes_a_renderer_and_those_given_are_tried_before_the_built_in_ones_in_order(entry):
    mine = box(lambda m: alone(m) if m.tags == ["thinking"] else None)(type("Mine", (Box,), {}))
    greedy = box(alone)(type("Greedy", (Box,), {}))
    assert isinstance(mine, Renderer)
    assert [n for n, _ in names([entry(["thinking"]), entry(["assistant"])], [mine, greedy])] == ["Mine", "Greedy"]
    assert [n for n, _ in names([entry(["thinking"]), entry(["assistant"])])] == ["thinking", "markdown"]


def test_alone_keys_a_message_by_its_id_so_its_group_outlives_a_new_read_of_it(entry):
    first = entry(["a"], "x")
    assert alone(first) == first.id and alone(first) != alone(entry(["a"], "x"))


def test_a_claim_that_raises_does_not_claim(entry):
    broken = box(lambda m: 1 / 0)(type("Broken", (Box,), {}))
    assert [n for n, _ in names([entry(["a"])], [broken])] == ["fallback"]


def test_a_box_that_raises_when_it_is_made_is_replaced_by_the_fallback_for_its_messages(entry, stub_host):
    class Broken(Box):
        def __init__(self, host, messages):
            raise RuntimeError("bad box")

    made = make(box(alone)(Broken), stub_host, [entry(["a"], "readable")])
    assert type(made) is boxes.Fallback and "readable" in "".join(made.lines)


class Live(Host):
    live = True

    def __init__(self):
        self.changes = threading.Event()

    def changed(self, box=None):
        self.changes.set()


def test_update_runs_in_its_own_thread_and_says_when_the_box_changed():
    class Clock(Box):
        def __init__(self, host, messages):
            super().__init__(host, messages)
            self.lines = ["starting"]
            host.start(self.update)

        def update(self):
            self.lines = ["ticked"]
            self.host.changed()

    host = Live()
    clock = Clock(host, [])
    assert host.changes.wait(3) and clock.lines == ["ticked"]


def test_a_box_whose_update_raises_is_marked_failed_and_the_viewer_is_told():
    class Bad(Box):
        def __init__(self, host, messages):
            super().__init__(host, messages)
            host.start(self.update)

        def update(self):
            raise RuntimeError("update failed")

    host = Live()
    bad = Bad(host, [])
    assert host.changes.wait(3)
    for _ in range(100):
        if bad.error:
            break
        time.sleep(0.01)
    assert isinstance(bad.error, RuntimeError)


def test_a_host_that_is_not_live_starts_nothing(stub_host):
    ran = threading.Event()
    stub_host.start(ran.set)
    assert not ran.wait(0.05)
