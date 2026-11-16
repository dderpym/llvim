# `std/panels/input/commands.py`: Command, Context

The slash commands of the input bar, as values, and the basic ones.

```python
@command("fork", "start another log from here", complete=lambda arg: [(n, "") for n in ("main", "alt") if n.startswith(arg)])
async def fork(ctx, arg):
    ctx.notice(f"forking as {arg}")
```

- `Command(name, help, run, complete=None)`: `run(context, argument)` is called with the text after the name; it may be `async`.
  `complete(argument)` gives `(argument, help)` suggestions for what is typed after the command.
- `command(name, help, complete=None)`: a decorator that makes a function that `Command`.
- `Context(log, notice, quit, commands, panes=None)`: what a command may use. `notice(text)` says something under the prompt.
- `QUIT`, `EXIT`: end the session. `HELP`: lists the commands.

## Why it is this way

- **Values, not a registry.** A bar has the commands it is given, so two bars can have different ones, and nothing runs at import.
- **`run` may be `async`.** A command that claims the log, like `/continue`, must wait; the bar awaits it beside the keyboard.
