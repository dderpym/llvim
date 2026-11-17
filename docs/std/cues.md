# `std/cues.py`: send, receive, take, take_turn, is_cue

A cue is a message that asks whoever listens on its channel to act. It is wanted while it is the last message of the log. Every
program sends, receives and checks cues through this file, and none knows what a cue looks like on disk.

```python
async with await cues.take_turn(log, Request(0)) as writer:     # the bar: once the turn is over
    writer.append(encode([Tag.USER], "hi"))
    cues.send(writer, GENERATE)                                  # the model should answer this
    await writer.commit()

async for writer in cues.receive(log, GENERATE, Request(0)):     # the provider: each time it is cued, the log held
    ...                                                          # answer, commit; released after the body
```

- Sending: `send(writer, on)`: appends a cue on channel `on`; it goes in with the writer's next commit. Its id.
- Receiving:
  - `receive(log, on, request)`, async iterator: each time `on` is cued, the log claimed with `request` and still cued once held.
    It is released when the loop body is done; a cue overtaken while it waited for the log is skipped.
  - `take(log, on, request)`, async: the same once, now: the held writer, or `None` (nothing held) if `on` is not cued or was
    overtaken by the time the log was free.
- Checking: `is_cue(entry, on=None)`: a cue, or a cue on `on`. `channel(entry)`: its channel, or `None`. `cued(snapshot)`: the
  channel of the last message, if it is a cue.
- The turn: `busy(log)`: someone holds the log, or a cue is last. `take_turn(log, request)`, async: the log once the whole turn is
  over, with no cue left once it is held; it waits again if one was left while it waited.
- `GENERATE` (`"generate"`): a model should write the next message.
- `TOOLS` (`"tools"`): the tool calls without a result should be run. The provider sends it with a reply that made calls, and
  `/bash` with yours; the [runner](tools/runner.md) answers it.

## Using it

- On disk a cue is `["cue", <channel>]` with no text ([conversation.md](conversation.md)). Nothing outside this file should build or
  match that: a program that does would disagree with the others as soon as the shape changes.
- Nothing removes a cue. Whatever is written after it overtakes it: the reply, an error, a stop. So a listener that fails writes its
  failure, and is not asked again until there is a new cue.
- `cued` decodes one message, so checking it on every change costs the same however long the log is.

## Why it is this way

- **One place says what a cue is.** Programs used to check the tags themselves, and the viewer's check (the first tag) and the
  status bar's (exactly two tags) disagreed about a message like `["cue"]`. Now a program says "send a cue on this channel" and
  "act on each cue on this channel", and the format, the claiming and the checking again live once.
- **Cues are messages.** As a file beside the log, a cue and what it asks about could be seen apart. As a message it is committed
  with them in one commit, and restored and forked with the log.
- **Wanted while last, not by whom.** A cue asks for the next message. Anything written after it means someone acted, so there is
  no "consumed" mark to keep in step, and two listeners never both answer.
- **Receiving checks the cue again once the log is held.** Waiting for the log takes time, and the cue may be answered meanwhile.
- **Waiting for the turn is not waiting for the holder.** A turn passes the log from program to program by cues: the model
  releases it with a cue for the tool runner, which only then claims. A claim made when the model let go would be first in the
  queue, ahead of the runner, and its calls would never run. So `take_turn` waits until nobody holds the log and no cue is last.
