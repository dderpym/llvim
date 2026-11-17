# `std/tools/registry.py`: Tool, Registry, Context, Result, ToolError

A `Tool` is a function a model may call, described once for any provider: a name, a sentence, and a JSON Schema of its arguments. A
`Registry` is the tools one program was given. A provider offers them; the [runner](runner.md) calls `registry.run` with what the
model sent.

```python
@tool("now", "The current time.", {"type": "object", "properties": {}})
def now(arguments, ctx):                    # sync: runs in a thread
    return time.ctime()

@tool("note", "Say something in the log while working.", {"type": "object"})
async def note(arguments, ctx):             # async: runs on the runner's loop, with its writer
    ctx.writer.append(encode(["status"], "working"))
    ...

registry = Registry([bash.TOOL, now, note])
result = await registry.run("now", "{}", Context(cwd, call, log, writer))
result.text, result.error
```

- `Tool(name, description, parameters, run)`: `run(arguments, ctx)` returns the text, or an awaitable of it. `is_async` says which.
- `tool(name, description, parameters)`: a decorator that makes a function a `Tool`.
- `Registry(tools)`: `register(tool, replace=False)` (a name twice raises `ValueError` unless replacing), `get`, iteration, `in`,
  `len`.
- `run(name, arguments, ctx)`, async: the `Result`. `arguments` is JSON text or already parsed; blank text is `{}`.
  - An unknown tool, arguments that are not JSON, a missing required argument, a wrong simple type: an error `Result` that says what
    to fix.
  - The tool raises `ToolError("why")`: an error `Result` of that message. It raises anything else: an error `Result` naming the
    exception.
  - Cancelled: an async tool is cancelled. A sync one has `ctx.cancelled` set, and its answer is still awaited and returned.
- `Context(cwd, call, log, writer, cancelled)`: the project folder, the `tool_call` entry, the log, the runner's held writer (async
  tools only; a sync tool gets `None`), and the event a sync tool watches.
- `check(schema, arguments)`: what is wrong with the arguments, or `None`.

## Using it

- An async tool shares the runner's writer. It may append and extend, and should remove a `status` message it wrote before it
  returns: the runner commits whatever is there with the result. It must not commit, release, or wait on `outranked_changed()`:
  the runner does those, and two waiters on one writer take each other's wake-ups.
- To stop cleanly, an async tool catches `CancelledError`, cleans up, and returns or raises `ToolError` with what it had done. The
  runner writes that as the result. If it lets the cancel through, the result is `[interrupted]`.
- A sync tool that never looks at `ctx.cancelled` holds the stop up until it returns.

## Why it is this way

- **Errors are results.** A model that sends bad arguments needs to be told what was wrong in the next message. An exception would
  end the turn instead.
- **Only what models get wrong is checked.** Not an object, a missing argument, a wrong simple type. A full JSON Schema validator
  would be a dependency for cases models do not produce.
- **Sync or async, chosen by the tool.** Most tools are a few lines that block, and a thread is right for them. A tool that works
  with the log, by writing into it, reading it, or awaiting a change, is an `async def` on the same loop as the runner, as every
  other program that holds a log is. Making every tool async was rejected because a blocking call in one would freeze the
  runner's watch for a stop.
- **A sync tool has no writer.** A Writer is not safe to use from two threads. Handing it out to a thread would work until two
  writes raced.
- **A cancelled thread is waited for.** Python cannot stop a thread. Returning at once would leave the tool running after its result
  was written, and a command it started would outlive the call.
