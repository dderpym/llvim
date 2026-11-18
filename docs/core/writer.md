# `core/writer.py`: Writer, Moved, Released, Committing

A `Writer` is the only way to change a log, its messages and its files. You get it from `Log.claim` ([log.md](log.md)) and keep it until you release it. Writes are uncommitted until `commit()`, and readers see them as they happen.

```python
async with await log.claim(Request(0)) as writer:
    id = writer.append(b"")
    async for chunk in reply:
        writer.extend(id, chunk)       # readers see the reply grow
        if writer.outranked():         # or await writer.outranked_changed() alongside the reply
            break
    await writer.commit(author=Author("gpt-5", "model@example.com"), message="reply")

async with await log.claim(Request(0)) as writer:
    writer.put("notes/today", b"...")                    # one file
    writer.put_tree("snapshot", tree)                    # a whole folder, e.g. from std/store.py
    await writer.commit()
```

- `append(content)`: adds a message after the last one and returns its id.
- `extend(id, chunk)`, `replace(id, content)`, `remove(id)`: a missing id raises `KeyError`.
- `put(path, data)`: sets the file at `path` under `files/` to `data` in the next commit; `None` removes the file or folder there. A bad path raises `ValueError`.
- `put_tree(path, tree)`: sets the folder at `path` (`""`: all of `files/`) to `tree`; `None` removes it. A tree the repo lacks raises `ValueError`.
  - A later put to a path replaces an earlier uncommitted one there and under it;
  - a put inside a folder given to `put_tree` lands on top of that tree.
- `restore(to)`: makes the log look like commit `to` again, messages and files, as an uncommitted change on top. An unknown commit raises `ValueError`; while a commit runs, `Committing`.
- `commit(*, author=LLVIM, message="")`, async: the commit says `author` wrote it, with `message`;
  - writes since the last commit: a new commit, which becomes the head;
  - nothing new: the head, unchanged, whatever the author and message. A put file is something new, even with no message written;
  - an empty log: a first commit, even with no writes;
  - something else moved the head: raises `Moved`. The head is untouched and the writes stay uncommitted;
  - git would not commit or move the head for another reason (a lock file left by a git that died, a full disk): raises `GitError` ([git.md](git.md)). The head is untouched, the writes stay uncommitted, and the commit can be tried again once the cause is gone;
  - while another commit of this Writer runs: raises `Committing`;
  - cancelled: waits for git to finish, keeps what it did, then raises `CancelledError`. If git made the commit, it is the head and the Writer goes on from it; if not, the writes stay uncommitted.
- `outranked()`: `True` if someone waiting has a higher priority.
- `outranked_changed()`, async: returns once `outranked()` may have changed since the last call. The first call returns at once.
- `offer()`: an `Offer` of the log, still held, to another process ([handoff.md](handoff.md)). Give that process
  `offer.address` and `await offer.taken(timeout)`. Once it is taken this Writer is released: the other process holds the same
  claim, and what was uncommitted here is discarded. Not taken in time: `TimeoutError`, and this Writer still holds the log.
- `release()`, or leaving `async with`: gives up the log and discards what is uncommitted. Releasing twice does nothing. A released Writer raises `Released` on any write or commit.

## Using it

- `put` stores the content in the repo at once, one git process (about 1 ms), so a commit holds only ids. Content of a put that is never committed stays in the repo until `git gc`. Readers see a put only once it is committed ([log.md](log.md)).
- A Writer that is never released holds the log until its process exits or the Writer is garbage collected. Use `async with await log.claim(...)`.
- Other tasks may go on writing while a commit runs. Those writes are not in the commit; they stay uncommitted, and readers go on seeing them. Puts too: they go in the next commit, and if the commit fails, they stay on top of the puts it was carrying. `restore` is refused while a commit runs, since it would change what the commit is writing.
- Each write is one write to the journal file. It costs no git process, so streaming chunk by chunk is cheap. A commit costs two git processes (`fast-import` and `update-ref`), about 6 ms whatever the log's length. A restore reads the commit it restores, and is linear in its length.
- After `Moved`, every later commit of that Writer fails too. Release it and claim again.
- `outranked_changed()` may return when nothing that matters changed (a waiter of lower priority joined): look at `outranked()`
  after it. Cancel a pending one before releasing; release closes what it waits on.

## Why it is this way

- **Uncommitted, not autosaved.** A reply that is cut off, or whose process dies, leaves no half-message in history. A commit is a point the caller chose.
- **A put is stored when it is made, not when it is committed.** A large file would otherwise sit in the Writer's memory until the commit, and then again in fast-import's input. Stored at once, the Writer and its journal keep an id.
- **Puts are kept in order, one per path.** A later put at a path drops the earlier ones at and under it, since it would overwrite them. What is left is applied in order, so a file put inside a `put_tree` folder lands on top of it: a caller can put a captured tree and then change one file in it, without building a new tree.
- **Puts are not refused while a commit runs.** For the same reason as messages (below): a caller putting files in one task must not stop for a commit in another. `put` checks only that the Writer is held.
- **Restore adds a commit, it does not reset.** The commits after `to` stay in history, so a restore can be undone by another restore. The next id is kept as the highest seen, so ids from the undone commits are not given out again. The files come back too, as one change of all of `files/`, or none if they are the same.
- **The Writer never touches git.** It keeps the state it is building (the messages, which ones changed since the last commit, and the bucket of each committed message) and hands a commit to `Log`, which has [git.py](git.md) write it. Git in one file means one place that knows the on-disk format.
- **A commit costs the same however long the log is.** The Writer keeps the set of changed ids, so a commit compares nothing it did not change. It keeps the bucket of every message, so the log does not read the base commit's trees to find them.
- **A cancelled commit finishes the git step.** Cancelling the wait does not stop git: an `update-ref` already running moves the head anyway. A Writer that gave up on it would not know the head moved, and every later commit would fail with `Moved`. So the commit waits for git, a few milliseconds, and records where the head ended. Killing git on cancel was rejected: the ref may already be moved by then, and the Writer would still have to find out which.
- **Writes during a commit are carried over, not refused.** A provider streams in one task and commits in another, so refusing writes during the few milliseconds of a commit would make it stop and wait. The commit takes the changed ids when it starts. When it ends, the ids changed since then are written into the fresh journal as they stand against the new head, so readers never lose them.
- **The Writer and readers apply the journal with the same code.** Both use `apply` from [live.py](live.md), so what readers show before a commit and what the commit holds cannot disagree.
- **`outranked_changed` is a wait, not a callback.** A holder waits on it alongside its own work, with
  `asyncio.wait(..., FIRST_COMPLETED)`, so it can stop at once even while that work is blocked. It is the queue's `Wake`
  ([queue.md](queue.md)) on `ticket.` files, made on the first call and kept until release, so a waiter that joins between two
  calls is not missed. Making it in the constructor was rejected: every Writer would hold an inotify descriptor and a thread whether
  it looks or not. A polling `outranked()` on a timer was rejected: it is late by the period and reads the queue's folder each time.
- **A claim can change hands, not only be given up.** A program sometimes waits for the log for another: the input bar queues
  for it, and the picker it then opens is a different process. Releasing for the other to claim lets whoever waits first take the
  log in between. `offer` keeps the log held across the hand-over.
- **Errors a caller handles have their own type.** `Moved` means claim again on top of the new head, `GitError` means fix the cause and commit again, `Committing` means wait for the running commit, and `Released` is a bug in the caller. Each is caught by its type, not by matching a message.
