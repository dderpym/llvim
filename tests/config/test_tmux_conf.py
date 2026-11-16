"""config/tmux.conf: the config llvim starts tmux with. Needs a real tmux."""

import os
import subprocess
import time

import pytest
from llvim.cli import CONFIG

pytestmark = pytest.mark.needs_tmux


def server(tmp_path, name):
    sock = f"llvim{name}{tmp_path.name[-6:]}"

    def tmux(*args, env=None):
        return subprocess.run(["tmux", "-L", sock, "-f", str(CONFIG / "tmux.conf"), *args], capture_output=True, text=True, env=env).stdout

    return tmux


def test_the_wheel_scrolls_history_and_leaves_it_at_the_bottom(tmp_path):
    tmux = server(tmp_path, "wheel")
    try:
        tmux("new-session", "-d", "-s", "s", "-x", "80", "-y", "24", "seq 1 300; sleep 30")
        assert "WheelUpPane" in tmux("list-keys", "-T", "root")
        copy = tmux("list-keys", "-T", "copy-mode-vi")
        assert "WheelUpPane" in copy and "WheelDownPane" in copy and len(copy.strip().splitlines()) == 2  # nothing else is bound
        for _ in range(50):
            if "300" in tmux("capture-pane", "-p", "-t", "s"):
                break
            time.sleep(0.1)
        tmux("copy-mode", "-e", "-t", "s")  # what the wheel binding does first
        tmux("send-keys", "-t", "s", "-X", "-N", "3", "scroll-up")  # then each notch
        assert tmux("display", "-p", "-t", "s", "#{pane_in_mode} #{scroll_position}").split() == ["1", "3"]
        tmux("send-keys", "-t", "s", "-X", "-N", "3", "scroll-down")
        assert tmux("display", "-p", "-t", "s", "#{pane_in_mode}").strip() == "0"  # back at the bottom: out of history
    finally:
        tmux("kill-server")


def test_a_session_started_later_takes_the_llvim_settings_of_its_own_client(tmp_path):
    tmux = server(tmp_path, "env")
    try:
        tmux("new-session", "-d", "-s", "first", "sleep 30")  # the server is up, without LLVIM_MODEL
        later = {**os.environ, "LLVIM_MODEL": "some-model", "LLVIM_STORE": "/some/store", "LLVIM_HOME": "/some/home"}
        tmux("new-session", "-d", "-s", "second", "sleep 30", env=later)
        for name, value in (("LLVIM_MODEL", "some-model"), ("LLVIM_STORE", "/some/store"), ("LLVIM_HOME", "/some/home")):
            assert tmux("show-environment", "-t", "second", name).strip() == f"{name}={value}", name
        assert "\nLLVIM_MODEL=" not in "\n" + tmux("show-environment", "-t", "first")
    finally:
        tmux("kill-server")


def test_every_terminal_may_set_the_clipboard_so_the_viewer_can_copy(tmp_path):
    tmux = server(tmp_path, "clip")
    try:
        tmux("new-session", "-d", "-s", "s", "sleep 30")
        assert "*:clipboard" in tmux("show", "-g", "terminal-features")
        assert tmux("show", "-gv", "set-clipboard").strip() == "on"
    finally:
        tmux("kill-server")
