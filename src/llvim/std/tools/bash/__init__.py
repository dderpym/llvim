"""std/tools/bash: bash as the values a start script hands out: TOOL and TERMINAL (what a model calls), BOX (how a viewer shows a call) and
COMMAND (`/bash` in the input bar). Importing it registers nothing."""

from llvim.std.tools.bash.box import BOX
from llvim.std.tools.bash.command import COMMAND
from llvim.std.tools.bash.tool import TERMINAL, TOOL

__all__ = ["BOX", "COMMAND", "TERMINAL", "TOOL"]
