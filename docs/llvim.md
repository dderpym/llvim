# `llvim/`: the package

A coding agent reduced to one concept: the log, a sequence of messages tracked like git.

| File or folder | What it defines |
|---|---|
| [core](core/core.md) | The model: a log stored in git and the Writer that changes it |
| [std](std/std.md) | The standard library: the message format, cues, and the programs of a session |
| [cli.py](cli.md) | `llvim`: starts tmux with the shipped config and runs the start script |
| [session.py](session.md) | `Session`, `llvim-run`: how a start script lays the panes out and says what runs in each |
| [config](config/config.md) | The shipped start script and tmux config |

## Why

- **One concept.** The conversation, the agent's work and its history are all logs. A feature is built on logs, not added beside them.
