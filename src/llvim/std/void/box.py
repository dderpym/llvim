"""std/void/box.py: BOX, the viewer's renderer for voided messages: they show nothing."""

from llvim.std.panels.logviewer.box import Renderer, alone
from llvim.std.panels.logviewer.boxes import Hidden
from llvim.std.void.tag import is_void

BOX = Renderer(lambda entry: alone(entry) if is_void(entry) else None, Hidden, "void")
