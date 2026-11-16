# `std/panels/status/bar.py`: State, StatusBar, compose

What a status renderer is given, and the bar that updates the renderers and puts their pieces in one line.

```python
bar = StatusBar(log, screen, [activity, model])
await bar.run()
```

- `State(snapshot, last, holder, model, busy_since, now)`: the log as read; its last message, decoded; the holder's request; the model
  of the last message that names one; when the turn in progress began (`None` when it is over), on the clock of `now`.
- A status renderer is `fn(state) -> str | None`: a piece of the line, colour codes allowed, or `None` for nothing.
- `compose(pieces, cols)`: the pieces that are not empty, joined with ` · `, padded to the width; too long, cut and ended with `…`.
- `StatusBar(log, screen, renderers, panes=None, clock=time.monotonic)`:
  - `line(snapshot, cols)`: each renderer given the state now, and the composed line. A renderer that raises shows nothing.
  - `run()`, async: draws the line when the log changes, and once a second while the turn runs. It ends when the terminal closes.
  - `on_key(raw)`: sends the key to the input bar.

## Using it

- A turn is "busy" while someone holds the log or a cue is the last message, the same as [cues.md](../../cues.md) says.
- The model is found by reading back from the last message, once per snapshot. A long log in which no message names a model costs
  that read on every change.

## Why it is this way

- **Renderers are plain functions.** A piece of a status line has no state worth keeping between draws and takes no keys, so it needs
  none of a viewer [box](../logviewer/box.md)'s hooks: it is given the state, and says what to show.
- **The bar does the timing.** It knows when the turn began and calls the renderers once a second while it runs, so a renderer that
  shows a clock is a pure function of the state, and when idle the bar draws nothing at all.
- **One decoded message, not the whole log.** The bar reads on every streamed chunk, and what is happening is said by the last
  message and the holder. A renderer that wants more has the snapshot.
