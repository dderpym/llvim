# `session.py`: Session, Pane, `llvim-run`

A start script lays the panes of a session out with a `Session`, and says what runs in each. `llvim-run` runs it, and runs the
program of each pane.

```python
from llvim.std.panels.input import STANDARD, Input
from llvim.std.panels.logviewer import Viewer
from llvim.std.panels.status import Status

def viewer():  Viewer().run()
def palette(): Input(commands=STANDARD).run()

def start(s):
    bar = s.split(s.here, below=5, run=palette, name="input")
    s.split(bar, above=1, run=Status, name="status")
    s.split(s.here, right="40%", run="htop")       # a shell command works too
    s.here.run(viewer, name="viewer")
```

- `s.here`: the first pane, where the script runs. `s.here.run(...)` replaces the script with that program once `start` returns.
- `s.split(pane, below= | above= | right= | left=, run=, name=None) -> Pane`: rows or columns, or a percentage (`"40%"`). Not
  exactly one side: `TypeError`.
- `s.window(run=, name=None) -> Pane`: a background window, for what need not be seen (a provider).
- `pane.run(run, name=None)`, `pane.focus()`, `s.name(pane, name)` (the option panels find each other by, `@llvim_pane_<name>`;
  [keys.md](std/panels/keys.md)), `s.tmux(*args)` for any other tmux command. `s.env`, `s.project`, `s.log`.
- `run=`: a shell command, or a top-level function or class of the start script or of a module. What it returns is run (`.run()`) if
  it has a `run`. Anything that cannot be found by name (a lambda, a nested function): `TypeError`, in `start`.
- `llvim-run --start <script.py>`: imports the script, calls `start(session)`, then becomes what `here` runs. No `start`: exits
  saying so. `llvim-run <script.py>:<name>` or `<module>:<name>`: one pane's program.

## Using it

- The viewer, the input bar and the status line look for each other as `viewer`, `input` and `status`: name their panes so.
- A pane whose program fails shows the error and waits for Enter before it closes.
- The script's folder is on the import path, so files beside it can be imported.

## Why it is this way

- **A pane's program is found by name.** Each pane is a process of its own: a function cannot cross into it, but its name can. The
  pane imports the script again and calls the function, as `multiprocessing`'s spawn does. So importing the script must start
  nothing, and only `start` acts.
- **Plugins are values.** A command or a renderer is something a module exports, and nothing registers itself on import, so what a
  pane can do is read in one file.
- **The layout is a program.** Any tmux command, any number of panes, conditions, a panel of your own: there is no layout format to
  grow.
- **Panes stay processes.** One panel failing does not take the others down.
