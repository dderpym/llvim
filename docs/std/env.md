# `std/env.py`: home, log, settings

Where llvim keeps its settings, which log a program is for, and reading a settings file there.

```python
log = env.log()                                         # $LLVIM_LOG of $LLVIM_PROJECT
data = env.settings("openai.toml", lambda key, value: None if key == "model" else f"{key} is not a setting")
```

- `home()`: `$LLVIM_HOME`, else `~/.llvim`. An empty value counts as unset.
- `log()`: the log `$LLVIM_LOG` (default `main`) of the project `$LLVIM_PROJECT` (default the working folder).
- `settings(file, problem)`: what `home()/file` holds as TOML, or `{}` without the file.
  - not TOML: raises `ValueError` naming the file;
  - `problem(key, value)` says what is wrong with an entry: raises `ValueError` naming the file and that.

## Why it is this way

- **The store is core's, the settings are std's.** Core finds its repos with `$LLVIM_STORE` ([log.md](../core/log.md)), which
  defaults to `~/.llvim/sessions`, inside the default home. Settings, the input history and the like are std's business, so
  `$LLVIM_HOME` is read here and core knows nothing of it.
- **The session is named by the environment.** Every program in a session runs in its own pane, so the environment is how they all
  find the same log without being told.
- **Each program checks its own settings.** `settings` takes a `problem` function, so the file's rules live beside the program that
  reads it ([openai_settings.md](providers/openai_settings.md)) and a mistake is reported with the file's name.
