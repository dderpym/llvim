"""std/panels/input/commands.py: commands are values, and the basic ones."""

from llvim.std.panels.input.commands import EXIT, HELP, QUIT, Command, Context, command


def context(said=None, ended=None, commands=(QUIT, EXIT, HELP)):
    return Context(None, (said if said is not None else []).append, lambda: (ended if ended is not None else []).append(1), {c.name: c for c in commands})


def test_quit_and_exit_end_the_session_and_help_lists_the_commands_it_was_given():
    ended, said = [], []
    for c in (QUIT, EXIT):
        c.run(context(said, ended), "")
    HELP.run(context(said, ended), "")
    assert ended == [1, 1] and "/quit" in said[0] and "/help" in said[0]


def test_command_makes_a_function_a_command_and_registers_nothing():
    seen = []

    @command("zz", "help text")
    def zz(ctx, arg):
        seen.append(arg)

    assert isinstance(zz, Command) and (zz.name, zz.help) == ("zz", "help text")
    zz.run(context(), "a")
    assert seen == ["a"]
