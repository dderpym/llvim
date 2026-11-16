# `std/panels/logviewer/screen.py`: Screen

The terminal, taken over: raw input, the mouse, the alternate screen, and drawing only the rows that changed.

```python
with Screen(mouse=True, paste=False) as screen:
    loop.add_reader(screen.fds()[0], wake)        # and the others: a resize writes to one
    for event in screen.read(): ...
    screen.draw(rows, cursor=(3, 0))
```

- `Screen(fd_in=stdin, out=stdout, mouse=True, paste=False)`, as a context manager: raw mode, the alternate screen, the mouse with drags,
  and with `paste` bracketed paste; all undone on leaving.
- `read()`: the keys and mouse events waiting, without blocking. `EOFError` once the terminal is gone. Sets `resized` after a resize.
- `fds()`: the files to wait on: the keyboard, and a pipe a resize writes to.
- `draw(rows, cursor=None)`: writes only the rows that differ from the last frame, in one synchronized update. `invalidate()`: the
  next draw writes everything.
- `copy(text)`: puts text on the terminal's clipboard with OSC 52. `size()`: `(columns, rows)`. `cbreak()`: lets Ctrl-C interrupt for
  a while.

## Why it is this way

- **A resize is a file to wait on.** SIGWINCH writes to a pipe (`signal.set_wakeup_fd`), so a loop that waits on files wakes for a
  resize as for a key.
- **Only changed rows are written.** A streamed chunk changes a row or two, and writing the whole screen each time flickers.
