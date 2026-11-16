"""The shipped start script: `llvim` runs it unless you write `$LLVIM_HOME/start.py`. Copy it and change anything.

Each function is what runs in one pane: `llvim-run` imports this file again there and calls it. So they are top-level, and
importing this file starts nothing; `start` lays the panes out, once, in the first pane. See docs/session.md.
"""

from llvim.std import env
from llvim.std.panels.input import STANDARD, Input
from llvim.std.panels.logviewer import Viewer
from llvim.std.panels.status import Status
from llvim.std.providers.openai import OpenAI


def viewer():
    Viewer().run()


def palette():
    Input(commands=STANDARD).run()


def model():
    OpenAI().run()


def start(s):
    bar = s.split(s.here, below=5, run=palette, name="input")  # the bar's 3 rows, the status line above it, and a border
    s.split(bar, above=1, run=Status, name="status")
    bar.focus()
    if s.env.get("LLVIM_MODEL") or (env.home() / "openai.toml").exists():
        s.window(run=model)  # the provider, in the background, once it has a model
    s.here.run(viewer, name="viewer")
