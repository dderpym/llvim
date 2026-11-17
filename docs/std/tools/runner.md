# `std/tools/runner.py`: Runner, llvim-tools

The runner answers the tool calls a provider left in the log. On a `tools` cue it claims the log. For each waiting call it commits a
start, runs the call through the [registry](registry.md), and writes the result. With the last result it cues the model.

```
llvim-tools                     # answer the calls in the log "main" of the working folder, with bash, until interrupted
llvim-tools alt -p ~/proj --once
```
```python
Runner(tools=[bash.TOOL, mine]).run()       # in a start script; the log is the session's
```

- `Runner(tools=(), log=None, once=False).run()`: the program. `llvim-tools` runs it with bash.
- `serve(log, registry)`, async: first `recover`, then each `tools` cue (`cues.receive`), until cancelled.
- `respond(log, registry)`, async: answers if the tools are cued now; how many calls it answered.
- `recover(log, registry)`, async: answers the calls a dead runner left cut off, if any, and then the rest of that turn.
- `run_calls(log, writer, registry)`, async: the work itself, with the log held:
  - calls that were [cut off](calls.md) are answered `[interrupted: the tool runner stopped while this call ran, so it was not run again]`;
  - each other waiting call, oldest first, gets a start, then a commit, then a run, then its result;
  - the last result is followed by a `generate` cue if any of the calls were the model's; one the user made (`/bash`) cues nobody;
  - outranked while a call runs: that call is answered and committed, the calls after it are left, and nobody is cued;
  - cued with no call waiting: an error message says so. That overtakes the cue, so the turn ends.

## Using it

- It claims at priority 0 ([cues.md](../cues.md)). The input bar's stop, at 100, outranks it. A message you send waits for the turn
  to end and does not stop a tool.
- Outranked, an async tool is cancelled and a sync one has `ctx.cancelled` set ([registry.md](registry.md)). Its answer is
  committed as the result. Bash's answer is what the command had printed, then `[interrupted after 2.3s]`.
- Each call costs two commits, its start and its result, about 6 ms each.
- Tools run in the log's project folder, one at a time.
- Run one runner per log. Two would take turns for the log and never run a call twice, but neither gains anything.

## Why it is this way

- **It acts on a cue.** It does not guess from the last message whether there is work. Whoever made the calls says so, as the bar
  does for the model.
- **The start is committed before the tool runs.** A Writer's uncommitted writes die with its process. Only a committed start lets
  the next runner know that a call was taken.
- **Cut-off calls are found at startup and on each cue.** The old runner looked on every change to the log, which needed a cache of
  what it had read. Checking at startup covers a runner that died and was started again. Checking on a cue covers one that never
  stopped.
- **The tool is raced against `outranked_changed()`.** It is the same shape as the provider's reply. A stop is acted on the moment
  it is asked, even while the tool is blocked in a thread or a command, not when the tool next looks.
- **Stopping does not cue anyone.** Whoever outranked the runner writes why, the way a stop does for the provider.
