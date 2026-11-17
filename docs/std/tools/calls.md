# `std/tools/calls.py`: pending, cut_off, call, answer

How tool calls look in a log. The provider writes calls, the [runner](runner.md) writes starts and results, and a viewer groups them
into one box. Each of them goes through this file.

```python
writer.append(call("bash", '{"command": "ls"}', "call_1", model="gpt"))
writer.append(answer(START, the_call))
writer.append(answer(RESULT, the_call, "a.txt", error=False))
pending(entries(log.read()))     # the calls still to be answered
```

| Message | Tags | Text | Fields |
|---|---|---|---|
| a call | `["tool_call", <tool>]` | the arguments, as JSON text | `call_id`, and `model` or `user` |
| a start | `["tool_start", <tool>]` | | `call_id`, and `user` if the call has it |
| a result | `["tool_result", <tool>]` | what the tool returned | `call_id`, `error`, and `user` if the call has it |

- `call(tool, arguments, id, **extra)`: a call message.
- `answer(tag, of, content="", **extra)`: the start or result of the call `of`, carrying its tool, id and `user`.
- `call_id(entry)`, `name(entry)` (its tool, or `""`), `kind(entry)` (its first tag), `by_user(entry)`.
- `pending(entries)`: the calls with no result that the user has not spoken over, oldest first. A call of the user's (`user=True`)
  stays waiting after they speak.
- `cut_off(entries)`: the calls with a start and no result, spoken over or not.

## Using it

- A result is matched to its call by `call_id`, wherever it sits. A result committed after the user spoke still answers its call.
- `cut_off` means a dead runner only when read by a runner that holds the log. While a runner holds it, the call it is running
  looks the same.
- Both scan every entry. The runner calls them once per cue, not per change, so a cache was not worth keeping.

## Why it is this way

- **The tool's name is in the tags.** So a viewer shows `tool_call bash` with no other knowledge, and a renderer claims "bash" calls
  by their tags.
- **The arguments are the text.** A provider streams them with `extend`, as it streams an answer.
- **A start, committed before the call runs.** A command is not always safe to repeat (`rm`, `git push`). If the runner dies while a
  call runs, the start says it was taken, so the call is answered as interrupted and the model decides what to do. It is never run
  again.
- **Speaking over a call drops it.** After the user's message the model has moved on, so its old calls are not run. A call the user
  made is theirs, and is still waited for.
