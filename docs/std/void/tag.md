# `std/void/tag.py`: VOID, is_void, marked, unmarked

The void tag: `"void"`, added after a message's other tags. `["assistant"]` becomes `["assistant", "void"]`.

```python
writer.replace(id, marked(message.content, True))    # void it
writer.replace(id, marked(message.content, False))   # put it back
is_void(entry), unmarked(entry).tags
```

- `is_void(entry)`: it has the tag.
- `marked(content, void)`: the message's bytes with the tag put on or taken off. `None` if that changes nothing, or if the message
  is in no format that has tags ([conversation.md](../conversation.md)).
- `unmarked(entry)`: the entry without the tag, for asking what kind of message it was. An entry that is not voided is returned
  as it is.

## Why it is this way

- **A tag at the end.** The first tag still says what the message is, so a program that was not told about void reads it as
  before. Programs that match tags exactly, as cues do, stop matching, which is what voiding a cue should do.
- **The text is not touched.** `marked` rewrites the header line and keeps the bytes after it, so a message whose text is not
  valid UTF-8 survives being voided and restored unchanged.
- **Restoring gives back the same bytes.** Taking the tag off leaves the header as `encode` wrote it, so a void and a restore
  leave the message equal to what it was.
