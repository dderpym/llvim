# `core/git.py`: GitError, Author, commit, Tree, repack

The repo of a project, and the only code that runs git or knows how a log is laid out in it. [log.md](log.md) calls it; nothing else does.

```python
git.init(repo)
where = {}                                  # the bucket of each message, kept by the caller
commit = await git.commit(repo, "refs/heads/main", None, {0: b"hello"}, 1, where, 500, LLVIM, "")
tree = git.Tree.read(git.Objects(repo), commit, None)
tree.contents                               # {0: b"hello"}
```

- `GitError`: git failed or refused. The message ends with git's own, which is also in `stderr`.
- `Author(name, email="")`: who a commit says wrote it. A name that is empty, or a name or email that git cannot record (`<`, `>`, a line break, a NUL), raises `ValueError`. `LLVIM` is the default author, and every commit's committer.
- `init(repo)`: makes a bare repo if there is none. Raises `GitError` if git cannot.
- `target(repo, ref)`: the commit a ref points at, or `None`.
- `commit(repo, ref, base, changes, next_id, where, bucket, author, message)`, async:
  - `ref` still at `base`: a new commit with `changes` (`None` for a removed message), and `ref` moves to it;
  - `ref` moved: `None`. The ref is untouched;
  - git would not make the commit or move the ref for another reason (a lock file left by a git that died, a full disk): raises `GitError`. The ref is untouched.
- `move(repo, ref, to, start)`, async: points `ref` at `to` if it is still at `start` (`None`: if it does not exist). Raises `GitError` otherwise.
- `Objects(repo).get(name)`: the id and content of an object, through one running `git cat-file --batch`.
- `Tree.read(objects, commit, last)`: a commit's messages, the bucket of each, and its next free id. Pass the last tree read to reuse what did not change.
- `repack(repo)`: drops old scratch refs and merges packs. A commit runs it in a background thread when the repo is untidy.

## Using it

- A commit costs two git processes (`fast-import` and `update-ref`), about 6 ms whatever the log's length.
- A commit that finds more than `PACKS` (50) packs, or about `LOOSE` (6,700) loose objects, starts `repack` in a background thread. The commit does not wait for it, and only one repack runs at a time.
- `where` is changed in place by a successful commit. The caller keeps it between commits; that is what makes a commit cost the same however long the log is.

## Why it is this way

- **A commit holds `messages/<bucket>/<id>` and `next`.** One blob per message, so a commit stores only the messages that changed. Messages are grouped in buckets of `bucket` ids, named by their first id (`messages/500/512`). Git rewrites every tree on the path of a changed file, so with one flat folder a commit would rewrite a tree with an entry for every message, and writing would get slower as the log grew. With buckets it rewrites one bucket and the short list of buckets.
- **The bucket size can change.** A message stays in the bucket it was first written to. Only new messages use the current size, and reading never computes a bucket, it lists them. So logs written with different sizes, or with several sizes, read and write correctly.
- **`next` is the next free id.** It is kept so that an id is never reused, even after its message is removed. Ids are not taken from the message count, because a remove would then give the same id to two messages.
- **A tree is read bucket by bucket.** A bucket whose git tree did not change since the last read is reused without asking git, and inside a changed bucket a message whose blob did not change is reused.
- **A commit moves the ref only if nothing else moved it.** The commit is built on a scratch ref. The branch moves in one `update-ref` transaction that checks the branch still points at the commit the writes started from, and deletes the scratch ref. Holding the claim does not stop raw git, or another program, from moving the branch. Overwriting would silently drop its commit. When `update-ref` fails, the ref is read again: `None` only if it really is somewhere else, and otherwise git's own error. Taking every failure for a race would send a writer to release and claim again over a stale `main.lock`, which a new claim does not remove, so every commit after it would fail the same way. `fast-import` was not allowed to move the branch itself: it only refuses moves that are not fast-forward, so it would accept a branch moved backwards.
- **Old scratch refs are dropped when repacking.** A process that dies between `fast-import` and `update-ref` leaves its scratch ref, which would keep its commit forever. `repack` deletes scratch refs whose commit is older than `SCRATCH_AGE` (an hour), each only if it still points at that commit. A younger one may belong to a commit still running. Their objects become unreachable; llvim does not prune them itself, because pruning walks the whole repo. `git gc` frees them.
- **`Author` refuses what git would choke on.** fast-import ends a name at `<`, an email at `>`, and a header at a line break; a NUL ends it early. Each would make a bad commit or fail it, so they are refused when the `Author` is made, where the caller sees it, not later inside a commit.
- **One `GitError` for every failure of git.** A caller catches one type whatever git was doing: making the repo, writing the commit, or moving a ref. Letting `CalledProcessError` through was rejected: it names git's internals, and a caller could not tell it from a failure of some other program. Races are not `GitError`: a moved ref is `None` here, and `Moved` or `FileExistsError` above.
- **Git runs with llvim's settings only.** Every git process gets an environment with none of the user's `GIT_` variables, no global or system config, and `SETTINGS` passed in by `GIT_CONFIG_COUNT`. A repo is made with no templates. Without this, a `core.hooksPath` or `init.templateDir` in the user's config would run their hooks on every commit: `update-ref` runs `reference-transaction`, and a failing hook fails the commit. A `GIT_DIR` left by a hook llvim was started from would point every command at another repo, and `GIT_NAMESPACE` would hide the log's branches. The settings travel in the environment, not in the repo's config file, so repos made before a setting existed get it too.
- **The committer is always llvim; the author is the caller's.** In git the committer is who made the commit and the author is who wrote what is in it, and that is the split here: the program that writes the log says who it writes for (a model, a user), and llvim made the commit. The message is the caller's too, since only it knows what the content means.
- **The repo is tidied as it grows.** fast-import leaves a pack for every commit, or loose objects for a small one, and nothing ever merges them. After a few thousand commits, every object lookup would search thousands of packs or files, and file handles would pile up. So a commit that finds too many starts a repack. `--geometric=2` merges small packs into larger ones and takes in the loose objects. Each object is rewritten a few times over the log's life, where `-a` would rewrite the whole repo every time. The thresholds are git's own `gc.autoPackLimit` and `gc.auto`, estimated the way `git gc --auto` does it. Running `git gc --auto` itself was rejected: it is a process on every commit, and its full repack rewrites everything.
- **One `fast-import` per commit.** It takes every changed message inline in one process. `hash-object`, `mktree` and `commit-tree` would take one process per changed message and two more for the trees.
- **A running `git cat-file --batch` instead of a process per read.** Reading a commit means reading its tree, the bucket list, the changed buckets and the changed blobs, one after the other. As separate processes that is several milliseconds; through one long-running process it is a pipe round trip each.
