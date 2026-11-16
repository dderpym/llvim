"""std/panels/input/pane.py: Growth, which makes the input pane as tall as what it holds."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from llvim.std.panels.keys import tmux

FORMAT = "#{pane_id} #{pane_left} #{pane_top} #{pane_width} #{pane_height}"


@dataclass(frozen=True)
class Slot:
    id: int  # the number of the pane id (``%3`` is 3)
    top: int
    height: int


def checksum(text: str) -> str:
    """tmux's checksum of a layout string, which it wants in front of it."""
    csum = 0
    for ch in text:
        csum = ((csum >> 1) + ((csum & 1) << 15) + ord(ch)) & 0xFFFF
    return f"{csum:04x}"


def stack(width: int, height: int, heights: list[tuple[int, int]]) -> str:
    """The layout string of panes stacked top to bottom, one border row between: ``heights`` is [(pane number, rows)]."""
    leaves, y = [], 0
    for number, rows in heights:
        leaves.append(f"{width}x{rows},0,{y},{number}")
        y += rows + 1
    body = f"{width}x{height},0,0[{','.join(leaves)}]"
    return f"{checksum(body)},{body}"


def fit(height: int, panes: list[Slot], mine: int, rows: int) -> list[tuple[int, int]] | None:
    """The heights of a stack of panes with pane ``mine`` made ``rows`` tall, the others as they are and the top one taking
    or giving the difference. None if there is no room for that."""
    if len(panes) < 2 or panes[0].id == mine:
        return None
    heights = [(p.id, rows if p.id == mine else p.height) for p in panes]
    top = height - sum(h for _, h in heights[1:]) - (len(panes) - 1)
    return [(panes[0].id, top), *heights[1:]] if top >= 1 else None


class Growth:
    """Sets the height of the pane this bar runs in: the usual ``base`` rows, plus ``extra`` while the menu or a long message needs them.

    It does not remember how the window was. Each time it reads the panes as they are now and lays the window out again with its
    own pane the height it wants: the panels above (the status line, one row) keep theirs, and the viewer, on top, takes the rest.
    Nobody moves them by hand (the layout has no keys for it), so what is asked for is what there is.
    """

    def __init__(self, base: int = 3, run: Callable[[list[str]], str] | None = None, pane: str | None = None):
        self.base, self.run = base, run or tmux
        self.pane = os.environ.get("TMUX_PANE") if pane is None else pane
        self.extra = 0

    def want(self, extra: int) -> None:
        """Have ``extra`` rows more than usual (zero: the usual), but never more than about half the window. Does nothing outside
        a tmux pane, or if tmux refuses."""
        if not self.pane:
            return
        try:
            width, height, *_ = self.run(["display-message", "-p", "-t", self.pane, "#{window_width} #{window_height}"]).split()
            width, height = int(width), int(height)
            extra = max(0, min(extra, height // 2 - self.base))
            if extra == self.extra:
                return
            panes = []
            for line in self.run(["list-panes", "-t", self.pane, "-F", FORMAT]).splitlines():
                pid, left, top, w, h = line.split()
                if int(left) != 0 or int(w) != width:
                    return  # not a stack of panes: not ours to lay out
                panes.append(Slot(int(pid.lstrip("%")), int(top), int(h)))
            panes.sort(key=lambda p: p.top)
            heights = fit(height, panes, int(self.pane.lstrip("%")), self.base + extra)
            if heights is None:
                return
            self.run(["select-layout", "-t", self.pane, stack(width, height, heights)])
            self.extra = extra
        except Exception:
            pass  # tmux said no, or it is not a layout of ours: the pane stays as it is, and the menu shows in the rows there are
