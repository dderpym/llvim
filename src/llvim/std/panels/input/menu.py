"""std/panels/input/menu.py: Menu, the suggestions shown as you type, which one is chosen, and when it stays shut."""

from __future__ import annotations

from dataclasses import dataclass, field

from llvim.std.panels.input.complete import Suggestion


@dataclass
class Menu:
    items: list[Suggestion] = field(default_factory=list)
    selected: int | None = None  # none until Tab or an arrow chooses one
    dismissed: str | None = None  # the line Esc closed it at: it stays shut until the line changes

    @property
    def shown(self) -> bool:
        return bool(self.items) and self.dismissed is None

    def refresh(self, items: list[Suggestion], line: str) -> None:
        """The suggestions for the line now. A choice is kept while its suggestion is still there."""
        if self.dismissed is not None and line != self.dismissed:
            self.dismissed = None
        chosen = self.items[self.selected] if self.selected is not None and self.selected < len(self.items) else None
        self.items = items
        self.selected = items.index(chosen) if chosen in items else None

    def move(self, delta: int) -> None:
        """Choose the next (or the previous) suggestion, round to the other end."""
        if self.items:
            start = -1 if delta > 0 else 0
            self.selected = (self.selected if self.selected is not None else start) + delta
            self.selected %= len(self.items)

    def current(self) -> Suggestion | None:
        return self.items[self.selected] if self.selected is not None else None

    def dismiss(self, line: str) -> None:
        self.dismissed = line

    def open(self) -> None:
        self.dismissed = None
