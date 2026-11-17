"""The undo stack behind Ctrl+Z on the stage and the laser page."""
import pytest

from gerber2rml.gui2.undo import PlacementUndo


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def stack(qt_app):
    clock = Clock()
    s = PlacementUndo(clock=clock)
    s.clock = clock
    return s


def test_undo_goes_back_and_redo_forward(stack):
    stack.push((0, 0))
    stack.push((5, 0))
    assert stack.undo((9, 9)) == (5, 0)
    assert stack.undo((5, 0)) == (0, 0)
    assert stack.undo((0, 0)) is None
    assert stack.redo((0, 0)) == (5, 0)
    assert stack.redo((5, 0)) == (9, 9)
    assert not stack.can_redo()


def test_a_new_change_forgets_the_redo(stack):
    stack.push((0, 0))
    stack.undo((1, 1))
    assert stack.can_redo()
    stack.push((0, 0))
    assert not stack.can_redo()


def test_a_burst_with_one_key_is_one_step(stack):
    for x in range(10):                 # a spin box held down
        stack.push((x, 0), merge="x")
        stack.clock.t += 0.1
    assert stack.undo((10, 0)) == (0, 0)
    assert not stack.can_undo()


def test_a_pause_starts_a_new_step(stack):
    stack.push((0, 0), merge="x")
    stack.clock.t += 5
    stack.push((1, 0), merge="x")
    assert stack.undo((2, 0)) == (1, 0)
    assert stack.undo((1, 0)) == (0, 0)


def test_a_different_key_is_a_new_step(stack):
    stack.push((0, 0), merge="x")
    stack.push((1, 0), merge="y")
    assert stack.undo((1, 1)) == (1, 0)


def test_steps_that_changed_nothing_are_skipped(stack):
    stack.push((0, 0))
    stack.push((3, 3))
    assert stack.undo((3, 3)) == (0, 0)


def test_a_restore_is_not_recorded(stack):
    stack.push((0, 0))
    stack.restoring = True
    stack.push((7, 7))
    stack.restoring = False
    assert stack.undo((1, 1)) == (0, 0)
    assert not stack.can_undo()


def test_the_stack_is_bounded(qt_app):
    s = PlacementUndo(limit=3)
    for x in range(10):
        s.push((x,))
    got = [s.undo((99,)), s.undo((0,)), s.undo((0,)), s.undo((0,))]
    assert got == [(9,), (8,), (7,), None]


def test_changed_fires_for_the_button(stack):
    seen = []
    stack.on_change = lambda: seen.append((stack.can_undo(), stack.can_redo()))
    stack.push((0, 0))
    stack.undo((1, 1))
    assert seen[0] == (True, False)
    assert seen[-1] == (False, True)
