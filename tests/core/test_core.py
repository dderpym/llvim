"""core/__init__.py: the public names of core, all importable from `llvim.core`."""

import llvim.core


def test_every_public_name_is_the_one_its_module_defines():
    for name in llvim.core.__all__:
        value = getattr(llvim.core, name)
        module = getattr(value, "__module__", None)
        if module is not None and module.startswith("llvim.core."):
            assert getattr(__import__(module, fromlist=[name]), name) is value, name


def test_a_caller_can_annotate_and_catch_everything_a_log_gives_or_raises():
    expected = {"Log", "Writer", "Snapshot", "Message", "Request", "Author", "Commit", "LLVIM"}
    errors = {"GitError", "Moved", "Released", "Committing"}
    assert expected | errors <= set(llvim.core.__all__)
    for name in errors:
        assert issubclass(getattr(llvim.core, name), Exception), name
