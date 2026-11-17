# `std/tmux.py`: Control, Embedded

`Control` is one quick connection to a tmux server. `Embedded` is one program in a hidden tmux window that another program shows
and types into, with tmux as the terminal emulator.

```python
control = Control.here()                                   # the server this program runs in
term = Embedded.start(control, "make test", "/project", 80, 24, {"@llvim_call": "c1"})
shot = term.snapshot()                                     # the screen, with colours; cursor; dead; status
term.send(b"q")
term.close()
```

- `Control(server, session)`: a control-mode client (`tmux -C`). `Control.here()` connects to `$TMUX`'s server, and raises
  `TmuxError` outside tmux.
  - `run(command, timeout=2)`: the command's output. It fails, or tmux does not answer: raises `TmuxError`.
  - Threads take turns.
- `Embedded.start(control, command, cwd, columns, rows, options=None)`: runs `command` (shell text, any length and lines) in a new
  hidden window. `options` are pane options (`@name`) set before the program starts.
- `Embedded.attach(control, pane, columns, rows)`: looks at a program someone else started. A pane that is gone: `TmuxError`.
  `Embedded.find(control, option, value, columns, rows)`: attaches to the pane whose option has that value, or `None`.
- `snapshot()`: `lines` (with colour codes), `cursor` (`None` when hidden or done), `dead`, `status` (once dead).
- `send(raw)`, `interrupt()`, `resize(columns, rows)`, `transcript()` (everything printed, history included, wrapped lines joined).
- `close()`: ends the program and its window if this party started it; for one that attached, nothing. Twice is fine.

## Using it

- A `Control` answers in about 0.05 ms; a `tmux` process each time costs about 5 ms. Make one and keep it.
- `transcript()` is the screen and its history. Lines that wrapped are joined, and the trailing spaces are the program's own, not
  padding. Empty rows follow the last line, down to the bottom of the screen.

## Why it is this way

- **tmux does the terminal work.** Parsing a program's output into a screen is a terminal emulator. tmux has a good one, and asking
  it for the rendered screen is cheap once the connection is open.
- **The command never goes through tmux's command line.** It is one line of text with its own quoting, so a heredoc broke it and a
  long command could not be quoted safely. `start` writes the command to a file, and tmux runs a wrapper script, also a file.
- **The program starts after the window is sized.** The wrapper waits on a `tmux wait-for` signal sent once the window has its
  size, so the program never starts at the wrong width, and one that ends at once still has its screen to read.
- **A pane is never left dead.** The wrapper records the exit status in the pane option `@llvim_status` and waits, so the screen
  stays and tmux draws no "Pane is dead" note over it. `remain-on-exit` was rejected: tmux scrolls the screen into history and
  prints the note.
- **Panes are found by their options.** Tagging a pane before its program starts means nothing about it is written anywhere but
  tmux.
