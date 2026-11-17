"""The shipped start script: `llvim` runs it unless you write `$LLVIM_HOME/start.py`. Copy it and change anything.

Each function is what runs in one pane: `llvim-run` imports this file again there and calls it. So they are top-level, and
importing this file starts nothing; `start` lays the panes out, once, in the first pane. See docs/session.md.
"""

from llvim.std import env, void
from llvim.std.panels.input import STANDARD, Input
from llvim.std.panels.logviewer import Viewer
from llvim.std.panels.status import Status
from llvim.std.providers.openai import OpenAI
from llvim.std.tools import bash
from llvim.std.tools.runner import Runner

TOOLS = [bash.TOOL, bash.TERMINAL]  # what the model is offered and the runner runs: add your own Tool values here


def viewer():
    Viewer(renderers=[void.BOX, bash.BOX]).run()  # void first: a voided bash call shows nothing


def palette():
    Input(commands=[*STANDARD, bash.COMMAND, void.COMMAND]).run()


def status():
    Status(context=[void.CONTEXT]).run()


def model():
    OpenAI(tools=TOOLS, context=[void.CONTEXT]).run()


def tools():
    Runner(tools=TOOLS).run()


def start(s):
    bar = s.split(
        s.here, below=5, run=palette, name="input"
    )  # the bar's 3 rows, the status line above it, and a border
    s.split(bar, above=1, run=status, name="status")
    bar.focus()
    if s.env.get("LLVIM_MODEL") or (env.home() / "openai.toml").exists():
        s.window(run=model)  # the provider, in the background, once it has a model
    s.window(run=tools)  # runs the calls the model makes; idle until there are some
    s.here.run(viewer, name="viewer")
