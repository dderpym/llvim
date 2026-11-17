"""std/tools/bash: bash as three values a start script hands out: TOOL (what a model calls), BOX (how a viewer shows a call) and
COMMAND (`/bash` in the input bar). Importing it registers nothing."""

from llvim.std.tools.bash.box import BOX
from llvim.std.tools.bash.command import COMMAND
from llvim.std.tools.bash.tool import TOOL

__all__ = ["BOX", "COMMAND", "TOOL"]
