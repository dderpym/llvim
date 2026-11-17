# `core/`: the model

The model of llvim: a log of messages kept in git, and the one Writer that may change it.

| File | What it defines |
|---|---|
| `__init__.py` | The public names: `Log`, `Writer`, `Snapshot`, `Message`, `Request`, `Author`, `LLVIM`, `Commit`, `Offer`, and the errors `GitError`, `Moved`, `Released`, `Committing` |
| [log.py](log.md) | `Log`: reading, watching, claiming and forking a log. The public face of core |
| [writer.py](writer.md) | `Writer`, `Moved`, `Released`, `Committing`: changing a log, committing, restoring |
| [git.py](git.md) | `GitError`, `Author`, `Tree`, `commit`, `repack`: the repo, and all access to git |
| [live.py](live.md) | `Message`, `Snapshot`, `View`: the journal of uncommitted writes, and reading it |
| [handoff.py](handoff.md) | `Offer`, `take`: a claim handed to another process, the log held throughout |
| [queue.py](queue.md) | `Request`, `Queue`, `Wake`: claims as locked files, and waiting for a turn |
| [watch.py](watch.md) | `Watch`: inotify on a log's folder |

## Why

- **Core depends on nothing else in llvim.** Everything else stands on it, so it is tested with the real thing: real git, real locks, real processes that die.
- **One file per concern, with `log.py` on top.** git, the journal, the claims, handing a claim over and the file events each have a file, and none of those imports `log.py`: each takes a folder, a repo or a function, not a `Log`. So each is read, reviewed and tested alone, and `log.py` is the API a caller sees.
- **One import for callers.** `std` and everything else imports from `llvim.core`, never from a file in it. Which file defines a type is then free to change, and a caller can annotate a `Writer` and catch every error without knowing the layout.
- **Everything shared lives on disk.** Holders, waiters and uncommitted writes are files in the store, and history is in git. So any process can read a log, claim it, or wait on it, and a process that dies leaves nothing that the others must clean up by hand.
