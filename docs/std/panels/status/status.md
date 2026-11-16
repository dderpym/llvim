# `std/panels/status/`: Status, the status bar

`llvim-status [log] [-p project]` is one line that says what is happening to the log: *awaiting your input*, *thinking · 4s*,
*writing*. Like the viewer, it is made of renderers: each gives one piece of the line, and the bar puts them together.

```python
def turns(state):                                  # a status renderer: the state, then a piece of the line or None
    return f"{len(state.snapshot.messages)} messages"

Status(renderers=[*BUILTIN, turns]).run()          # the log is the session's (env.log)
```

| File | What it defines |
|---|---|
| `__init__.py` | `Status`, the program; `main`, the command |
| [bar.py](bar.md) | `State`, `StatusBar`, `compose`: what a renderer is given, and the line made of their pieces |
| [renderers.py](renderers.md) | `activity`, `model`, `BUILTIN`: the built-in renderers |

## Using it

- It shows and does not type: a key that reaches it goes to the input bar, and the focus with it.
- Off a terminal it exits saying so.

## Why

- **Renderers, as in the viewer.** What is worth a glance differs from one session to the next, so the line is made of pieces a start
  script chooses, and the bar is only the layer that updates them and composes them.
- **No animation.** A status that moves when nothing changes draws the eye for nothing; the old one's rainbow shimmer, redrawn many
  times a second, flashed. The line changes when the log does, and once a second while a turn runs, for its clock.
- **Everything shown comes from the log.** Who holds it, and the last message, say what is happening. So it needs nothing from the
  provider, and it is right however the log got that way.
