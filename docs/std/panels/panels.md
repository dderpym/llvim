# `std/panels/`: the programs in the panes

Small terminal programs that run in the panes of a session, each its own command, each reading or writing the log like any other
program.

| File | What it defines |
|---|---|
| [keys.py](keys.md) | `route`, `Redirect`, `Panes`, `parse`: what a panel does with a key, and passing a key to another panel |
| [logviewer/](logviewer/logviewer.md) | `Viewer`, `logviewer`: shows a log and follows it live |
| [input/](input/input.md) | `Input`, `llvim-input`: the bar where you write to the log |
| [status/](status/status.md) | `Status`, `llvim-status`: one line that says what is happening to the log, made of renderers |

## Why

- **Separate programs.** A panel that is its own program can be placed anywhere, replaced by your own, or left out, and it can crash
  or be restarted without touching the others. They share the log, not memory.
- **Each draws its own screen.** A menu above a prompt, a live box in the log, selecting text that belongs to the log and not to the
  screen: none of it fits a line-based terminal. The screen code ([screen.md](logviewer/screen.md)) and the cell-width text code
  ([ansi.md](logviewer/ansi.md)) live in the viewer's folder and the bar uses them too.
