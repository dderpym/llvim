"""std/panels/logviewer/text.py: the colours of the built-in renderers, cleaning untrusted text, and how a message looks
as plain terminal text."""

import json
import re

RESET = "\x1b[0m"
CLEAR = RESET + "\x1b[H\x1b[2J\x1b[3J"  # the reset: a stream cut short must not leave its colour on
HEAD = "\x1b[1;36m"
GREY, GREY_HEAD = "\x1b[38;5;245m", "\x1b[38;5;240m"  # for thinking: the text, and its label a step darker

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean(text: str) -> str:
    return _CONTROL.sub("", text)


def tags_text(tags) -> str:
    return clean(" ".join(t if isinstance(t, str) else json.dumps(t) for t in tags))


def default(tags, content: str) -> str:
    return f"{HEAD}{tags_text(tags)}{RESET}\n{clean(content)}\n\n"


def thinking(tags, content: str) -> str:
    return f"{GREY_HEAD}{tags_text(tags)}{RESET}\n{GREY}{clean(content)}{RESET}\n\n"


def is_thinking(tags) -> bool:
    return "thinking" in tags


def partial(tags, text: str) -> str:
    """A message still streaming, with no trailing newline. Its colour stays on until ``RESET`` closes it."""
    if is_thinking(tags):
        return f"{GREY_HEAD}{tags_text(tags)}{RESET}\n{GREY}{clean(text)}"
    return f"{HEAD}{tags_text(tags)}{RESET}\n{clean(text)}"

