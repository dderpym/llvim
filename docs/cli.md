# `cli.py`: the `llvim` command

`llvim [log]` starts tmux with the shipped config and runs a start script in it. That is all it does; `log` defaults to `main`.

```
tmux -L llvim -f <config/tmux.conf> new-session -A -s <session> -c <project> -e LLVIM_PROJECT=... -e LLVIM_LOG=... llvim-run --start <start.py>
```

- `command(project, log="main")`: the tmux command line, for the working folder as the project.
- `session_name(project, log)`: `<project folder>-<log>-<hash>`, without the `.` and `:` tmux forbids.
- `start_script()`: `$LLVIM_HOME/start.py`, else `$LLVIM_HOME/start` (a shell script), else the shipped
  [config/start.py](config/start.md).
- `starter(script)`: a Python script runs with `llvim-run --start` ([session.md](session.md)), any other with `sh`.
- `main()`: becomes tmux. No tmux on the `PATH`: exits saying so.

## Using it

- Running `llvim` again for the same project and log attaches to its session; several terminals on one session share one view.
- llvim's tmux is its own server: `tmux -L llvim ls` lists its sessions, and your own tmux config never applies.
- The variables it reads, all through [std/env.py](std/env.md) and the provider's settings
  ([openai_settings.md](std/providers/openai_settings.md)); an empty value counts as unset:

| Variable | Meaning |
|---|---|
| `LLVIM_HOME` | Settings and the start script. Default `~/.llvim` |
| `LLVIM_STORE` | Where the logs are kept ([log.md](core/log.md)). Default `~/.llvim/sessions` |
| `LLVIM_SOCKET` | The name of llvim's tmux server. Default `llvim` |
| `LLVIM_MODEL` | The provider's model; the shipped start script also starts the provider when it is set |
| `LLVIM_PROJECT`, `LLVIM_LOG` | Set in each session, for the start script and its panes |

## Why it is this way

- **It does the minimum.** Layout, panels and what runs in them are the start script's; the command only gives them a tmux.
- **Its own server.** A separate socket keeps llvim's locked-down config away from your tmux, and yours from it.
- **One session per project and log.** The hash keeps two projects with the same folder name, or two logs, apart.
