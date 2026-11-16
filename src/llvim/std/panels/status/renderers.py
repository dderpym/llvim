"""std/panels/status/renderers.py: the built-in status renderers: what is happening to the log, and which model is at it."""

from llvim.std.conversation import Info, Tag
from llvim.std.cues import GENERATE, channel
from llvim.std.panels.status.bar import State

DIM, WORKING, ERROR, RESET = "\x1b[38;5;245m", "\x1b[1;36m", "\x1b[1;31m", "\x1b[0m"


def activity(state: State) -> str:
    """One phrase for what is happening, with how long the turn has taken while it is not over."""
    phrase, colour = _phrase(state)
    if state.busy_since is not None:
        phrase += f" · {int(state.now - state.busy_since)}s"
    return f"{colour}{phrase}{RESET}"


def _phrase(state: State) -> tuple[str, str]:
    last, holder = state.last, state.holder
    if holder is None:
        if last is not None and channel(last) == GENERATE:
            return "waiting for a model", WORKING
        if last is not None and last.tags[:1] == [Tag.ERROR]:
            return f"error: {last.content.splitlines()[0] if last.content else ''}", ERROR
        return "awaiting your input", DIM
    data = holder.data if isinstance(holder.data, dict) else {}
    if Info.PROVIDER in data:
        if last is not None and last.uncommitted:
            if last.tags[:1] == [Tag.STATUS]:
                return last.content, ERROR
            if last.tags[:1] == [Tag.THINKING]:
                return "thinking", WORKING
            if last.tags[:1] == [Tag.ASSISTANT]:
                return "writing", WORKING
        return "waiting for the model", WORKING
    if Info.INPUT in data:
        return "sending", WORKING
    return f"busy: {holder.data}", WORKING


def model(state: State) -> str | None:
    """The model at work, else the one that wrote the last reply."""
    data = state.holder.data if state.holder is not None and isinstance(state.holder.data, dict) else {}
    name = data.get(Info.MODEL) or state.model
    return f"{DIM}{name}{RESET}" if name else None


BUILTIN = [activity, model]

