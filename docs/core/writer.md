# `core/writer.py`: Writer, Moved, Released, Committing

A `Writer` is the only way to change a log. You get it from `Log.claim` ([log.md](log.md)) and keep it until you release it. Writes are uncommitted until `commit()`, and readers see them as they happen.

```python
async with await log.claim(Request(0)) as writer:
    id = writer.append(b"")
    async for chunk in reply:
        writer.extend(id, chunk)       # readers see the reply grow
        if writer.outranked():
            break
    await writer.commit(author=Author("gpt-5", "model@example.com"), message="reply")
```

- `append(content)`: adds a message after the last one and returns its id.
- `extend(id, chunk)`, `replace(id, content)`, `remove(id)`: a missing id raises `KeyError`.
- `restore(to)`: makes the log look like commit `to` again, as an uncommitted change on top. An unknown commit raises `ValueError`; while a commit runs, `Committing`.
- `commit(*, author=LLVIM, message="")`, async: the commit says `author` wrote it, with `message`;
  - writes since the last commit: a new commit, which becomes the head;
  - nothing new: the head, unchanged, whatever the author and message;
  - an empty log: a first commit, even with no writes;
  - something else moved the head: raises `Moved`. The head is untouched and the writes stay uncommitted;
  - git would not commit or move the head for another reason (a lock file left by a git that died, a full disk): raises `GitError` ([git.md](git.md)). The head is untouched, the writes stay uncommitted, and the commit can be tried again once the cause is gone;
  - while another commit of this Writer runs: raises `Committing`.
- `outranked()`: `True` if someone waiting has a higher priority.
- `release()`, or leaving `async with`: gives up the log and discards what is uncommitted. Releasing twice does nothing. A released Writer raises `Released` on any write or commit.

## Using it

- A Writer that is never released holds the log until its process exits or the Writer is garbage collected. Use `async with await log.claim(...)`.
- Other tasks may go on writing while a commit runs. Those writes are not in the commit; they stay uncommitted, and readers go on seeing them. `restore` is refused while a commit runs, since it would change what the commit is writing.
- Each write is one write to the journal file. It costs no git process, so streaming chunk by chunk is cheap. A commit costs two git processes (`fast-import` and `update-ref`), about 6 ms whatever the log's length. A restore reads the commit it restores, and is linear in its length.
- After `Moved`, every later commit of that Writer fails too. Release it and claim again.

## Why it is this way

- **Uncommitted, not autosaved.** A reply that is cut off, or whose process dies, leaves no half-message in history. A commit is a point the caller chose.
- **Restore adds a commit, it does not reset.** The commits after `to` stay in history, so a restore can be undone by another restore. The next id is kept as the highest seen, so ids from the undone commits are not given out again.
- **The Writer never touches git.** It keeps the state it is building (the messages, which ones changed since the last commit, and the bucket of each committed message) and hands a commit to `Log`, which has [git.py](git.md) write it. Git in one file means one place that knows the on-disk format.
- **A commit costs the same however long the log is.** The Writer keeps the set of changed ids, so a commit compares nothing it did not change. It keeps the bucket of every message, so the log does not read the base commit's trees to find them.
- **Writes during a commit are carried over, not refused.** A provider streams in one task and commits in another, so refusing writes during the few milliseconds of a commit would make it stop and wait. The commit takes the changed ids when it starts. When it ends, the ids changed since then are written into the fresh journal as they stand against the new head, so readers never lose them.
- **The Writer and readers apply the journal with the same code.** Both use `apply` from [live.py](live.md), so what readers show before a commit and what the commit holds cannot disagree.
- **Errors a caller handles have their own type.** `Moved` means claim again on top of the new head, `GitError` means fix the cause and commit again, `Committing` means wait for the running commit, and `Released` is a bug in the caller. Each is caught by its type, not by matching a message.
