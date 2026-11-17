# `std/`: the standard library

Everything built on [core](../core/core.md): the message format the standard programs agree on, cues, and the programs that
run in a session. Nothing in core imports from here.

| File | What it defines |
|---|---|
| [env.py](env.md) | `home`, `log`, `settings`: where llvim keeps its settings, and which log a program is for |
| [conversation.py](conversation.md) | `Entry`, `encode`, `decode`, `entries`, `Tag`, `Info`: the message format and its tags |
| [cues.py](cues.md) | `cue`, `cued`, `busy`, `GENERATE`, `TOOLS`: messages that ask a program to act |
| [context.py](context.md) | `ContextRenderer`, `render`: a step between a log and a program that reads it as a conversation |
| [tmux.py](tmux.md) | `Control`, `Embedded`: a quick connection to tmux, and a program in a hidden tmux window |
| [panels/](panels/panels.md) | The programs for the panes of a session: the viewer, the input bar and the status bar |
| [providers/](providers/providers.md) | The programs that answer a log: the OpenAI-compatible provider |
| [tools/](tools/tools.md) | What a model may call, the runner that runs the calls, and bash |
| [void/](void/void.md) | Voiding: taking a message out of the conversation and leaving it in the log |

## Why

- **One protocol, written down.** The programs of a session never call each other: they share a log. What they agree on is in two
  files. [conversation.py](conversation.md) says what a message is, and [cues.py](cues.md) says when a program acts. A program can
  be replaced by one that knows only those two.
- **Every program acts on a cue, never on what the last message happens to be.** You send, and the bar commits a cue; the provider
  answers it. A reply overtakes the cue, so the turn is over exactly when no cue is last and nobody holds the log.
- **Who goes first is core's queue.** A program claims the log with a priority, and a holder that is `outranked()` yields. The
  input bar's stop outranks a provider; a message waits for the turn. Conventions of std's own on top (urgency, `yield_to`,
  `acquire`) were rejected: core's queue already orders claims by priority and tells the holder when someone higher waits.
- **Async, because core is.** Claiming, watching and committing are coroutines, so each program is one event loop that waits on
  the log and its own input (the keyboard, an HTTP stream) together.
