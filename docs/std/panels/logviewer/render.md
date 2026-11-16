# `std/panels/logviewer/render.py`: renderer, render

A text function as a renderer, and one message as plain text through a chain of renderers.

```python
@renderer(lambda tags: "note" in tags)
def note(tags, content):
    return f"\x1b[2m{content}\x1b[0m\n\n"

render(entry, chain([note]))            # the text the first renderer that claims it gives
```

- `renderer(match)`: a decorator that makes `fn(tags, content) -> str` the Renderer of the messages whose tags `match` accepts, one
  box each. The content it gets is cleaned of control characters.
- `render(entry, renderers=None)`: the plain text of the first renderer that claims the message and makes a box that gives text.
  `None` is the built-in chain.

## Using it

- A renderer that raises, or gives something other than text, is skipped. Nothing is reported: try a new renderer with
  `logviewer --once`.

## Why it is this way

- **A text renderer is a box made for you.** Everything shows through boxes, so a text function is the easy way to make one, and works
  on screen and in print alike.
- **Printing starts nothing.** The host is not live, so a box that would run a program shows its plain text instead.
