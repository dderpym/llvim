# `std/tools/bash/settings.py`: setting

The numbers of the bash tool. Each comes from `$LLVIM_BASH_<NAME>`, else `<name>` in `$LLVIM_HOME/bash.toml`, else its default.

```toml
# ~/.llvim/bash.toml
max_lines = 500
timeout = 300
```

| Name | Default | What |
|---|---|---|
| `timeout` | 120 | seconds before a command is stopped, when the model gives none |
| `settle` | 1.5 | seconds a [kept terminal](shared.md)'s screen must be still before the model is shown it |
| `user_timeout` | 3600 | seconds a kept terminal stays the user's if they never hand it back |
| `max_lines` | 2000 | the most lines the model is given whole; more go to a file |
| `max_bytes` | 50,000 | the same, in bytes |
| `long_line_bytes` | 10,000 | a line at least this long is pointed out in the note (0: none is) |
| `long_line_count` | 5 | how many long lines are numbered; the rest are counted |
| `preview_chars` | 500 | the note's preview, half from the start and half from the end (0: none) |

- `setting(name)`: the number. An unknown name raises `KeyError`. A value that is not a number, or is negative, raises
  `ValueError`, naming the variable or the file it came from.

## Why it is this way

- **Read when a call runs, never on import.** A broken `bash.toml` then fails a bash call, with a message the model and the user
  see. If it were read on import, every program that loads the tools would fail to start.
- **The environment wins.** One session can be changed without editing the file every session reads.
