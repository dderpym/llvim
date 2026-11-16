# `std/panels/status/renderers.py`: activity, model

The built-in status renderers, and `BUILTIN`, the two in order.

```python
Status(renderers=[activity])          # without the model
```

- `activity(state)`: one phrase, and while the turn runs, its seconds (`thinking · 4s`):
  - nobody holds the log: *awaiting your input*; *waiting for a model* under a cue; *error: ...* (its first line) after an error;
  - a provider holds it: *thinking* or *writing* while that streams, its reconnect note while it waits to try again, else *waiting
    for the model*;
  - the input bar holds it: *sending*; anyone else: *busy:* and what they claimed with.
- `model(state)`: the model of the provider at work, else the one that wrote the last reply; `None` before any.

## Why it is this way

- **Grey when it waits for you, cyan while it works, red when it failed.** A glance says whose turn it is.
- **Whole seconds.** A clock that shows tenths changes ten times a second, which is the flashing the bar exists to avoid.
