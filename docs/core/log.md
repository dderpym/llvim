# `core/log.py`: Log

A `Log` is a view of one log: a sequence of messages kept as a git branch. Anyone can read it and watch it change. To change it, claim a [Writer](writer.md). The log hands out one Writer at a time, by priority and then by arrival.

```python
log = Log("/home/me/code/myproject")        # the log "main" of the project
async with await log.claim(Request(priority=0, data="me"), timeout=5) as writer:
    writer.append(b"hello")
    await writer.commit()
async for snapshot in log.changes():        # now, then after every change
    show(snapshot.messages, snapshot.uncommitted, snapshot.removed)
```

`log.py` is the public face of core. It puts together the four modules under it: [git.py](git.md) (the repo), [live.py](live.md) (uncommitted writes), [queue.py](queue.md) (claims) and [watch.py](watch.md) (file events). A caller imports everything from `llvim.core` ([core.md](core.md)), not from these files.

> **`claim` is awaited, then entered:** `async with await log.claim(request) as writer`. Leaving out the `await` (`async with log.claim(request)`) fails at once with `TypeError: 'coroutine' object does not support the asynchronous context manager protocol`.

- `Log(project, name="main", *, repo=None, bucket=500)`:
  - `project` is the project's folder. A relative path is taken from the working folder.
  - `repo` is where the project's git repo is kept. By default it is in the store, under the project's flattened path.
  - `bucket` is how many messages share one folder in a commit ([git.md](git.md)).
  - A bad log name, or the root folder as the project, raises `ValueError`. The log need not exist; an unwritten log is empty. A repo git cannot make raises `GitError`.
- `head()`: the latest commit, or `None` for an empty log.
- `read(at)`, a `Snapshot` of `head`, `messages`, `uncommitted` and `removed`:
  - no `at`: the head plus the holder's uncommitted writes ([live.md](live.md));
  - a commit: exactly what it holds, with nothing uncommitted. An unknown commit raises `ValueError`.
- `changes()`, async: an iterator of snapshots, the first at once, then one each time the log may have changed.
- `claim(request, timeout=None)`, async: the Writer, once it is your turn. `async with` the Writer releases it on leaving.
  - Not your turn within `timeout` seconds: raises `TimeoutError`, and you leave the queue.
  - `timeout=0`: the log only if it is yours at once.
  - Cancelled: you leave the queue.
- `holder()`: the request of whoever holds the log, or `None`.
- `queue()`: the holder's request first, then the waiters', in the order they will get the log.
- `fork(name, at)`, async: a new log starting at `at` (default: the head). Raises `FileExistsError` if `name` already has commits, `ValueError` if there is nothing to start from, and `GitError` if git would not make the branch for another reason.

## Using it

- The store is `$LLVIM_STORE`, else `~/.llvim/sessions`. A project is one bare git repo, and a log is the branch `refs/heads/<name>` in it. A new session is a new name: its log starts empty.
- The repo of `/home/stoler/Documents/a` is `home-stoler-Documents-a` in the store. In each part of the path, `%` becomes `%25` and `-` becomes `%2D` before the parts are joined with `-`.
- `changes()` may give a snapshot that equals the last one: something changed that a snapshot does not show, such as a new waiter. Ask `holder()` or `queue()` then.
- Close a `changes()` iterator you stop early (`contextlib.aclosing`, or `aclose()`), or it keeps its inotify instance until it is garbage collected ([watch.md](watch.md)). Each running `changes()` and `claim` holds one, and works only on Linux.
- `claim`, `changes`, `fork` and `Writer.commit` need a running event loop; the rest are plain calls.
- Each `Log` keeps a cache, and runs one `git cat-file` process from its first read until it is garbage collected. The first read after a commit fetches only the buckets that commit changed ([git.md](git.md)). A streaming read costs a directory listing and the journal bytes written since the last read ([live.md](live.md)). `read(at)` of an old commit replaces the cache, so the next read of the head fetches again what differs.
- Tasks and threads may share a `Log`. Each `changes()` has its own watch, so two of them never take each other's wake-ups.

## Why it is this way

- **Async where it waits on something outside the process.** Claiming waits on other claimants, watching waits on file events, and committing and forking wait on git. Those are async, so a program can race them against its own input: a viewer waits on the keyboard and the log in one `asyncio.wait`, and a provider can stream a reply while it watches for someone who outranks it. Reading, the Writer's edits and `release` work from memory and local files in well under a millisecond, so they stay plain calls. A sync API that also handed out the inotify file descriptor was rejected: it put inotify outside core.
- **`claim` is a plain `async def`; the Writer is its own context manager.** So `claim` is an ordinary coroutine that `asyncio.create_task` takes, and the Writer releases itself on leaving `async with`. An object that is both awaitable and a context manager would save the `await` in `async with await`. But `create_task` only takes a coroutine, so that object must implement `send`, `throw` and `close` by hand. That is a hand-written coroutine class, to save one word. Forgetting the `await` is not silent: it fails on that line.
- **Changes come as snapshots, not as wake-ups.** `changes()` makes its watch before its first read. So a change made between two snapshots always brings another one. With a separate `wait()`, every caller had to read, then wait, and rely on events having queued in between. Changes that pile up while the consumer is busy come as one snapshot, which is what a screen wants.
- **A timeout is a claim's own.** Only `claim` can take its ticket back out of the queue. A caller that gave up on its own, by checking `holder()` first or by abandoning a waiting thread, either raced another claimant or left its ticket queued: it kept outranking others, made the holder's `outranked()` true, and finally took the log for nothing. Timing out or cancelling runs the same cleanup as any error in `claim`.
- **One git repo per project, one branch per log.** Forking is then making a ref, and every commit of every log can be read with `read(at)`. History is kept the git way, with nothing of our own to keep consistent with it.
- **The store holds a project under its whole path, flattened.** Every repo is one folder directly in the store, so `ls` shows every project. Nested folders that mirror the path were rejected: they are deep to browse, and one project's repo can sit inside another's folders. Escaping `-` and `%` keeps the name unique: `/a-b/c` is `a%2Db-c` and `/a/b-c` is `a-b%2Dc`. Otherwise both would be `a-b-c`.
- **A fork that fails says why.** `FileExistsError` only if the branch is there after git refused; otherwise git's own error as `GitError`, for the same reason as a commit ([git.md](git.md)).
- **Reads are cached, because readers read on every change.** A viewer reads on every streamed chunk. Without a cache that is three git processes and every message, every time: 58 ms at 5,000 messages. The log keeps the last commit it read ([git.md](git.md)) and the live view on top of the head ([live.md](live.md)). The head is read from the ref file, not from a git process. The cache is best effort: whenever the head, the holder or the journal file differs, the view is rebuilt from the commit.
