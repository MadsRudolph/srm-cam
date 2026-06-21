from gerber2rml.toolpath import Move


def test_move_defaults_to_feed():
    m = Move(1.0, 2.0, -0.1)
    assert (m.x, m.y, m.z) == (1.0, 2.0, -0.1)
    assert m.rapid is False


def test_move_can_be_rapid():
    assert Move(0, 0, 2.0, rapid=True).rapid is True
