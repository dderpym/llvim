# `config/start.py`: the shipped start script

`llvim` runs it unless `$LLVIM_HOME/start.py` exists; copy it there to change anything ([session.md](../session.md)). It lays the
session out like a coding agent: the log on top, a status line, then a three-line input bar.

```
┌──────────────────────────────────┐
│ viewer                           │  the log, following live
├──────────────────────────────────┤
│ status                           │  1 line: what is happening
├──────────────────────────────────┤
│ › input                          │  3 lines: where you type
└──────────────────────────────────┘
```

- The cursor starts in the input bar. The first pane becomes the viewer.
- If `$LLVIM_MODEL` is set or `$LLVIM_HOME/openai.toml` exists, the [OpenAI provider](../std/providers/openai.md) runs in a window
  of its own (`llvim-openai --configure` writes the file). With neither, nothing answers, and the status line says *waiting for a
  model*.
- The [tool runner](../std/tools/runner.md) runs in a window of its own. `TOOLS` is what the model is offered and the runner runs:
  bash, to start with. Add your own `Tool` values there ([registry.md](../std/tools/registry.md)). The viewer shows bash calls as
  live terminals, and the bar has `/bash`.

## Why it is this way

- **The bottom block is made first.** The first pane is split once for a block five lines tall (the bar's three, the status line,
  and the border between them), and that block is split again above for the status line. So the viewer takes everything else, and
  the input bar can grow upwards into it while its menu is open ([pane.md](../std/panels/input/pane.md)).
- **Each pane is named** `viewer`, `status`, `input`, which is how the panels send keys and the focus to each other.
- **No provider without a model.** It would only exit with an error in a window nobody sees.
- **The runner always runs.** It is idle until it is cued, and `/bash` needs it whether or not there is a model.
- **One list of tools, given to both.** A tool the model is offered but the runner does not have would fail every call, and the
  reverse is never called.
