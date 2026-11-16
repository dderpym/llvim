"""std/panels/logviewer/ansi.py: text with colour codes, measured and cut in terminal cells."""

import random

from llvim.std.panels.logviewer import ansi


def plain(s):
    return ansi.strip(s)


# --- measuring ---


def test_width_counts_cells_not_codes():
    assert ansi.width("\x1b[1;36mabc\x1b[0m") == 3
    assert ansi.width("日本") == 4 and ansi.width("é") == 1 and ansi.width("é") == 1  # wide, precomposed, combining


# --- wrapping ---


def test_wrap_cuts_at_the_width_and_a_line_that_just_fits_is_one_row():
    assert ansi.wrap("abcdefgh", 3) == ["abc", "def", "gh"]
    assert ansi.wrap("abc", 3) == ["abc"] and ansi.wrap("", 5) == [""]


def test_the_fast_paths_for_plain_and_coloured_ascii_agree_with_the_careful_one():
    rng, codes = random.Random(7), ["\x1b[1m", "\x1b[0m", "\x1b[38;5;245m", "\x1b[0;1;36m", "\x1b[m"]
    for _ in range(300):
        pieces = [rng.choice(codes) if rng.random() < 0.3 else "".join(rng.choices("abc def,ghi", k=rng.randint(1, 15))) for _ in range(rng.randint(1, 8))]
        line, cols = "".join(pieces), rng.randint(1, 12)
        careful = ansi.wrap(line + "​", cols)  # a zero-width character is not printable ASCII: the careful path, same layout
        assert [r.replace("​", "") for r in careful] == ansi.wrap(line, cols), (line, cols)
        assert ansi.width(line) == ansi.width(line + "​")


# --- cutting and highlighting ---


def test_highlight_reverses_the_cells_and_puts_it_back_after_a_reset_inside():
    assert ansi.highlight("abcdef", 2, 4) == "ab\x1b[7mcd\x1b[27mef" and ansi.highlight("abc", 1) == "a\x1b[7mbc\x1b[27m"
    lit = ansi.highlight("\x1b[31mab\x1b[0mcdef", 1, 5)
    assert plain(lit) == "abcdef" and lit.count("\x1b[7m") == 2 and lit.endswith("\x1b[27mf")


def test_tabs_become_spaces_to_the_next_stop_whatever_the_colours_and_pad_fills_a_row_to_its_width():
    assert ansi.expand_tabs("ab\tc") == "ab      c" and plain(ansi.expand_tabs("\x1b[1mab\x1b[0m\tc")) == "ab      c"
    assert ansi.pad("ab", 5) == "ab   " and ansi.width(ansi.pad("a\tb", 20)) == 20 and plain(ansi.pad("abcdef", 3)) == "abc"
