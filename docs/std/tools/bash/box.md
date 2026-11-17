# `std/tools/bash/box.py`: BOX

How the viewer shows a bash call or a `terminal` call. While the command runs, the box is its terminal, live. When the result comes, the box shows the end
of what it printed.

```
╭─ $ make test ───────────────────────────────╮
│ building…                                   │
│ ok 12 passed                                │
╰ click to type ──────────────────────────────╯
```

- `BOX`: the renderer, for `Viewer(renderers=[...])`. `claim` gives a bash call, its start and its result the call id as their key,
  so they make one box.
- While the call has no result, the box finds the pane tagged with the call id ([terminal.md](terminal.md)) through the viewer's
  tmux connection. It attaches, and paints the screen about 30 times a second while it changes. It looks every 0.2 s for a pane
  that has not appeared yet, and every 2 s after 10 s.
- `interactive` call: the box can take the keyboard. A click gives it, and ctrl-] or a click outside gives it back. Keys go to the
  terminal as they were typed.
- A call the user made (`/bash`) asks for the keyboard as soon as its terminal is up.
- A `terminal` call is a box of its own. One that starts a terminal is titled `$ command` and shows its own pane, as a bash call
  does. A turn is titled by what it does (`⇄ type "y\n"`, `⇄ your turn: type your password`) and shows the terminal it names,
  found by the id of the call that started it.
- A kept terminal ([shared.md](shared.md)) takes the keyboard only while its `@llvim_owner` is `user`. Then the box is yellow,
  asks for the keyboard once, and says *your turn*. ctrl-g gives it back to the model; anywhere else, ctrl-g is a key like any
  other.
- With a result: the last 20 rows, red if the call failed or the command exited non-zero.
- Its plain text is `$ command` and the output, which is what `--plain` prints and what a copy holds.

## Why it is this way

- **Found by its call id, through tmux.** The box needs nothing in the log but the call. The pane is wherever the tool started it,
  and the tag is how two programs that never talk agree on it.
- **A plain `Box`.** It uses only the hooks every box has ([box.md](../../panels/logviewer/box.md)), so the viewer has no knowledge of bash.
- **ctrl-g to hand back.** It had to be a key the box takes before the terminal does, and one rarely typed at a password or a
  question. ctrl-] already leaves the box, and leaving is not done: you may click away to read the log and come back. Ctrl-g is
  readline's abort, which matters little at a prompt you are about to give away.
- **The terminal is sized to the box.** The box resizes the hidden window to its inside width, so what the command draws is what
  fits.
