# `std/panels/logviewer/app.py`: Viewer

The screen of the log: it follows the log, scrolls, selects and copies, and gives the keyboard to a box that takes it.

```python
with Screen() as screen:
    asyncio.run(Viewer(log, log.project, screen, renderers=renderers).run())
```

- `Viewer(log, project, screen, panes=None, renderers=())`. `panes` defaults to the session's, over a tmux control connection made
  when first needed.
  - `run()`, async: until Ctrl-C with no input bar to pass it to, then closes every box.
  - `on_key(event)`: `False` to quit. `on_mouse(event)`: wheel, drag, click.
  - `scroll(rows)`, `frame()` (the rows and cursor to draw), `selected_text()`.

## Using it

- The viewer wakes when the log changes, when a key or the mouse arrives, when the terminal is resized, and when a box says it changed
  (from any thread). Otherwise it sleeps. A burst of changes is one redraw.
- A box's hooks run on the viewer's thread: one that hangs hangs the viewer, one that raises is replaced by the fallback.

## Why it is this way

- **Following is an anchor at the end.** The top of the screen is a slot and an offset ([document.md](document.md)). Scrolling up
  stops following, so text that arrives does not move what you read; scrolling back to the end follows again.
- **A selection belongs to the log.** Its ends are cells of slots, not of the screen, so it stays on its text while the screen
  scrolls, and copying gives the text it covers whether or not it is on screen.
- **The log is read in a task of its own.** It keeps only the newest snapshot, and the loop takes it when it wakes, so a reply that
  streams faster than the screen draws costs one layout per frame, not per chunk.
- **A box's threads wake the loop through a pipe.** They cannot touch the loop, but they can write a byte to a file it reads.
