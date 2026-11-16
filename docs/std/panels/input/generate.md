# `std/panels/input/generate.py`: /continue

`/continue` asks the model to go on from the log as it is, without a new message: it commits a `GENERATE` cue
([cues.md](../../cues.md)).

```python
Input(commands=[*STANDARD]).run()     # STANDARD has CONTINUE
```

- The log is held (a reply is streaming): it says "busy" and does nothing.
- The log is empty: it says so.
- The last message is already a cue: nothing is added.

## Why it is this way

- **It does not wait for the log.** Something holding the log is most likely a reply, which would overtake the cue as soon as it
  commits. So it claims with `timeout=0` and says busy instead.
- **The cue is the whole command.** The model answers cues, not messages, so going on is one cue, with nothing written for it to read.
