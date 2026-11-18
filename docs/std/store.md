# `std/store.py`: Store, Scan, Left, Unsteady

A `Store` moves files between any folder on disk and git trees in a log's repo. It knows nothing of the log's head: a tree it makes goes into a commit only through `Writer.put_tree` ([writer.md](../core/writer.md)), and a tree it writes out comes from wherever the caller found it (`Log.tree`, [log.md](../core/log.md)).

```python
store = Store(log)
scan = await store.scan(folder, against=last_tree, cache="project")   # cheap when little changed
if scan.changed:
    tree = await store.capture(folder, scan)                           # Unsteady if a file moved meanwhile
    async with await log.claim(Request(0)) as writer:
        writer.put_tree("project", tree)
        await writer.commit()

left = await store.checkout(old_tree, folder)                          # rewind the folder
```

- `scan(dir, against, cache, excludes=())`, async: a `Scan` of the folder.
  - `files`: every file (or link) that is not ignored and not inside a nested repo, with its size;
  - `changed`: those that differ from the tree `against`, in content or mode, or are not in it; `against=None`: all of them;
  - `repos`: the nested git repos found, as `"path/"`. Nothing inside one is listed.
  - An unknown `against` or a bad cache name (empty, with `/`, starting with `.`) raises `ValueError`; a `dir` that is not a folder, `NotADirectoryError`.
- `capture(dir, scan, leave=())`, async: the tree id of the scanned files but `leave`, or `None` if there are none.
  - A file that changed since the scan or while it was read: raises `Unsteady`, whose `paths` names them. No tree is made.
- `add(tree, changes)`, async: `tree` (or nothing) with `changes` made in order, a path each: `bytes` is the content, a `Path` is that file as capture would store it (a link as a link, `100755` if its owner may run it), `None` removes the file or folder there. `None` if nothing is left.
- `checkout(tree, dir, leave=(), scan=None)`, async: makes `dir` hold `tree` (`None`: no files), and returns `Left`:
  - a scanned file not in `tree` is deleted, and so is any folder that leaves empty;
  - a file whose content or mode differs is written; one already right is not touched;
  - `blocked`: not written because a real folder stands at the path, or a file, a link or a repo stands above it;
  - `ignored`: not written because a file there is ignored now, so it was never captured as it is;
  - `Left` is false when both are empty.
- `leave` is paths not touched at all: not captured, written or deleted. A path ending in `/` is a folder.
- `excludes` are ignore patterns on top of every `.gitignore` in `dir` and `dir/.git/info/exclude`. A file `dir`'s own repo tracks is never ignored.

## Using it

- Checkout destroys what it overwrites or deletes, uncaptured edits included. Capture first if they matter; the store does not guard them.
- Each call runs in a thread, since it reads and writes files. With 20,000 files (200 MB): a first scan reads them all, about 0.3 s; a scan with a warm cache takes 0.1 s, since it reads only files whose stat data changed; a capture stores what changed, about 2 s for all of it; a checkout that has nothing to write takes 0.02 s, and one into an empty folder about 2 s.
- A capture or checkout refuses a scan of another folder with `ValueError`. Hand capture a scan just taken: a file that changed since raises `Unsteady`, and one that appeared since is not captured.
- `Store(log)` uses the log's `write_blobs`, `blob`, `write_tree` and `read_tree` ([log.md](../core/log.md)), and its `dir`. Caches are `caches/<name>.json` in that folder. Deleting one costs only time.
- A file changed in the last two seconds is not cached, so it is read again by the next scan.
- `checkout` without a `scan` scans the folder itself, reading every file, and honours `.gitignore` but no `excludes`.

## Why it is this way

- **In std, not core.** Core knows the log: messages and files in commits, and who may write them. Which folder on disk a tree comes from or goes to is a use of the log, like a conversation is. The store reaches the log through four calls on objects (blobs in, blobs out, trees in, trees out), and a tree reaches a commit only through the Writer.
- **It runs no git.** Only core runs git, so there is one place that sets git up (the environment, no hooks, no user config) and knows the repo. Running git on a private index from here was tried and rejected: it was a second git runner with its own environment to keep safe. So the store walks the folder, reads ignore rules, and writes files itself.
- **No meaning in paths and no policy.** The store moves what it is told. Which folder is a project, what to leave out, how large a file may be, and when to capture are the caller's: core gives files no meaning, as it gives messages none.
- **A scan works out blob ids itself.** A git blob id is the SHA-1 of `blob <size>\0` and the content, so a scan hashes a file in Python and compares the id with the tree's. Finding what changed then stores nothing; only capture writes to the repo, and only what changed, in one batch.
- **The cache maps stat data to a blob id, whatever the tree.** A file whose mode, size, mtime, ctime and inode are what the cache holds has the id the cache holds, so it is not read. An entry belongs to the file, not to a tree, so a scan against any tree uses it. It is an optimization only: missing, stale or broken, it costs reading the files again. A file changed in the last two seconds is left out, since a second change within the same timestamp would leave its stat data the same.
- **The cache is written whole and moved in place.** Two scans of one cache never see half of the other's. The last one to finish wins, and either is correct.
- **A capture checks the files did not move under it.** A file half-written while it was read would be stored as if whole, and a rewind would bring back a broken file. Each file's stat data must be what the scan saw before and after storing, and each stored id must be the id the scan worked out. Otherwise it raises `Unsteady` and makes no tree. Blobs already stored stay in the repo, unreferenced, until `git gc`. The caller decides whether to wait and try again.
- **Ignore rules are git's, read here.** Each folder's `.gitignore` applies below it, a deeper one before a shallower one, `excludes` before both and `.git/info/exclude` after; within one, the last matching pattern decides. A pattern with a `/` is anchored to its folder, a trailing `/` matches folders only, `*` and `?` stop at `/`, `**` matches any number of folders, and `!` re-includes. An ignored folder is not entered, so nothing in it can be re-included, as in git. The user's global excludes are not read: what a project keeps should not depend on whose machine it is.
- **Nested repos are never entered.** A repo inside the folder has its own history, and its files are not this tree's to keep. A folder holding `.git` is reported as `path/` and not looked into.
- **The folder's own repo decides what is never ignored.** A file the user put in with `git add -f` is one they want kept, though its `.gitignore` matches. The store reads that repo's index file (versions 2 to 4) for the tracked paths. An index it cannot read, such as a split one, adds nothing, and the `.gitignore` rules alone decide.
- **Checkout leaves what it would destroy for good.** Writing a file where a folder stands, or under a file, link or repo, would mean deleting that first: an ignored file, a whole folder, a repo with its history. None of those was in the scan, so none was captured, and a rewind would lose it. The store leaves such paths and reports them in `Left`, and the caller decides.
- **A file ignored now is not overwritten.** The tree's copy is from when it was not ignored. The one on disk was never captured since, so it is newer, and overwriting it would lose it.
- **Files already right are not written.** Their times stay, so the next scan's cache still matches them and does not read them again; and an editor holding one open sees no change.
- **A file is written whole.** It is written to a scratch name beside it and moved over the old one, so a program reading it never sees half of it, and a link is replaced, not followed.
- **Empty folders are removed.** Deleting the files of a folder no tree had would leave the folder behind, and a rewind would not look like the tree it rewound to.
- **Content goes in and out as it is.** No line endings are converted and no `.gitattributes` filter runs, so a file comes back byte for byte.
