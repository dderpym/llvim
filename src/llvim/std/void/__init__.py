"""std/void: voiding, as three values a start script hands out: BOX (a viewer shows a voided message as nothing), CONTEXT (a
provider leaves it out of what the model is sent) and COMMAND (`/void`, the picker). Importing it registers nothing."""

from llvim.std.void.box import BOX
from llvim.std.void.command import COMMAND
from llvim.std.void.context import CONTEXT
from llvim.std.void.tag import VOID, is_void

__all__ = ["BOX", "COMMAND", "CONTEXT", "VOID", "is_void"]
