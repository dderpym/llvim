# llvim

A coding agent reduced to one concept: the **log**. A log is a sequence of messages, tracked like git.

## Use

```
llvim-openai --configure   # once: base URL, API key (typed hidden) and model, saved to ~/.llvim/openai.toml
cd your/project && llvim   # the log on top, a status line, and the input bar; Ctrl+Alt+Q leaves
```

`llvim alt` opens the log `alt` of the same project. The layout is a Python file you can copy and change: see
[docs/session.md](docs/session.md).

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

- [`llvim/`](docs/llvim.md)
  - [`cli.py`](docs/cli.md)
  - [`session.py`](docs/session.md)
  - [`config/`](docs/config/config.md)
    - [`config/start.py`](docs/config/start.md)
    - [`config/tmux.conf`](docs/config/tmux.md)
- [`core/`](docs/core/core.md)
  - [`core/git.py`](docs/core/git.md)
  - [`core/live.py`](docs/core/live.md)
  - [`core/log.py`](docs/core/log.md)
  - [`core/queue.py`](docs/core/queue.md)
  - [`core/watch.py`](docs/core/watch.md)
  - [`core/writer.py`](docs/core/writer.md)
- [`std/`](docs/std/std.md)
  - [`std/conversation.py`](docs/std/conversation.md)
  - [`std/cues.py`](docs/std/cues.md)
  - [`std/env.py`](docs/std/env.md)
  - [`std/panels/`](docs/std/panels/panels.md)
    - [`std/panels/input/`](docs/std/panels/input/input.md)
      - [`std/panels/input/bar.py`](docs/std/panels/input/bar.md)
      - [`std/panels/input/commands.py`](docs/std/panels/input/commands.md)
      - [`std/panels/input/complete.py`](docs/std/panels/input/complete.md)
      - [`std/panels/input/editor.py`](docs/std/panels/input/editor.md)
      - [`std/panels/input/generate.py`](docs/std/panels/input/generate.md)
      - [`std/panels/input/menu.py`](docs/std/panels/input/menu.md)
      - [`std/panels/input/pane.py`](docs/std/panels/input/pane.md)
      - [`std/panels/input/view.py`](docs/std/panels/input/view.md)
    - [`std/panels/keys.py`](docs/std/panels/keys.md)
    - [`std/panels/logviewer/`](docs/std/panels/logviewer/logviewer.md)
      - [`std/panels/logviewer/ansi.py`](docs/std/panels/logviewer/ansi.md)
      - [`std/panels/logviewer/app.py`](docs/std/panels/logviewer/app.md)
      - [`std/panels/logviewer/box.py`](docs/std/panels/logviewer/box.md)
      - [`std/panels/logviewer/boxes.py`](docs/std/panels/logviewer/boxes.md)
      - [`std/panels/logviewer/document.py`](docs/std/panels/logviewer/document.md)
      - [`std/panels/logviewer/markdown.py`](docs/std/panels/logviewer/markdown.md)
      - [`std/panels/logviewer/plain.py`](docs/std/panels/logviewer/plain.md)
      - [`std/panels/logviewer/render.py`](docs/std/panels/logviewer/render.md)
      - [`std/panels/logviewer/screen.py`](docs/std/panels/logviewer/screen.md)
      - [`std/panels/logviewer/text.py`](docs/std/panels/logviewer/text.md)
    - [`std/panels/status/`](docs/std/panels/status/status.md)
      - [`std/panels/status/bar.py`](docs/std/panels/status/bar.md)
      - [`std/panels/status/renderers.py`](docs/std/panels/status/renderers.md)
  - [`std/providers/`](docs/std/providers/providers.md)
    - [`std/providers/openai.py`](docs/std/providers/openai.md)
    - [`std/providers/openai_settings.py`](docs/std/providers/openai_settings.md)
  - [`std/tmux.py`](docs/std/tmux.md)
  - [`std/tools/`](docs/std/tools/tools.md)
    - [`std/tools/registry.py`](docs/std/tools/registry.md)
    - [`std/tools/calls.py`](docs/std/tools/calls.md)
    - [`std/tools/runner.py`](docs/std/tools/runner.md)
    - [`std/tools/bash/`](docs/std/tools/bash/bash.md)
      - [`std/tools/bash/tool.py`](docs/std/tools/bash/tool.md)
      - [`std/tools/bash/terminal.py`](docs/std/tools/bash/terminal.md)
      - [`std/tools/bash/settings.py`](docs/std/tools/bash/settings.md)
      - [`std/tools/bash/box.py`](docs/std/tools/bash/box.md)
      - [`std/tools/bash/command.py`](docs/std/tools/bash/command.md)
