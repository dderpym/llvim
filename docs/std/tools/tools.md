# `std/tools/`: tools

What a model may call, how a call looks in the log, and the program that runs the calls. Nothing here knows about any model API, and
nothing registers itself: a tool is a value, and the [start script](../../config/start.md) gives the provider and the runner theirs.

```
user:              list the files                    ← you; cue generate
assistant:         I'll look.                        ← the provider
tool_call bash     {"command": "ls"}                 ← the provider; cue tools
tool_start bash                                      ← the runner, holding the log
tool_result bash   a.txt  b.txt                      ← the runner; cue generate
assistant:         There are two files.              ← the provider again
```

| File | What it defines |
|---|---|
| `__init__.py` | The public names: `Tool`, `Registry`, `Context`, `Result`, `ToolError`, `check`, `tool` |
| [registry.py](registry.md) | `Tool`, `Registry`, `Context`, `Result`, `ToolError`: a tool described once, and a call run the way a model asked |
| [calls.py](calls.md) | `pending`, `cut_off`, `call`, `answer`: how calls, starts and results look in a log |
| [runner.py](runner.md) | `Runner`, `llvim-tools`: the program that answers the calls |
| [bash/](bash/bash.md) | The bash tool, its box in the viewer, and `/bash` |

## Why

- **The runner is a program of its own, not part of the provider.** It is shaped like a provider: wait for a cue, claim the log,
  answer, commit, release. Any provider that writes `tool_call` messages and cues `tools` gets its calls run, and a provider or
  runner that crashes leaves the log as it was.
- **A tool is a neutral description.** A name, a sentence and a JSON Schema are what every function-calling API takes in some shape.
  Each provider translates; the registry stays out of every API's way.
- **Tools are on the async side.** A tool may be an `async def`. It then runs on the runner's event loop, with the log and the
  runner's held [Writer](../../core/writer.md): it can read the log, write into it live, and await whatever it waits on. It is
  stopped with asyncio's own cancel. A plain function runs in a thread and is told to stop with an event, since a thread cannot
  be stopped from outside.
- **The log holds only what happened.** It holds the call, that it was taken, and its result. Where a call runs, such as bash's
  terminal pane, is not in the log; a viewer finds it by the call's id ([bash/box.md](bash/box.md)).
