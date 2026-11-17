# `std/void/`: void

Voiding takes a message out of the conversation without taking it out of the log. A voided message has the tag `void`: the viewer
shows nothing for it and the model is not sent it. It can be restored.

```python
from llvim.std import void

Viewer(renderers=[void.BOX, bash.BOX])                  # first, so a voided bash call shows nothing
OpenAI(tools=TOOLS, context=[void.CONTEXT])
Status(context=[void.CONTEXT])                          # the status line reports the conversation the model has
Input(commands=[*STANDARD, void.COMMAND])               # /void
```

| File | What it defines |
|---|---|
| `__init__.py` | `BOX`, `CONTEXT`, `COMMAND`, and `VOID`, `is_void` |
| [tag.py](tag.md) | `VOID`, `is_void`, `marked`, `unmarked`: the tag, and putting it on a message |
| [context.py](context.md) | `CONTEXT`: the context renderer that leaves voided messages out |
| [box.py](box.md) | `BOX`: the viewer's renderer for voided messages |
| [turns.py](turns.md) | `Turn`, `Element`, `turns`: the log as the picker lists it |
| [picker.py](picker.md) | `Picker`, `llvim-void`: the list where you void and restore |
| [command.py](command.md) | `COMMAND`: `/void`, the picker in a tmux popup |

## Why

- **A tag, not a removal.** `Writer.remove` and `restore` already take messages away. Voiding keeps them: the log still says what
  happened, a voided message can be put back with one key, and what was voided is in the log's history like any other change.
- **Each program is told separately.** Nothing in core or in the other programs knows the tag. The viewer hides voided messages
  because it was given `BOX`, and the provider and the status line leave them out because they were given `CONTEXT`. A start script that gives only one
  gets only that: a viewer without `BOX` shows voided messages, tagged `void`.
- **A voided cue is not a cue.** A cue is exactly `["cue", channel]` ([cues.md](../cues.md)), so the extra tag makes it stop
  asking. Voiding a turn nobody answered ends it, with no change to the cue rules.
- **The tool runner does not read the tag.** A call is not run after the user has spoken, and the note a stop leaves counts as
  speaking, voided or not. Hiding voided messages from the runner was rejected: voiding a stop note would then make the calls
  before it wait to be run again.
