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
