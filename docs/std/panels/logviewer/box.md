# `std/panels/logviewer/box.py`: Box, Host, Renderer

A renderer claims messages and makes a `Box` to show them. A box is built, and may be updated; everything else it can do is a hook it
registers on its host.

```python
@box(lambda m: m.extra.get("job"))               # messages with the same "job" go to one box
class Job(Box):
    def __init__(self, host, messages):
        super().__init__(host, messages)
        self.lines = ["starting…"]
        host.start(self.update)                  # in its own thread, if the viewer is live

    def update(self):
        self.lines = [f"done: {fetch(self.messages)}"]
        self.changed()
```

- `Box(host, messages)`: `lines` is what it shows (colour codes allowed; the viewer wraps them). `changed()` says to draw again, from
  any thread. `closed` is an event set when the box is dropped. `framed` (default `True`): its frame is left out of copied text.
- `Host`: `cols`, `project`, `live` (`False` when printing: nothing starts), `start(fn)`, `changed(box)`, `control()` (a tmux
  [Control](../../tmux.md)), `request_focus(box)`, and the hooks, each `host.<hook>(box, fn)`:
  - `on_messages(fn(messages))`: its messages changed. Without it, the box is made again.
  - `layout(fn(cols) -> rows)`: draws itself at a width instead of having `lines` wrapped.
  - `focusable(fn() -> bool | bool)`, `on_focus(fn(bool))`, `on_key(fn(raw))`, `cursor(fn() -> (col, row) | None)`: the keyboard.
  - `text(fn() -> str)`: its plain text, for printing and copying. `on_click(fn())`. `on_close(fn())`.
- `Renderer(claim, make, name)`: `claim(entry)` is a group key or `None`; `make(host, entries)` is the box.
- `box(claim)`: a decorator that makes a Box class a Renderer. `alone(entry)`: a claim for just this message (its id).
- `chain(renderers)`: those given, then the [built-in ones](boxes.md). `claimed`, `group`, `make` (the fallback, if `make` raises).

## Using it

- A box's `__init__` runs when it first comes into view, not when its messages arrive, so a box never scrolled to never starts.
- Say `self.changed()`, not `host.changed()`, from a box with a `layout` hook: the viewer then lays out that box alone.
- A claim that raises does not claim. A box that raises in `__init__`, a hook or `update` is replaced by the fallback.

## Why it is this way

- **A small core.** A box is built and updated; every other capability is a hook. The viewer never probes a box for methods it might
  have, so a new capability is a new hook, not a change to every box.
- **Groups are keyed by message id.** `alone` was the message object's identity; a read of the log now makes new objects for the same
  message, so the id is what stays.
- **Threads, not processes.** An `update` waits on I/O, so a thread is enough, it shares memory with its box, and it costs nothing to
  start.
