# `core/live.py`: Message, Snapshot, the journal, View

The holder's uncommitted writes, as a journal file that readers in any process can follow. `View` is the head with a journal applied, kept between reads.

```python
journal.write(record(b"B", 0, head.encode()) + record(b"S", 0, b"hello"))
view = View(head, identity, contents_of_head)
view.take(new_journal_bytes, contents_at)  # applies only the records it has not seen
view.snapshot()                            # Snapshot(head, messages, uncommitted, removed)
```

- `Message(id, content)`, `Snapshot(head, messages, uncommitted=(), removed=())`: what a read gives ([log.md](log.md)).
  - `uncommitted`: the messages that are new or differ from the head;
  - `removed`: the head's messages that the writes removed, as the head has them.
- `record(op, id, payload)`: one journal record. The ops are:
  - `B`: the commit the journal was written on top of (empty: none). It is the first record;
  - `S`: set a message; `E`: add to the end of one; `D`: remove one;
  - `R`: make the messages those of the commit in the payload (and the files too, for the Writer);
  - `F`, `T` (`FILE_OPS`): a file or a folder put under `files/` ([writer.md](writer.md)). The payload is the path, a NUL, and the object's id, which is empty for a removal. The id is 0.
- `records(journal)`: the whole records in some bytes. A record still being written is left out.
- `apply(messages, op, id, payload, contents_at)`: one record applied to a dict of messages.
- `View.take(data, contents_at)`: applies the records in `data`, which starts at `offset`.

## Using it

- A read of a streaming log costs the journal bytes written since the last read, and compares only the ids the journal touched with the head.
- After a read finds nothing new, `snapshot()` returns the same object.

## Why it is this way

- **Uncommitted writes are in a journal on disk.** That is how a reader in another process sees a reply as it streams. The journal starts with the commit it was written on top of. A reader applies it only if that commit is still the head. Otherwise the holder has just committed (and the head already holds the writes) or someone moved the head. Either way the head alone is right. The journal is read before the head, so a reader that loses this race sees a newer state, never an older one.
- **The journal of a dead holder is ignored, then deleted.** A reader only reads the journal of a `held.…` file whose lock is held ([queue.md](queue.md)).
- **`uncommitted` and `removed` compare with the head; they do not list the writes.** A reader wants to know how the log differs from its last commit, not how the holder got there. So an append that is removed again shows as nothing, a replace with the same content shows as nothing, and a restore shows as the messages it changes and removes. A removed message keeps the content the head has, so a viewer can still show what is going.
- **The Writer and readers apply the journal with the same code.** Both use `apply`, so what readers show before a commit and what the commit holds cannot disagree.
- **A view keeps what it worked out.** The journal's offset, the messages with the journal applied, the ordered list, and the ids the journal touched. Setting or extending a message, or appending one after the last, patches the ordered list in place, so a streamed chunk costs little. Any other change rebuilds it on the next snapshot.
- **File changes are in the journal, but readers skip them.** The Writer records them there so its journal holds everything it would commit. Readers show messages only; reading files is of commits ([log.md](log.md)), so `View.take` passes over `F` and `T`. Content is not in the record: the Writer stores it in the repo when it is put, and the record names it by id.
- **It is given `contents_at`, not a log.** A restore record needs another commit's messages. Taking a function keeps live.py free of git and of `Log`, so it is tested on plain dicts.
