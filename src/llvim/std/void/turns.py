"""std/void/turns.py: Turn and Element, a log as the picker lists it: turns, each made of the elements that can be voided alone."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from llvim.std.conversation import Entry, Tag
from llvim.std.cues import is_cue
from llvim.std.snapshot import is_record
from llvim.std.tools.calls import CALL, RESULT, START, call_id, kind, name
from llvim.std.void.tag import is_void, unmarked


class Voided(StrEnum):
    NONE = "none"
    PART = "part"
    ALL = "all"


def voided(entries: tuple[Entry, ...]) -> Voided:
    count = sum(is_void(entry) for entry in entries)
    return Voided.NONE if count == 0 else Voided.ALL if count == len(entries) else Voided.PART


@dataclass(frozen=True)
class Element:
    """What is voided together inside a turn: one message with the cues left after it, or a tool call with its start and result."""

    entries: tuple[Entry, ...]

    @property
    def id(self) -> int:
        return self.entries[0].id

    @property
    def voided(self) -> Voided:
        return voided(self.entries)

    @property
    def label(self) -> str:
        first = unmarked(self.entries[0])
        text = next((line.strip() for line in first.content.splitlines() if line.strip()), "")
        return f"{' '.join(str(tag) for tag in first.tags)}  {text}".strip()


@dataclass(frozen=True)
class Turn:
    """A user message and everything up to the next one. What comes before the first user message is a turn too."""

    elements: tuple[Element, ...]

    @property
    def id(self) -> int:
        return self.elements[0].id

    @property
    def entries(self) -> tuple[Entry, ...]:
        return tuple(entry for element in self.elements for entry in element.entries)

    @property
    def voided(self) -> Voided:
        return voided(self.entries)

    @property
    def label(self) -> str:
        first = unmarked(self.elements[0].entries[0])
        return (
            self.elements[0].label.removeprefix(str(Tag.USER)).strip()
            if _starts_turn(first)
            else self.elements[0].label
        )


def _starts_turn(entry: Entry) -> bool:
    """A message the user wrote. The note a stop leaves is tagged as theirs too, and belongs to the turn it stopped."""
    return entry.tags[:1] == [Tag.USER] and Tag.STOP not in entry.tags


def turns(entries: list[Entry]) -> list[Turn]:
    out: list[list[list[Entry]]] = []
    calls: dict[str, list[Entry]] = {}  # the element of each call of the turn being read
    for entry in entries:
        plain = unmarked(entry)
        if is_record(plain):
            continue
        if _starts_turn(plain) or not out:
            out.append([])
            calls = {}
        turn = out[-1]
        if is_cue(plain) and turn:
            turn[-1].append(entry)  # voided with what it asks about: alone, it would be answered without it
        elif kind(plain) in (START, RESULT) and name(plain) and call_id(plain) in calls:
            calls[call_id(plain)].append(entry)
        else:
            turn.append([entry])
            if kind(plain) == CALL and call_id(plain):
                calls[call_id(plain)] = turn[-1]
    return [Turn(tuple(Element(tuple(element)) for element in turn)) for turn in out]
