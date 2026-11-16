"""config/start.py: the shipped start script. Needs a real tmux, and the commands on the PATH (as in `uv run pytest`)."""

import subprocess
import time

import pytest
from llvim.cli import command

pytestmark = pytest.mark.needs_tmux


ROLES = {"--start": "viewer", ":palette": "input", ":Status": "status", ":model": "openai"}  # what each pane runs


def role(start_command: str) -> str | None:
    return next((name for mark, name in ROLES.items() if mark in start_command), None)


@pytest.fixture
def layout(tmp_path, monkeypatch):
    """The shipped layout, started in a tmux of its own. Yields `(tmux, panes)`: panes is {role: (pane id, height)} for the
    viewer, input, status and openai."""
    monkeypatch.setenv("LLVIM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LLVIM_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("LLVIM_SOCKET", f"llvimlayout{tmp_path.name[-6:]}")
    monkeypatch.setenv("LLVIM_MODEL", "some-model")  # also starts the provider window
    project = tmp_path / "proj"
    project.mkdir()
    argv = command(project, "main")
    i = argv.index("new-session") + 1
    argv[i:i] = ["-d", "-x", "100", "-y", "30"]

    def tmux(*args):
        return subprocess.run(["tmux", "-L", argv[2], *args], capture_output=True, text=True).stdout

    subprocess.run(argv, check=True)
    try:
        for _ in range(100):  # the script lays the session out
            listed = [l.split(" ", 2) for l in tmux("list-panes", "-a", "-F", "#{pane_id} #{pane_height} #{pane_start_command}").splitlines()]
            panes = {role(cmd): (pane, height) for pane, height, cmd in listed if role(cmd)}
            if len(panes) == 4:
                break
            time.sleep(0.1)
        yield tmux, panes
    finally:
        tmux("kill-server")


def test_the_script_lays_out_the_viewer_a_status_line_and_a_three_line_input_bar_and_starts_the_provider(layout):
    tmux, panes = layout
    assert set(panes) == {"viewer", "input", "status", "openai"}
    assert panes["input"][1] == "3" and panes["status"][1] == "1"
    assert int(panes["viewer"][1]) >= 20  # the log gets the rest
    assert tmux("list-panes", "-F", "#{?pane_active,#{pane_id},}").split() == [panes["input"][0]]  # the cursor starts in the input bar
    recorded = {n: tmux("show-options", "-wqv", "@llvim_pane_" + n).strip() for n in ("viewer", "status", "input")}  # where the panels are, by name
    assert recorded == {n: panes[n][0] for n in ("viewer", "status", "input")}


def test_typing_into_the_viewer_or_the_status_line_ends_up_in_the_input_bar_with_focus(layout):
    """The whole path through the real programs: a panel that has focus and does not use a key passes it to the input bar."""
    tmux, panes = layout
    ids = {n: panes[n][0] for n in ("input", "status")}
    viewer = panes["viewer"][0]
    active = lambda: tmux("list-panes", "-F", "#{?pane_active,#{pane_id},}").split()[0]  # noqa: E731
    for name, pane in (("the viewer", viewer), ("the status line", ids["status"])):
        tmux("select-pane", "-t", pane)  # a click would do the same
        for _ in range(100):  # the program has taken the keyboard
            if tmux("display-message", "-p", "-t", pane, "#{alternate_on}").strip() == "1" or (pane == ids["status"] and tmux("capture-pane", "-p", "-t", pane).strip()):
                break
            time.sleep(0.05)
        tmux("send-keys", "-t", pane, "-l", f"typed-in-{name.split()[-1]}")
        for _ in range(100):
            if active() == ids["input"] and f"typed-in-{name.split()[-1]}" in tmux("capture-pane", "-p", "-t", ids["input"]):
                break
            time.sleep(0.05)
        assert active() == ids["input"], name
        assert f"typed-in-{name.split()[-1]}" in tmux("capture-pane", "-p", "-t", ids["input"]), name
        tmux("send-keys", "-t", ids["input"], "C-u")  # clear the line for the next


def test_the_menu_grows_the_input_pane_upwards_and_closing_it_puts_the_layout_back(layout):
    tmux, panes = layout
    ids = {n: panes[n][0] for n in ("input", "status")}
    heights = lambda: {n: int(tmux("display-message", "-p", "-t", p, "#{pane_height}")) for n, p in ids.items()}  # noqa: E731
    before = heights()

    def wait(check):
        for _ in range(100):
            if check():
                return True
            time.sleep(0.05)
        return False

    wait(lambda: "›" in tmux("capture-pane", "-p", "-t", ids["input"]))
    tmux("send-keys", "-t", ids["input"], "-l", "/")
    assert wait(lambda: "/quit" in tmux("capture-pane", "-p", "-t", ids["input"])), tmux("capture-pane", "-p", "-t", ids["input"])
    grown = heights()
    assert grown["input"] > before["input"] and grown["status"] == before["status"]
    tmux("send-keys", "-t", ids["input"], "C-u")
    assert wait(lambda: heights() == before), (before, heights())
