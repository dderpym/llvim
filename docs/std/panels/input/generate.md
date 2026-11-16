# `std/panels/input/generate.py`: /continue

`/continue` asks the model to go on from the log as it is, without a new message. It queues a `GENERATE` cue
([cues.md](../../cues.md)) in the bar's queue, with the messages ([bar.md](bar.md)).

```python
Input(commands=[*STANDARD]).run()     # STANDARD has CONTINUE
```

- The log is empty: it says so, and queues nothing.
- Otherwise: `cue_the_model` is queued. Once the turn in progress is over, it commits the cue.
- `cue_the_model(log)`, async: the queued work, `after_turn` writing one cue.

## Using it

- Typed while the model works, it waits for the turn like a message, in the order typed. Ctrl-C forces it in with the rest of the queue.

## Why it is this way

- **Queued, not refused.** It used to say "busy" while anything held the log, so it had to be typed again at the right moment. In
  the queue it is one more thing the user asked for, done in turn.
- **The cue is the whole command.** The model answers cues, not messages, so going on is one cue, with nothing written for it to read.
