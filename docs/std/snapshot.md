# `std/snapshot.py`: HOOK, choose, at, left_alone, BOX

The project folder, kept in the commit of each user message, so a later step can put the folder back as it was at any turn.
`HOOK` is an input bar hook ([bar.md](panels/input/bar.md)) that stages the folder under `files/project` in the commit that
holds the message; `at` reads back what a commit holds.

```python
Input(commands=STANDARD, hooks=[snapshot.HOOK]).run()       # each message sent takes a snapshot
Viewer(renderers=[void.BOX, snapshot.BOX]).run()            # shows what was skipped, and refusals

taken = snapshot.at(log, commit)                            # Taken(tree, skipped, refused), or None
keep_out = snapshot.left_alone(log, now, then)              # what a move between the two must not touch
```

- `HOOK(log, writer, text)`, async: scans `log.project` against the head's snapshot, stages the captured tree with
  `writer.put_tree("project", tree)` if it differs, and appends one `[snapshot]` record. Its result is the bar's:
  - taken: `["snapshot"]`, `skipped=[...]` (sorted); returns True;
  - refused by the size rules, or files kept changing over three tries: nothing is staged, `["snapshot", "error"]` with why and
    `refused=True`; returns False, so the model is not cued;
  - any other failure: the same record, "Not snapshotted: <error>"; returns True, so the turn goes on.
- `choose(scan, is_binary, first=False)`: a `Choice(skipped, refused)`, and nothing else is done. `is_binary(path)` is asked only
  of a file over 1 MB and not over 50 MB. Skipped, the snapshot is still taken:
  - a binary file over `BINARY_LIMIT` (1 MB); binary is a NUL in its first 8000 bytes, git's own test (`is_binary`);
  - any file over `TEXT_LIMIT` (50 MB);
  - a folder whose kept files add up to over `FOLDER_LIMIT` (1 GB), as `"folder/"`, deepest first;
  - every nested repo the scan found, as `"path/"`.
  Refused, naming the five largest files counted:
  - not `first`: the kept files in `scan.changed` add up to over `CHANGED_LIMIT` (100 MB);
  - `first`: all the kept files add up to over `FIRST_LIMIT` (2 GB).
- `at(log, commit)`: `Taken(tree, skipped, refused)` from the newest `[snapshot]` record at or before `commit`, or None if there
  is none. `tree` is `log.tree("project", at=commit)`. A refused turn has the previous snapshot's tree and skips, and
  `refused=True`.
- `left_alone(log, a, b)`: what the snapshot at `a` or at `b` skipped, as a set of paths (folders end in `/`).
- `BOX`: the viewer's renderer for records: nothing for a snapshot that kept everything, a grey line `snapshot skipped: a.bin,
  data/` for one that skipped something, and the reason, as an error, for a refused one.

## Using it

- The hook runs while the bar holds the log, so a send waits for the scan and the capture. A scan with a warm cache costs about
  0.1 s for 20,000 files; a first capture stores everything, about 2 s for 200 MB ([store.md](store.md)).
- `at` and `left_alone` read whole commits: call them for the turns being looked at, not for every turn of a long log.
- A move between two snapshots should leave alone `left_alone(...)`: a skipped path is in neither tree, so the tree says nothing
  about it, and writing the other tree there would delete what is on disk.
- A `Taken` with `refused=True` holds an older tree than the folder had then. Warn before moving to it.
- The constants at the top of the file are the limits. A start script that wants others can write its own hook around `choose`.

## Why it is this way

- **Policy here, mechanism in the store.** Core and [store.md](store.md) move files and know no limits. Which folder, what is too
  large, and what to do then are this file's, so another layout can take snapshots another way without touching either.
- **In the commit of the message.** The bar runs the hook after the message is appended and before the commit, so one commit holds
  both, and "the folder as of this message" is a single commit to read. A separate commit per snapshot was rejected: it would
  need its own claim and could land on the other side of a model's reply.
- **Records are messages; core knows nothing of them.** A record says what was skipped and whether the snapshot was refused,
  which the tree alone cannot say: a refused turn and an unchanged folder both leave the tree as it was. `at` reads the record,
  not the tree's history. The provider sends only the three roles ([openai.md](providers/openai.md)), so the model never sees one.
- **Large files are skipped, not refused.** A build output or a dataset should not stop a user from working, and keeping one
  every turn would fill the repo. Skipping it costs only that a rewind leaves it as it is, which `left_alone` says.
- **A large change is refused, not skipped.** 100 MB of changed files in one turn is usually something generated that belongs in
  `.gitignore`. Storing it silently would grow the repo for good; skipping it would leave a snapshot that quietly misses work. So
  the turn ends with the five largest named and what to do, and the message stays in the log.
- **A first snapshot has its own limit.** With no snapshot before it, every file is new, so the 100 MB rule would refuse any
  real project. `choose` is told `first` rather than guessing it from the scan: a later scan in which every file changed looks
  the same.
- **Deepest folder first.** Skipping the deepest folder over the limit keeps the most: its parents may then be under the limit
  and stay. Skipping the shallowest would throw away their small files with it.
- **Binary is read only when it matters.** A file of 1 MB or less is kept whatever it holds, and one over 50 MB is skipped
  whatever it holds, so only those between are opened, and only their first 8000 bytes.
- **Files that keep changing are tried three times, then refused.** A capture that sees a file move under it stores nothing
  ([store.md](store.md)); a log being written by a running program would fail every time. Three tries cover a save in progress,
  and then the user is told which files, rather than the turn waiting forever.
- **Any other failure lets the turn go on.** A broken snapshot (a folder gone, a disk error) must not stop the user from talking
  to the model. It is recorded as refused, so `at` does not claim the folder was kept.
- **One record per turn, and it is the only word on it.** A refusal is not also written as a plain `[error]`: the viewer would
  show it twice, and a reader would have two messages to reconcile.
