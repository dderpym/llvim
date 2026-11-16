"""std/panels/logviewer/render.py: one message as plain text, through a chain of renderers."""

import importlib

from llvim.std.panels.logviewer.box import Renderer, chain

render = importlib.import_module("llvim.std.panels.logviewer.render")  # the package exports a function of the same name


def test_renderer_makes_a_text_function_a_renderer_and_one_that_fails_is_skipped_to_the_next(entry):
    given = [
        render.renderer(lambda tags: 1 / 0)(lambda tags, content: "the match raises"),
        render.renderer(lambda tags: True)(lambda tags, content: 1 / 0),
        render.renderer(lambda tags: True)(lambda tags, content: None),
        render.renderer(lambda tags: True)(lambda tags, content: "fine"),
    ]
    assert all(isinstance(r, Renderer) for r in given)
    assert render.render(entry(["a"], "x"), chain(given)) == "fine"


def test_a_text_renderer_gets_the_content_cleaned_of_control_characters(entry):
    shout = render.renderer(lambda tags: True)(lambda tags, content: content.upper())
    assert render.render(entry(["a"], "hi\x1b[2J"), chain([shout])) == "HI[2J"


def test_with_no_renderers_given_the_built_in_ones_render(entry):
    assert render.render(entry(["note"], "x")) == "\x1b[1;36mnote\x1b[0m\nx\n\n"
