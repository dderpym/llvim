"""std/void/turns.py: a log as turns, each made of the elements that are voided together."""

from llvim.std.void.turns import Voided, turns


def shape(found):
    """Each turn as the tags of the first message of each of its elements, with how many messages the element holds."""
    return [[(e.entries[0].tags[0], len(e.entries)) for e in turn.elements] for turn in found]


def test_a_turn_is_a_user_message_and_everything_up_to_the_next(entry):
    log = [
        entry(["user"], "one"),
        entry(["assistant"], "a"),
        entry(["user"], "two"),
        entry(["thinking"], "hm"),
        entry(["assistant"], "b"),
    ]
    found = turns(log)
    assert shape(found) == [[("user", 1), ("assistant", 1)], [("user", 1), ("thinking", 1), ("assistant", 1)]]
    assert [turn.label for turn in found] == ["one", "two"] and found[1].id == log[2].id


def test_what_comes_before_the_first_user_message_is_a_turn_of_its_own(entry):
    found = turns([entry(["system"], "be brief"), entry(["user"], "hi")])
    assert shape(found) == [[("system", 1)], [("user", 1)]] and found[0].label == "system  be brief"


def test_the_note_a_stop_leaves_stays_in_the_turn_it_stopped(entry):
    found = turns(
        [entry(["user"], "go"), entry(["assistant"], "par"), entry(["user", "stop"], "User stopped this response.")]
    )
    assert shape(found) == [[("user", 1), ("assistant", 1), ("user", 1)]]


def test_a_call_its_start_and_its_result_are_one_element_wherever_the_result_is(entry):
    log = [
        entry(["user"], "look"), entry(["tool_call", "bash"], '{"command": "ls"}', call_id="a"),
        entry(["tool_call", "bash"], "{}", call_id="b"), entry(["tool_start", "bash"], call_id="a"),
        entry(["tool_result", "bash"], "a.txt", call_id="a"), entry(["tool_result", "bash"], "x", call_id="b"),
    ]  # fmt: skip
    (turn,) = turns(log)
    assert shape([turn]) == [[("user", 1), ("tool_call", 3), ("tool_call", 2)]]
    assert turn.elements[1].label == 'tool_call bash  {"command": "ls"}'


def test_a_cue_is_no_element_of_its_own_it_goes_with_the_message_before_it(entry):
    log = [entry(["user"], "hi"), entry(["cue", "generate"]), entry(["assistant"], "yo"), entry(["cue", "generate"])]
    assert shape(turns(log)) == [[("user", 2), ("assistant", 2)]]


def test_voided_messages_are_grouped_as_what_they_were(entry):
    log = [entry(["user", "void"], "one"), entry(["cue", "generate", "void"]), entry(["user"], "two")]
    found = turns(log)
    assert shape(found) == [[("user", 2)], [("user", 1)]] and found[0].label == "one"


def test_a_turn_or_element_is_voided_in_part_until_every_message_of_it_is(entry):
    log = [
        entry(["user"], "one"),
        entry(["assistant", "void"], "a"),
        entry(["user", "void"], "two"),
        entry(["user"], "three"),
    ]
    first, second, third = turns(log)
    assert (first.voided, second.voided, third.voided) == (Voided.PART, Voided.ALL, Voided.NONE)
    assert [e.voided for e in first.elements] == [Voided.NONE, Voided.ALL]


def test_an_empty_log_has_no_turns():
    assert turns([]) == []
