# llvim

A coding agent reduced to one concept: the **log**. A log is a sequence of messages, tracked like git.

## Develop

Needs Python 3.12+, `uv` and git (and tmux). On nix:

```
nix develop            # uv, python, git, tmux
uv sync
uv run pytest
```

How the code, docs and tests are written: [AGENTS.md](AGENTS.md).

## Docs

One page per source file, explaining why it is shaped the way it is:

- [llvim](docs/llvim.md)
  - [core](docs/core/core.md): [store](docs/core/store.md), [repo](docs/core/repo.md), [layout](docs/core/layout.md), [history](docs/core/history.md), [log](docs/core/log.md), [writer](docs/core/writer.md), [journal](docs/core/journal.md), [lock](docs/core/lock.md), [cue](docs/core/cue.md)
