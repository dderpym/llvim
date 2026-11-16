# `core/`: the model

The model of llvim: a log of messages kept in git, and the one Writer that may change it.

| File | What it defines |
|---|---|
| [log.py](log.md) | `Log`, `Snapshot`, `Message`, `Request`: reading, watching and claiming a log, and all access to git |
| [writer.py](writer.md) | `Writer`, `Moved`: changing a log, committing, restoring |

## Why

- **Core depends on nothing else in llvim.** Everything else stands on it, so it is tested with the real thing: real git, real locks, real processes that die.
- **Everything shared lives on disk.** Holders, waiters and uncommitted writes are files in the store, and history is in git. So any process can read a log, claim it, or wait on it, and a process that dies leaves nothing that the others must clean up by hand.
