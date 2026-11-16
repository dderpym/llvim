"""std/panels/input/pane.py: the input pane sets its own height and the window is laid out around it."""

from llvim.std.panels.input.pane import Growth, Slot, checksum, fit, stack


def window(height=30, panes=((0, 0, 24), (2, 25, 1), (1, 27, 3)), width=100):
    """A runner that answers like tmux for a window of stacked panes, and keeps what it was told."""
    commands = []

    def run(args):
        commands.append(args)
        if args[0] == "display-message":
            return f"{width} {height}\n"
        if args[0] == "list-panes":
            return "".join(f"%{i} 0 {top} {width} {h}\n" for i, top, h in panes)
        return ""

    return run, commands


def test_a_layout_string_has_tmuxs_checksum_in_front():
    assert checksum("100x30,0,0,0") == checksum("100x30,0,0,0") and len(checksum("x")) == 4
    layout = stack(100, 30, [(0, 24), (2, 1), (1, 3)])
    assert layout.endswith("100x30,0,0[100x24,0,0,0,100x1,0,25,2,100x3,0,27,1]") and layout[4] == ","


def test_the_top_pane_gives_or_takes_the_rows_and_the_others_keep_theirs():
    panes = [Slot(0, 0, 24), Slot(2, 25, 1), Slot(1, 27, 3)]
    assert fit(30, panes, 1, 7) == [(0, 20), (2, 1), (1, 7)]
    assert fit(30, panes, 1, 3) == [(0, 24), (2, 1), (1, 3)]
    assert fit(30, panes, 1, 40) is None and fit(30, panes[:1], 0, 3) is None


def test_growing_lays_the_window_out_with_the_pane_taller_and_asking_again_does_nothing():
    run, commands = window()
    g = Growth(3, run, "%1")
    g.want(4)
    layout = commands[-1]
    assert layout[:3] == ["select-layout", "-t", "%1"] and "100x20,0,0,0" in layout[3] and "100x7,0,27,1" not in layout[3] and "100x7,0,23,1" in layout[3]
    count = len(commands)
    g.want(4)
    assert len(commands) == count + 1 and g.extra == 4  # looked at the window, laid nothing out


def test_going_back_is_the_same_thing_in_the_other_direction_with_no_saved_layout():
    run, commands = window(panes=((0, 0, 20), (2, 21, 1), (1, 23, 7)))
    g = Growth(3, run, "%1")
    g.extra = 4
    g.want(0)
    assert "100x24,0,0,0" in commands[-1][3] and "100x3,0,27,1" in commands[-1][3] and g.extra == 0


def test_it_never_takes_more_than_half_the_window():
    run, commands = window(height=20, panes=((0, 0, 14), (2, 15, 1), (1, 17, 3)))
    g = Growth(3, run, "%1")
    g.want(30)
    assert g.extra == 7 and "100x7," in commands[-1][3]


def test_outside_tmux_or_a_window_that_is_not_a_stack_or_when_tmux_refuses_nothing_breaks():
    g = Growth(3, window()[0], "")
    g.want(3)
    assert g.extra == 0
    side_by_side = lambda args: "100 30" if args[0] == "display-message" else "%0 0 0 50 30\n%1 51 0 49 30\n"  # noqa: E731
    g = Growth(3, side_by_side, "%1")
    g.want(3)
    assert g.extra == 0

    def refuse(args):
        raise RuntimeError

    g = Growth(3, refuse, "%1")
    g.want(3)
    assert g.extra == 0
