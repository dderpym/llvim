# `std/conversation.py`: Entry, Tag, Info

The message format the standard programs agree on. Core's messages are bytes; an `Entry` is one read as tags, fields and text.

```python
writer.append(encode([Tag.ASSISTANT], "Hel", model="gpt"))   # b'{"tags": ["assistant"], "model": "gpt"}\nHel'
writer.extend(id, b"lo")                                    # still valid: the text is now "Hello"
for entry in entries(log.read()):
    print(entry.tags, entry.content, entry.extra, entry.streaming)
```

- `encode(tags, content="", **extra)`: a JSON header line of the tags and fields, a line break, then the text.
- `decode(message, uncommitted=False, streaming=False)`: the `Entry`. A message in no known format is an entry with no tags,
  holding its bytes as text; it never raises.
- `entries(snapshot)`: every message of a snapshot. The ones in `snapshot.uncommitted` are `uncommitted`, and the last message, if
  uncommitted, is `streaming`.
- `Tag`: `system`, `user`, `assistant`, `thinking`, `status`, `error`, `stop`, `cue`, and `tool_call`, `tool_start`,
  `tool_result` ([calls.md](tools/calls.md)). `ROLES` are the three a chat message has.
- `Field`: the fields the standard programs write: `model`, and on tool calls `call_id`, `user` and `error`.
- `Info`: the keys of a claim's `data` (`provider`, `model`, `input`, `tools`), which say who holds or waits for the log.

## Using it

- A message's text may arrive in pieces, and a piece may split a character: `decode` replaces what is not UTF-8 rather than fail.
- `streaming` is a guess: "uncommitted, and last". A writer that appends a whole message and commits later shows it as streaming
  until then. Nothing more is known: core keeps no "finished" mark, and a viewer only needs the guess to leave a message open.

## Why it is this way

- **A header line, then the text.** A reply streams with `Writer.extend`, which adds bytes to the end of a message. A JSON object
  stops being JSON when bytes are added to it; a header and then text stays valid at every byte. Rejected: one message per chunk
  (the log fills with fragments), and replacing the whole message per chunk (each chunk costs the message's length).
- **Tags are any JSON values.** Core gives them no meaning, and a program may tag with more than a word (`["cue", "generate"]`).
- **Decoding never fails.** Any program can write to a log, so a viewer or a provider must survive a message it does not
  understand. It shows as untagged text and the provider leaves it out.
- **Closed sets of strings are `StrEnum`s.** Members are plain strings on disk, so another program needs nothing from llvim to
  write them, and a typo in Python fails at once.
