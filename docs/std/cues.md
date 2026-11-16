# `std/cues.py`: cue, cued, busy

A cue is a message that asks whoever listens on its channel to act. It is wanted while it is the last message of the log.

```python
writer.append(encode([Tag.USER], "hi"))
writer.append(cue(GENERATE))                 # the model should answer this
await writer.commit()
...
if cued(log.read()) == GENERATE:             # in the provider
    ...
```

- `cue(channel)`: the content of a cue message, `["cue", channel]` with no text.
- `channel(entry)`: the channel of a cue, or `None` for any other message.
- `cued(snapshot)`: the channel of the last message, if it is a cue; else `None`.
- `busy(log)`: the turn is not over: someone holds the log, or a cue is last.
- `GENERATE` (`"generate"`): a model should write the next message.

## Using it

- Nothing removes a cue. Whatever is written after it overtakes it: the reply, an error, a stop. So a listener that fails writes its
  failure, and is not asked again until there is a new cue.
- A listener checks `cued` again after it has claimed the log: something may have overtaken the cue while it waited.
- `cued` decodes one message, so checking it on every change costs the same however long the log is.

## Why it is this way

- **Cues are messages.** A cue was a file beside the log, with the commit it was for. As a message it is in history like anything
  else: committed with what it asks about in one commit, so there is no moment when one is there without the other; restored and
  forked with the log; and shown or hidden by a viewer like any message.
- **Wanted while last, not by whom.** A cue asks for the next message. Anything written after it means someone acted, so there is
  no "consumed" mark to keep in step, and two listeners never both answer.
- **Programs act on cues, not on what the last message is.** A user message nobody cued (one typed while the model was stopped) is
  not for the model to guess at.
