"""session.py: a start script lays panes out with a Session, and llvim-run finds what a pane runs again by name. tmux is
a stub."""

import shlex
import sys

import pytest

from llvim import session as sessionmod
from llvim.session import SCRIPT_MODULE, Session, call, load, spec


@pytest.fixture
def script(tmp_path, monkeypatch):
    """A start script beside a module of its own, imported fresh."""
    monkeypatch.delitem(sys.modules, SCRIPT_MODULE, raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))
    (tmp_path / "mine.py").write_text("RAN = []\n")
    path = tmp_path / "start.py"
    path.write_text(
        "import mine\n"
        "class Panel:\n"
        "    def run(self): mine.RAN.append('panel')\n"
        "def plain(): mine.RAN.append('plain')\n"
        "def start(s): pass\n"
        "nested = lambda: None\n"
    )
    return path


class FakeTmux:
    def __init__(self):
        self.calls, self.made = [], iter(f"%{n}" for n in range(10, 99))

    def __call__(self, *args):
        self.calls.append(args)
        return next(self.made) + "\n" if "-P" in args else ""


def test_a_top_level_function_of_the_script_or_of_a_module_runs_in_a_pane_by_name_and_a_lambda_cannot(script):
    module = load(script)
    assert spec(module.plain, script) == f"{script}:plain"
    assert spec(sessionmod.Session, script) == "llvim.session:Session"
    with pytest.raises(TypeError, match="cannot run in a pane"):
        spec(module.nested, script)
    with pytest.raises(TypeError, match="cannot run in a pane"):
        spec(lambda: None, script)


def test_a_pane_imports_the_script_again_calls_the_function_and_runs_what_it_returns(script):
    load(script)
    mine = sys.modules["mine"]  # the script imported a module beside it
    call(f"{script}:plain")
    call(f"{script}:Panel")
    assert mine.RAN == ["plain", "panel"]


def test_split_and_window_make_panes_running_their_programs_where_asked_and_named(script, monkeypatch):
    monkeypatch.setenv("LLVIM_PROJECT", str(script.parent))
    module, tmux = load(script), FakeTmux()
    s = Session(script, tmux, here="%1")
    bar = s.split(s.here, below=5, run=module.plain, name="input")
    s.window(run="htop")
    assert bar.id == "%10"
    split, named, window = tmux.calls
    assert split[:5] == ("split-window", "-v", "-l", "5", "-t") and split[5] == "%1" and split[7] == str(script.parent)
    assert split[-1] == "exec " + shlex.join(["llvim-run", f"{script}:plain"])
    assert named == ("set-option", "-w", "-t", "%10", "@llvim_pane_input", "%10")
    assert window[0] == "new-window" and window[-1] == "htop"  # a shell command runs as it is
    with pytest.raises(TypeError, match="one of below="):
        s.split(bar, run="x")


def test_here_becomes_its_program_once_start_has_returned(script, monkeypatch):
    module, tmux, execs = load(script), FakeTmux(), []
    monkeypatch.setattr(sessionmod.os, "execvp", lambda file, argv: execs.append(argv))
    s = Session(script, tmux, here="%1")
    s.here.run(module.plain, name="viewer")
    assert execs == [] and tmux.calls == [("set-option", "-w", "-t", "%1", "@llvim_pane_viewer", "%1")]
    s.finish()
    assert execs == [["sh", "-c", "exec " + shlex.join(["llvim-run", f"{script}:plain"])]]


def test_a_start_script_without_start_is_refused_with_its_name(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, SCRIPT_MODULE, raising=False)
    (tmp_path / "start.py").write_text("x = 1\n")
    with pytest.raises(SystemExit, match="no start"):
        sessionmod.start(tmp_path / "start.py")
