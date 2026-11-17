# `std/tools/bash/`: bash

Bash as the values a start script hands out: `TOOL` and `TERMINAL`, which a model calls; `BOX`, which shows a call in the viewer
as a live terminal; and `COMMAND`, which is `/bash` in the input bar. Importing it registers nothing.

```python
from llvim.std.tools import bash

Runner(tools=[bash.TOOL, bash.TERMINAL])          # the runner runs them, and the provider offers them
Viewer(renderers=[bash.BOX])
Input(commands=[*STANDARD, bash.COMMAND])
```

| File | What it defines |
|---|---|
| [tool.py](tool.md) | `TOOL`: run a command and tell the model what it printed; `TERMINAL`: a turn at a kept terminal |
| [terminal.py](terminal.md) | `run`: a command in a hidden tmux window tagged with its call |
| [shared.py](shared.md) | a terminal kept open past its call, which the model and the user take turns at |
| [settings.py](settings.md) | `setting`: the tool's numbers, from the environment, `bash.toml` or a default |
| [box.py](box.md) | `BOX`: the call in the viewer, live while it runs |
| [command.py](command.md) | `COMMAND`: `/bash`, a terminal of your own in the log |

## Why

- **One terminal, two parties, linked by the call id.** The tool starts the command in a hidden tmux window and tags the pane with
  the call's id. The viewer's box knows that id from the `tool_call` message, finds the pane by it, and paints it. Nothing about
  the pane is in the log, and the runner knows nothing of tmux.
- **A real terminal.** Programs see a tty, so they colour and lay out as they would for you. The user watches the command run, and
  can type into it when it needs them (a `sudo` password).
- **A terminal can outlive its call.** With the `terminal` tool the model starts a program, types into it, reads it, hands it to you for what only
  you should type, and takes it back. Who may type is a pane option both sides read ([shared.md](shared.md)).
- **No approval step and no sandbox.** The command runs with your permissions. Run llvim where that is acceptable.
